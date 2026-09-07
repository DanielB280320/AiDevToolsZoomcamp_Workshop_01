"""Flagging missed chores (task 15).

plan.md §4 names surfacing who missed which chores as a core requirement, and
§6 keeps reminders inside the app — so the state has to be right at the moment
someone looks, not only after a cron ran. architecture.md §4 therefore calls
this both ways, which is why running it twice must change nothing.
"""

import datetime as dt

import pytest
from django.core.management import call_command
from django.urls import reverse

from accounts.models import Household, Member
from chores.models import Chore
from schedule.models import Turn, TurnStatus
from schedule.services.transitions import mark_overdue, refresh_household

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 1, 5)


@pytest.fixture(autouse=True)
def _clock(frozen_clock):
    """`mark_overdue` defaults to today; pin it."""


@pytest.fixture
def make_chore(household):
    def _make_chore(name="Bins", *, grace=2, **extra):
        return Chore.objects.create(
            household=household,
            name=name,
            anchor_date=TODAY,
            grace_days=grace,
            **extra,
        )

    return _make_chore


@pytest.fixture
def make_turn(make_chore, members):
    default = make_chore()

    def _make_turn(due, *, chore=None, status=TurnStatus.PENDING, cycle=None):
        chore = chore or default
        cycle = chore.turns.count() if cycle is None else cycle
        return Turn.objects.create(
            chore=chore,
            assignee=members[0],
            cycle_index=cycle,
            period_start=due,
            due_date=due,
            status=status,
        )

    return _make_turn


# Criterion 1 — past the deadline is missed.


def test_a_turn_past_its_due_date_and_grace_is_marked_missed(make_turn):
    turn = make_turn(dt.date(2026, 1, 1))  # due 1st, 2 days grace, deadline 3rd

    assert mark_overdue(today=TODAY) == 1

    turn.refresh_from_db()
    assert turn.status == TurnStatus.MISSED


def test_the_day_after_the_deadline_is_the_first_missed_day(make_turn):
    turn = make_turn(dt.date(2026, 1, 3))  # deadline 5th, today is the 5th
    assert mark_overdue(today=TODAY) == 0

    assert mark_overdue(today=dt.date(2026, 1, 6)) == 1
    turn.refresh_from_db()
    assert turn.status == TurnStatus.MISSED


def test_each_chore_uses_its_own_grace_period(make_chore, make_turn):
    strict = make_chore("Strict", grace=0)
    lenient = make_chore("Lenient", grace=7)
    tight = make_turn(dt.date(2026, 1, 4), chore=strict)
    loose = make_turn(dt.date(2026, 1, 4), chore=lenient)

    mark_overdue(today=TODAY)

    tight.refresh_from_db()
    loose.refresh_from_db()
    assert tight.status == TurnStatus.MISSED
    assert loose.status == TurnStatus.PENDING


def test_several_overdue_turns_are_all_caught(make_turn):
    for day in (1, 2, 3):
        make_turn(dt.date(2025, 12, day))

    assert mark_overdue(today=TODAY) == 3
    assert Turn.objects.filter(status=TurnStatus.MISSED).count() == 3


# Criterion 2 — inside the grace period, nothing happens.


def test_a_turn_due_today_is_left_alone(make_turn):
    turn = make_turn(TODAY)
    assert mark_overdue(today=TODAY) == 0
    turn.refresh_from_db()
    assert turn.status == TurnStatus.PENDING


def test_a_turn_still_inside_its_grace_is_left_alone(make_turn):
    turn = make_turn(dt.date(2026, 1, 4))  # deadline the 6th
    assert mark_overdue(today=TODAY) == 0
    turn.refresh_from_db()
    assert turn.status == TurnStatus.PENDING


def test_a_turn_due_in_the_future_is_left_alone(make_turn):
    turn = make_turn(dt.date(2026, 3, 1))
    mark_overdue(today=TODAY)
    turn.refresh_from_db()
    assert turn.status == TurnStatus.PENDING


def test_grace_is_inclusive_of_its_last_day(make_turn):
    turn = make_turn(dt.date(2026, 1, 3))  # 2 days grace, deadline the 5th
    assert turn.deadline() == TODAY

    mark_overdue(today=TODAY)

    turn.refresh_from_db()
    assert turn.status == TurnStatus.PENDING


# Criterion 3 — a settled turn is never reopened.


@pytest.mark.parametrize(
    "status",
    [TurnStatus.COMPLETED, TurnStatus.SKIPPED_AWAY, TurnStatus.SWAPPED],
)
def test_a_settled_turn_is_never_marked_missed(make_turn, status):
    turn = make_turn(dt.date(2025, 12, 1), status=status)

    assert mark_overdue(today=TODAY) == 0

    turn.refresh_from_db()
    assert turn.status == status


def test_an_absence_is_never_converted_into_a_failure(make_turn):
    """plan.md §8: the whole point of SKIPPED_AWAY being its own status."""
    turn = make_turn(dt.date(2025, 11, 1), status=TurnStatus.SKIPPED_AWAY)

    mark_overdue(today=TODAY)

    turn.refresh_from_db()
    assert turn.status == TurnStatus.SKIPPED_AWAY
    assert turn.status != TurnStatus.MISSED


