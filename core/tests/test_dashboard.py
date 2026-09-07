"""The home screen (task 16).

plan.md §6 chose in-app reminders as the only notification channel, which puts
the entire reminder burden on this screen: if it is not obvious here, nobody
finds out at all. Overdue is shown to every roommate, not only the assignee —
that answers the spec's open question on visibility.
"""

import datetime as dt

import pytest
from django.urls import reverse

from accounts.models import Household, Member
from chores.models import Cadence, Chore
from schedule.models import Turn, TurnStatus

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 1, 5)


@pytest.fixture(autouse=True)
def _clock(frozen_clock):
    """The screen asks for today; pin it."""


@pytest.fixture
def bins(household):
    return Chore.objects.create(
        household=household,
        name="Bins",
        cadence_unit=Cadence.WEEK,
        anchor_date=TODAY,
        grace_days=1,
    )


@pytest.fixture
def make_turn(bins, members):
    def _make_turn(due, *, assignee=None, status=TurnStatus.PENDING, chore=None):
        chore = chore or bins
        return Turn.objects.create(
            chore=chore,
            assignee=assignee or members[0],
            cycle_index=chore.turns.count(),
            period_start=due,
            due_date=due,
            status=status,
        )

    return _make_turn


@pytest.fixture
def as_ana(client, members):
    client.force_login(members[0])
    return client


@pytest.fixture
def as_ben(client, members):
    client.force_login(members[1])
    return client


def home(session):
    return session.get(reverse("dashboard"))


# Criterion 1 — your own turns.


def test_your_own_turn_due_today_is_shown(as_ana, make_turn, members):
    turn = make_turn(TODAY, assignee=members[0])

    response = home(as_ana)

    assert list(response.context["mine_today"]) == [turn]
    assert "Bins" in response.content.decode()


def test_your_upcoming_turns_are_shown_separately_from_todays(
    as_ana, make_turn, members
):
    today = make_turn(TODAY, assignee=members[0])
    later = make_turn(TODAY + dt.timedelta(days=14), assignee=members[0])

    response = home(as_ana)

    assert list(response.context["mine_today"]) == [today]
    assert list(response.context["mine_upcoming"]) == [later]


def test_someone_elses_turn_is_not_in_your_list(as_ana, make_turn, members):
    make_turn(TODAY, assignee=members[1])

    response = home(as_ana)

    assert list(response.context["mine_today"]) == []
    assert list(response.context["mine_upcoming"]) == []


def test_a_turn_you_already_did_is_not_still_owed(as_ana, make_turn, members):
    make_turn(TODAY, assignee=members[0], status=TurnStatus.COMPLETED)

    response = home(as_ana)

    assert list(response.context["mine_today"]) == []


def test_your_own_turns_are_ordered_soonest_first(as_ana, make_turn, members):
    late = make_turn(TODAY + dt.timedelta(days=21), assignee=members[0])
    soon = make_turn(TODAY + dt.timedelta(days=3), assignee=members[0])

    response = home(as_ana)

    assert list(response.context["mine_upcoming"]) == [soon, late]


# Criterion 2 — overdue, shown to everyone.


def test_an_overdue_turn_is_shown_to_the_person_who_owes_it(as_ana, make_turn, members):
    turn = make_turn(dt.date(2025, 12, 1), assignee=members[0])

    response = home(as_ana)

    assert list(response.context["overdue"]) == [turn]
    assert response.context["my_overdue_count"] == 1


def test_an_overdue_turn_is_shown_to_everyone_else_too(as_ben, make_turn, members):
    """The spec's open question on visibility, answered.

    A private nudge nobody else can see is just a nag; the shared sight of it is
    what gives a reminder weight in a peer household.
    """
    turn = make_turn(dt.date(2025, 12, 1), assignee=members[0])

    response = home(as_ben)

    assert list(response.context["overdue"]) == [turn]
    assert "Ana" in response.content.decode()
    # It is not *Ben's* problem, and the screen says so.
    assert response.context["my_overdue_count"] == 0


def test_overdue_names_who_owes_it_and_when_it_was_due(as_ben, make_turn, members):
    make_turn(dt.date(2025, 12, 1), assignee=members[2])

    body = home(as_ben).content.decode()

    assert "Cleo" in body
    assert "2025-12-01" in body or "Dec. 1, 2025" in body


def test_overdue_is_ordered_oldest_first(as_ana, make_turn, members):
    newer = make_turn(dt.date(2025, 12, 20), assignee=members[1])
    older = make_turn(dt.date(2025, 12, 1), assignee=members[2])

    response = home(as_ana)

    assert list(response.context["overdue"]) == [older, newer]


