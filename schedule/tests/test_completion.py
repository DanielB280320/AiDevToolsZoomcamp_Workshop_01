"""Marking a chore complete (task 14).

plan.md §4 makes attribution the whole point — the log is what settles "I did do
it last week". So completion records who actually did it, separately from whose
turn it was, and two people tapping at once must not produce a duplicate or
steal each other's credit.
"""

import datetime as dt

import pytest
from django.urls import reverse

from chores.models import Chore
from schedule.models import Turn, TurnStatus
from schedule.services.transitions import TransitionRefused, complete_turn

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 1, 5)
EVENING = dt.datetime(2026, 1, 5, 19, 30, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _clock(frozen_clock):
    """Completion stamps `timezone.now()`; pin it."""


@pytest.fixture
def bins(household):
    return Chore.objects.create(
        household=household, name="Bins", anchor_date=TODAY, grace_days=2
    )


@pytest.fixture
def turn(bins, members):
    return Turn.objects.create(
        chore=bins,
        assignee=members[0],
        cycle_index=0,
        period_start=TODAY,
        due_date=TODAY,
    )


@pytest.fixture
def as_ana(client, members):
    client.force_login(members[0])
    return client


@pytest.fixture
def as_dev(members):
    """A second, genuinely separate session.

    Not the `client` fixture: pytest hands out one Client per test, so building
    both roommates on it would silently make them the same person -- and a test
    about two people racing would quietly be testing one person tapping twice.
    """
    from django.test import Client

    session = Client()
    session.force_login(members[3])
    return session


# Criterion 1 — completing stamps status, time and person.


def test_completing_records_status_time_and_who(turn, members):
    done, changed = complete_turn(turn, members[0], when=EVENING)

    assert changed is True
    assert done.status == TurnStatus.COMPLETED
    assert done.completed_by == members[0]
    assert done.completed_at == EVENING


def test_the_completion_is_persisted_not_just_returned(turn, members):
    complete_turn(turn, members[0], when=EVENING)
    turn.refresh_from_db()

    assert turn.status == TurnStatus.COMPLETED
    assert turn.completed_by == members[0]


def test_completing_on_time_is_not_marked_late(turn, members):
    done, _ = complete_turn(turn, members[0], when=EVENING)
    assert done.was_late is False


def test_the_assignee_is_never_overwritten_by_the_completer(turn, members):
    complete_turn(turn, members[3], when=EVENING)
    turn.refresh_from_db()
    assert turn.assignee == members[0]


# Criterion 2 — anyone may do it, and covering is recorded as covering.


def test_a_roommate_may_complete_someone_elses_turn(turn, members):
    done, changed = complete_turn(turn, members[3], when=EVENING)

    assert changed is True
    assert done.assignee == members[0]
    assert done.completed_by == members[3]
    assert done.was_covered is True


def test_doing_your_own_turn_is_not_recorded_as_covering(turn, members):
    done, _ = complete_turn(turn, members[0], when=EVENING)
    assert done.was_covered is False


# Criterion 3 — two taps at the same moment.


def test_a_second_completion_is_a_no_op_and_keeps_the_first_persons_credit(
    turn, members
):
    """The second tap must not quietly rewrite who gets the credit."""
    _first, first_changed = complete_turn(turn, members[0], when=EVENING)
    second, second_changed = complete_turn(
        turn, members[3], when=EVENING + dt.timedelta(seconds=2)
    )

    assert first_changed is True
    assert second_changed is False
    assert second.completed_by == members[0]
    assert second.completed_at == EVENING


def test_a_second_completion_creates_no_extra_row(turn, members):
    complete_turn(turn, members[0], when=EVENING)
    complete_turn(turn, members[1], when=EVENING)

    assert Turn.objects.count() == 1


def test_completing_a_stale_in_memory_copy_still_sees_the_truth(turn, members):
    """Two requests each hold their own copy; the lock re-reads."""
    stale = Turn.objects.get(pk=turn.pk)
    complete_turn(turn, members[0], when=EVENING)

    _, changed = complete_turn(stale, members[3], when=EVENING)

    assert changed is False
    turn.refresh_from_db()
    assert turn.completed_by == members[0]


def test_the_second_tap_through_the_screen_says_who_actually_did_it(
    as_ana, as_dev, turn, members
):
    as_ana.post(reverse("turn_complete", args=[turn.pk]))
    response = as_dev.post(reverse("turn_complete", args=[turn.pk]), follow=True)

    body = response.content.decode()
    assert "already marked done by Ana" in body
    turn.refresh_from_db()
    assert turn.completed_by == members[0]


# Criterion 4 — a missed chore done late.


def test_a_missed_turn_can_still_be_completed(turn, members):
    turn.status = TurnStatus.MISSED
    turn.save(update_fields=["status"])

    done, changed = complete_turn(
        turn, members[0], when=dt.datetime(2026, 1, 10, 9, 0, tzinfo=dt.UTC)
    )

    assert changed is True
    assert done.status == TurnStatus.COMPLETED


def test_completing_after_the_deadline_records_it_as_late(turn, members, bins):
    assert turn.deadline() == dt.date(2026, 1, 7)  # due 5th + 2 days grace

    done, _ = complete_turn(
        turn, members[0], when=dt.datetime(2026, 1, 8, 9, 0, tzinfo=dt.UTC)
    )

    assert done.was_late is True


def test_completing_on_the_last_day_of_grace_is_not_late(turn, members):
    done, _ = complete_turn(
        turn, members[0], when=dt.datetime(2026, 1, 7, 23, 0, tzinfo=dt.UTC)
    )
    assert done.was_late is False


def test_being_late_does_not_erase_that_it_was_done(turn, members):
    """plan.md §4: the record should show it was eventually done, and late."""
    done, _ = complete_turn(
        turn, members[0], when=dt.datetime(2026, 2, 1, 9, 0, tzinfo=dt.UTC)
    )
    assert done.status == TurnStatus.COMPLETED
    assert done.was_late is True


# Criterion 5 — a turn settled another way is not quietly overwritten.


@pytest.mark.parametrize("status", [TurnStatus.SKIPPED_AWAY, TurnStatus.SWAPPED])
def test_a_turn_settled_by_someone_elses_decision_refuses_completion(
    turn, members, status
):
    turn.status = status
    turn.save(update_fields=["status"])

    with pytest.raises(TransitionRefused):
        complete_turn(turn, members[0], when=EVENING)

    turn.refresh_from_db()
    assert turn.status == status
    assert turn.completed_by is None


def test_the_screen_reports_a_refusal_rather_than_failing(as_ana, turn):
    turn.status = TurnStatus.SKIPPED_AWAY
    turn.save(update_fields=["status"])

    response = as_ana.post(reverse("turn_complete", args=[turn.pk]), follow=True)

    assert response.status_code == 200
    assert "already skipped" in response.content.decode()


# Criterion 6 — the screen action.


def test_a_roommate_marks_a_turn_done_from_the_chore_page(as_dev, turn, members):
    response = as_dev.post(
        reverse("turn_complete", args=[turn.pk]),
        {"next": reverse("chore_detail", args=[turn.chore.pk])},
        follow=True,
    )

    assert response.status_code == 200
    turn.refresh_from_db()
    assert turn.status == TurnStatus.COMPLETED
    assert turn.completed_by == members[3]
    assert "marked done" in response.content.decode()


def test_the_done_button_is_on_the_chore_page(as_ana, turn):
    body = as_ana.get(reverse("chore_detail", args=[turn.chore.pk])).content.decode()
    assert reverse("turn_complete", args=[turn.pk]) in body
    assert "Done" in body


def test_a_settled_turn_moves_out_of_the_outstanding_list(as_ana, turn, members):
    complete_turn(turn, members[0], when=EVENING)

    response = as_ana.get(reverse("chore_detail", args=[turn.chore.pk]))

    assert list(response.context["outstanding"]) == []
    assert list(response.context["settled"]) == [turn]


def test_the_chore_page_shows_who_covered(as_ana, turn, members):
    complete_turn(turn, members[3], when=EVENING)

    body = as_ana.get(reverse("chore_detail", args=[turn.chore.pk])).content.decode()

    assert "done by Dev" in body


def test_completing_is_post_only(as_ana, turn):
    assert as_ana.get(reverse("turn_complete", args=[turn.pk])).status_code == 405


def test_another_households_turn_cannot_be_completed(as_ana, members):
    from accounts.models import Household, Member

    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )
    their_chore = Chore.objects.create(
        household=other, name="Their bins", anchor_date=TODAY
    )
    their_turn = Turn.objects.create(
        chore=their_chore,
        assignee=outsider,
        cycle_index=0,
        period_start=TODAY,
        due_date=TODAY,
    )

    assert (
        as_ana.post(reverse("turn_complete", args=[their_turn.pk])).status_code == 404
    )
    their_turn.refresh_from_db()
    assert their_turn.status == TurnStatus.PENDING


def test_an_anonymous_visitor_cannot_complete_anything(client, turn):
    response = client.post(reverse("turn_complete", args=[turn.pk]))
    assert response.status_code == 302
    turn.refresh_from_db()
    assert turn.status == TurnStatus.PENDING