def test_an_already_missed_turn_is_not_counted_again(make_turn):
    make_turn(dt.date(2025, 12, 1), status=TurnStatus.MISSED)
    assert mark_overdue(today=TODAY) == 0


def test_a_turn_completed_late_stays_completed(make_turn, members):
    turn = make_turn(dt.date(2025, 12, 1), status=TurnStatus.COMPLETED)
    turn.was_late = True
    turn.save(update_fields=["was_late"])

    mark_overdue(today=TODAY)

    turn.refresh_from_db()
    assert turn.status == TurnStatus.COMPLETED
    assert turn.was_late is True


# Criterion 4 — the second run is a no-op.


def test_running_it_twice_changes_nothing_the_second_time(make_turn):
    make_turn(dt.date(2025, 12, 1))
    make_turn(dt.date(2025, 12, 8))

    assert mark_overdue(today=TODAY) == 2
    assert mark_overdue(today=TODAY) == 0


def test_the_second_run_does_not_touch_the_rows(make_turn):
    make_turn(dt.date(2025, 12, 1))
    mark_overdue(today=TODAY)
    snapshot = {(t.pk, t.status, t.completed_by_id) for t in Turn.objects.all()}

    mark_overdue(today=TODAY)

    assert {(t.pk, t.status, t.completed_by_id) for t in Turn.objects.all()} == snapshot


def test_marking_missed_never_invents_an_attribution(make_turn):
    turn = make_turn(dt.date(2025, 12, 1))
    mark_overdue(today=TODAY)
    turn.refresh_from_db()

    assert turn.completed_by is None
    assert turn.completed_at is None


# Criterion 5 — the command, and the lazy run when someone opens the app.


def test_the_management_command_marks_and_reports(make_turn, capsys):
    make_turn(dt.date(2025, 12, 1))

    call_command("mark_overdue")

    assert Turn.objects.filter(status=TurnStatus.MISSED).count() == 1
    assert "1 turn(s) marked missed." in capsys.readouterr().out


def test_running_the_command_twice_is_harmless(make_turn, capsys):
    make_turn(dt.date(2025, 12, 1))
    call_command("mark_overdue")
    capsys.readouterr()

    call_command("mark_overdue")

    assert "0 turn(s) marked missed." in capsys.readouterr().out


def test_opening_the_app_marks_overdue_turns(client, members, make_turn):
    turn = make_turn(dt.date(2025, 12, 1))
    client.force_login(members[0])

    client.get(reverse("dashboard"))

    turn.refresh_from_db()
    assert turn.status == TurnStatus.MISSED


def test_opening_the_app_also_generates_missing_turns(client, members, make_chore):
    """Generation runs first: a turn never materialised cannot be marked missed."""
    chore = make_chore("Bins")
    chore.set_rotation(members[:3])
    assert chore.turns.count() == 0

    client.force_login(members[0])
    client.get(reverse("dashboard"))

    assert chore.turns.count() > 0


def test_refresh_reports_what_it_did(household, make_chore, make_turn, members):
    chore = make_chore("Bathroom")
    chore.set_rotation(members[:2])
    make_turn(dt.date(2025, 12, 1), chore=chore, cycle=99)

    generated, missed = refresh_household(household, today=TODAY)

    assert generated > 0
    assert missed == 1


def test_a_second_page_load_changes_nothing(client, members, make_turn):
    make_turn(dt.date(2025, 12, 1))
    client.force_login(members[0])

    client.get(reverse("dashboard"))
    snapshot = {(t.pk, t.status) for t in Turn.objects.all()}
    client.get(reverse("dashboard"))

    assert {(t.pk, t.status) for t in Turn.objects.all()} == snapshot


# Criterion 6 — scoping.


def test_marking_can_be_scoped_to_one_household(make_turn, household):
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )
    their_chore = Chore.objects.create(
        household=other, name="Their bins", anchor_date=TODAY, grace_days=0
    )
    theirs = Turn.objects.create(
        chore=their_chore,
        assignee=outsider,
        cycle_index=0,
        period_start=dt.date(2025, 12, 1),
        due_date=dt.date(2025, 12, 1),
    )
    mine = make_turn(dt.date(2025, 12, 1))

    moved = mark_overdue(Turn.objects.for_household(household), today=TODAY)

    assert moved == 1
    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.status == TurnStatus.MISSED
    assert theirs.status == TurnStatus.PENDING


def test_opening_the_app_does_not_touch_another_household(
    client, members, make_turn, household
):
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )
    their_chore = Chore.objects.create(
        household=other, name="Their bins", anchor_date=TODAY, grace_days=0
    )
    theirs = Turn.objects.create(
        chore=their_chore,
        assignee=outsider,
        cycle_index=0,
        period_start=dt.date(2025, 12, 1),
        due_date=dt.date(2025, 12, 1),
    )

    client.force_login(members[0])
    client.get(reverse("dashboard"))

    theirs.refresh_from_db()
    assert theirs.status == TurnStatus.PENDING