def test_anyone_can_clear_an_overdue_turn_from_the_home_screen(
    as_ben, make_turn, members
):
    turn = make_turn(dt.date(2025, 12, 1), assignee=members[0])

    body = home(as_ben).content.decode()
    assert reverse("turn_complete", args=[turn.pk]) in body

    as_ben.post(
        reverse("turn_complete", args=[turn.pk]),
        {"next": reverse("dashboard")},
        follow=True,
    )

    turn.refresh_from_db()
    assert turn.status == TurnStatus.COMPLETED
    assert turn.completed_by == members[1]


# Criterion 3 — what is due soon elsewhere.


def test_someone_elses_turn_due_soon_is_shown(as_ana, make_turn, members):
    turn = make_turn(TODAY + dt.timedelta(days=3), assignee=members[1])

    response = home(as_ana)

    assert list(response.context["due_soon"]) == [turn]


def test_a_turn_beyond_the_soon_window_is_not_shown(as_ana, make_turn, members):
    make_turn(TODAY + dt.timedelta(days=30), assignee=members[1])

    response = home(as_ana)

    assert list(response.context["due_soon"]) == []


def test_due_soon_does_not_repeat_your_own_turns(as_ana, make_turn, members):
    make_turn(TODAY + dt.timedelta(days=2), assignee=members[0])

    response = home(as_ana)

    assert list(response.context["due_soon"]) == []
    assert len(response.context["mine_upcoming"]) == 1


def test_a_settled_turn_is_not_due_soon(as_ana, make_turn, members):
    make_turn(
        TODAY + dt.timedelta(days=2),
        assignee=members[1],
        status=TurnStatus.SKIPPED_AWAY,
    )

    response = home(as_ana)

    assert list(response.context["due_soon"]) == []


# Criterion 4 — the state is refreshed as the page renders.


def test_opening_the_screen_marks_a_newly_overdue_turn(as_ana, make_turn, members):
    turn = make_turn(dt.date(2026, 1, 1), assignee=members[0])
    assert turn.status == TurnStatus.PENDING

    response = home(as_ana)

    turn.refresh_from_db()
    assert turn.status == TurnStatus.MISSED
    assert list(response.context["overdue"]) == [turn]


def test_opening_the_screen_generates_turns_that_did_not_exist(as_ana, bins, members):
    bins.set_rotation(members[:3])
    assert bins.turns.count() == 0

    response = home(as_ana)

    assert bins.turns.count() > 0
    assert response.context["mine_today"] or response.context["mine_upcoming"]


def test_a_second_load_changes_nothing(as_ana, bins, members, make_turn):
    make_turn(dt.date(2026, 1, 1), assignee=members[0])
    bins.set_rotation(members[:3])

    home(as_ana)
    snapshot = {(t.pk, t.status, t.assignee_id) for t in Turn.objects.all()}
    home(as_ana)

    assert {(t.pk, t.status, t.assignee_id) for t in Turn.objects.all()} == snapshot


# Criterion 5 — overdue reads as different in kind, not just further up.


def test_overdue_is_marked_out_visually_and_not_merely_listed(
    as_ana, make_turn, members
):
    make_turn(dt.date(2025, 12, 1), assignee=members[0])

    body = home(as_ana).content.decode()

    assert "panel--danger" in body
    assert "row--danger" in body
    assert "Overdue" in body


def test_the_greeting_tells_you_where_you_stand(as_ana, make_turn, members):
    make_turn(dt.date(2025, 12, 1), assignee=members[0])

    body = home(as_ana).content.decode()

    assert "You are behind on 1 chore" in body


def test_the_greeting_is_calm_when_nothing_is_owed(as_ana):
    assert "Nothing owed right now." in home(as_ana).content.decode()


def test_a_household_with_no_turns_says_how_to_start(as_ana):
    body = home(as_ana).content.decode()

    assert "No turns yet." in body
    assert reverse("chore_list") in body


def test_nothing_of_yours_today_still_reads_sensibly(as_ana, make_turn, members):
    make_turn(TODAY + dt.timedelta(days=3), assignee=members[1])

    body = home(as_ana).content.decode()

    assert "Nothing of yours is due today." in body


# Criterion 6 — scoping.


def test_another_households_turns_never_appear(as_ana, make_turn, members):
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )
    their_chore = Chore.objects.create(
        household=other, name="Their bins", anchor_date=TODAY, grace_days=0
    )
    Turn.objects.create(
        chore=their_chore,
        assignee=outsider,
        cycle_index=0,
        period_start=dt.date(2025, 12, 1),
        due_date=dt.date(2025, 12, 1),
    )
    mine = make_turn(dt.date(2025, 12, 1), assignee=members[0])

    response = home(as_ana)
    body = response.content.decode()

    assert list(response.context["overdue"]) == [mine]
    assert "Outsider" not in body
    assert "Their bins" not in body


def test_the_home_screen_requires_signing_in(client):
    response = client.get(reverse("dashboard"))
    assert response.status_code == 302
    assert reverse("login") in response.url
