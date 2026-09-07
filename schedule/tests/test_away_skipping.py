"""Skipping a turn for an absence (task 18).

plan.md §8 is explicit that a planned absence must be distinguishable from a
genuine miss. SKIPPED_AWAY is therefore its own terminal status, not a variety
of MISSED — otherwise §4's record would blame someone for a chore they were
never due to do.

Passing the turn to the next roommate rather than leaving it undone answers the
spec's open question: the household should not go without a clean bathroom
because one person is on holiday.
"""

import datetime as dt

import pytest
from django.urls import reverse

from chores.models import Cadence, Chore
from schedule.models import AwayPeriod, Turn, TurnStatus
from schedule.services.transitions import (
    mark_overdue,
    refresh_household,
    skip_away_turns,
)

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 1, 5)


@pytest.fixture(autouse=True)
def _clock(frozen_clock):
    """Skipping compares due dates against absences; pin the clock."""


@pytest.fixture
def bins(household, members):
    chore = Chore.objects.create(
        household=household,
        name="Bins",
        cadence_unit=Cadence.WEEK,
        anchor_date=TODAY,
        grace_days=1,
    )
    chore.set_rotation(members[:3])  # Ana, Ben, Cleo
    return chore


@pytest.fixture
def make_turn(bins, members):
    def _make_turn(due, *, assignee=None, cycle=None, chore=None):
        chore = chore or bins
        return Turn.objects.create(
            chore=chore,
            assignee=assignee or members[0],
            cycle_index=chore.turns.count() if cycle is None else cycle,
            period_start=due,
            due_date=due,
        )

    return _make_turn


@pytest.fixture
def away(members):
    def _away(member, start, end):
        return AwayPeriod.objects.create(
            member=member, start_date=start, end_date=end, created_by=member
        )

    return _away


def live_turn(chore, cycle):
    return chore.turns.exclude(status=TurnStatus.SKIPPED_AWAY).get(cycle_index=cycle)


# Criterion 1 — the turn is skipped, and skipped is not missed.


def test_a_turn_inside_the_assignees_absence_is_skipped(make_turn, away, members):
    turn = make_turn(dt.date(2026, 1, 12), assignee=members[0])
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    skipped, _ = skip_away_turns(today=TODAY)

    turn.refresh_from_db()
    assert skipped == 1
    assert turn.status == TurnStatus.SKIPPED_AWAY
    assert turn.status != TurnStatus.MISSED


def test_a_turn_outside_the_absence_is_untouched(make_turn, away, members):
    turn = make_turn(dt.date(2026, 1, 5), assignee=members[0])
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    assert skip_away_turns(today=TODAY) == (0, 0)

    turn.refresh_from_db()
    assert turn.status == TurnStatus.PENDING


@pytest.mark.parametrize(
    ("due", "skipped"),
    [
        (dt.date(2026, 1, 9), False),  # day before
        (dt.date(2026, 1, 10), True),  # first day away, inclusive
        (dt.date(2026, 1, 15), True),
        (dt.date(2026, 1, 20), True),  # last day away, inclusive
        (dt.date(2026, 1, 21), False),  # day after
    ],
)
def test_the_absence_boundaries_are_inclusive(make_turn, away, members, due, skipped):
    turn = make_turn(due, assignee=members[0])
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    skip_away_turns(today=TODAY)

    turn.refresh_from_db()
    expected = TurnStatus.SKIPPED_AWAY if skipped else TurnStatus.PENDING
    assert turn.status == expected


def test_someone_elses_absence_does_not_skip_your_turn(make_turn, away, members):
    turn = make_turn(dt.date(2026, 1, 12), assignee=members[0])
    away(members[1], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    skip_away_turns(today=TODAY)

    turn.refresh_from_db()
    assert turn.status == TurnStatus.PENDING


# Criterion 2 — it passes to the next roommate, and the trail is visible.


def test_the_turn_passes_to_the_next_roommate_in_the_rotation(
    bins, make_turn, away, members
):
    turn = make_turn(dt.date(2026, 1, 12), assignee=members[0], cycle=1)
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    skipped, reassigned = skip_away_turns(today=TODAY)

    assert (skipped, reassigned) == (1, 1)
    replacement = live_turn(bins, 1)
    assert replacement.assignee == members[1]  # Ana -> Ben
    assert replacement.status == TurnStatus.PENDING
    assert replacement.due_date == turn.due_date
    assert replacement.cycle_index == turn.cycle_index


def test_the_replacement_links_back_to_the_turn_it_took_over(
    bins, make_turn, away, members
):
    turn = make_turn(dt.date(2026, 1, 12), assignee=members[0], cycle=1)
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    skip_away_turns(today=TODAY)

    replacement = live_turn(bins, 1)
    turn.refresh_from_db()
    assert replacement.replaces == turn
    assert turn.replaced_by == replacement


def test_both_halves_of_the_story_survive(bins, make_turn, away, members):
    """The skip and the hand-on are both facts; neither may overwrite the other."""
    make_turn(dt.date(2026, 1, 12), assignee=members[0], cycle=1)
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    skip_away_turns(today=TODAY)

    for_cycle = bins.turns.filter(cycle_index=1)
    assert for_cycle.count() == 2
    assert {t.status for t in for_cycle} == {
        TurnStatus.SKIPPED_AWAY,
        TurnStatus.PENDING,
    }
    assert {t.assignee for t in for_cycle} == {members[0], members[1]}


def test_the_rotation_wraps_when_the_last_person_is_away(
    bins, make_turn, away, members
):
    make_turn(dt.date(2026, 1, 12), assignee=members[2], cycle=1)  # Cleo is last
    away(members[2], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    skip_away_turns(today=TODAY)

    assert live_turn(bins, 1).assignee == members[0]  # wraps back to Ana


def test_a_turn_whose_assignee_left_the_rotation_starts_from_the_top(
    bins, make_turn, away, members
):
    make_turn(dt.date(2026, 1, 12), assignee=members[4], cycle=1)  # not in rota
    away(members[4], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    skip_away_turns(today=TODAY)

    assert live_turn(bins, 1).assignee == members[0]


# Criterion 3 — an absent roommate is never marked missed.


def test_an_absent_roommate_is_never_marked_missed(make_turn, away, members):
    """The assertion this whole task exists for."""
    turn = make_turn(dt.date(2026, 1, 12), assignee=members[0], cycle=1)
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    # A month later: long past the due date and grace.
    later = dt.date(2026, 2, 15)
    skip_away_turns(today=later)
    mark_overdue(today=later)

    turn.refresh_from_db()
    assert turn.status == TurnStatus.SKIPPED_AWAY
    assert turn.status != TurnStatus.MISSED


def test_the_refresh_skips_before_it_marks_missed(household, make_turn, away, members):
    """Order matters: marking first would stamp MISSED on an absent roommate."""
    turn = make_turn(dt.date(2026, 1, 6), assignee=members[0], cycle=1)
    away(members[0], dt.date(2026, 1, 1), dt.date(2026, 1, 31))

    refresh_household(household, today=dt.date(2026, 1, 20))

    turn.refresh_from_db()
    assert turn.status == TurnStatus.SKIPPED_AWAY


def test_the_replacement_can_still_be_marked_missed(bins, make_turn, away, members):
    """The stand-in is accountable, even though the absent person is not."""
    make_turn(dt.date(2026, 1, 6), assignee=members[0], cycle=1)
    away(members[0], dt.date(2026, 1, 1), dt.date(2026, 1, 31))

    skip_away_turns(today=dt.date(2026, 1, 20))
    mark_overdue(today=dt.date(2026, 1, 20))

    assert live_turn(bins, 1).status == TurnStatus.MISSED


# Criterion 4 — everyone away.


def test_it_keeps_walking_when_the_next_person_is_also_away(
    bins, make_turn, away, members
):
    make_turn(dt.date(2026, 1, 12), assignee=members[0], cycle=1)
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))
    away(members[1], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    skipped, reassigned = skip_away_turns(today=TODAY)

    assert (skipped, reassigned) == (1, 1)
    assert live_turn(bins, 1).assignee == members[2]  # skips Ben, lands on Cleo


def test_when_the_whole_flat_is_away_nobody_takes_it(bins, make_turn, away, members):
    turn = make_turn(dt.date(2026, 1, 12), assignee=members[0], cycle=1)
    for member in members[:3]:
        away(member, dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    skipped, reassigned = skip_away_turns(today=TODAY)

    assert (skipped, reassigned) == (1, 0)
    turn.refresh_from_db()
    assert turn.status == TurnStatus.SKIPPED_AWAY
    assert bins.turns.filter(cycle_index=1).count() == 1


def test_a_chore_with_no_rotation_left_simply_skips(household, away, members):
    chore = Chore.objects.create(household=household, name="Orphan", anchor_date=TODAY)
    turn = Turn.objects.create(
        chore=chore,
        assignee=members[0],
        cycle_index=0,
        period_start=dt.date(2026, 1, 12),
        due_date=dt.date(2026, 1, 12),
    )
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    assert skip_away_turns(today=TODAY) == (1, 0)
    turn.refresh_from_db()
    assert turn.status == TurnStatus.SKIPPED_AWAY


# Criterion 5 — running it twice.


def test_a_second_run_changes_nothing(bins, make_turn, away, members):
    make_turn(dt.date(2026, 1, 12), assignee=members[0], cycle=1)
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    assert skip_away_turns(today=TODAY) == (1, 1)
    assert skip_away_turns(today=TODAY) == (0, 0)
    assert bins.turns.filter(cycle_index=1).count() == 2


def test_a_skipped_turn_is_terminal_and_never_revisited(make_turn, away, members):
    turn = make_turn(dt.date(2026, 1, 12), assignee=members[0], cycle=1)
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))
    skip_away_turns(today=TODAY)
    turn.refresh_from_db()

    skip_away_turns(today=TODAY)

    assert turn.is_terminal is True
    assert Turn.objects.filter(status=TurnStatus.SKIPPED_AWAY).count() == 1


def test_the_replacement_is_not_itself_skipped_when_the_stand_in_is_here(
    bins, make_turn, away, members
):
    make_turn(dt.date(2026, 1, 12), assignee=members[0], cycle=1)
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    skip_away_turns(today=TODAY)
    skip_away_turns(today=TODAY)

    assert live_turn(bins, 1).status == TurnStatus.PENDING


def test_a_completed_turn_is_never_skipped(make_turn, away, members):
    turn = make_turn(dt.date(2026, 1, 12), assignee=members[0])
    turn.status = TurnStatus.COMPLETED
    turn.save(update_fields=["status"])
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    assert skip_away_turns(today=TODAY) == (0, 0)
    turn.refresh_from_db()
    assert turn.status == TurnStatus.COMPLETED


# Criterion 6 — it happens when someone opens the app, and stays scoped.


def test_opening_the_app_skips_an_absent_roommates_turn(
    client, bins, make_turn, away, members
):
    turn = make_turn(dt.date(2026, 1, 6), assignee=members[0], cycle=1)
    away(members[0], dt.date(2026, 1, 1), dt.date(2026, 1, 31))

    client.force_login(members[1])
    client.get(reverse("dashboard"))

    turn.refresh_from_db()
    assert turn.status == TurnStatus.SKIPPED_AWAY


def test_skipping_can_be_scoped_to_one_household(make_turn, away, members, household):
    from accounts.models import Household, Member

    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )
    their_chore = Chore.objects.create(
        household=other, name="Their bins", anchor_date=TODAY
    )
    theirs = Turn.objects.create(
        chore=their_chore,
        assignee=outsider,
        cycle_index=0,
        period_start=dt.date(2026, 1, 12),
        due_date=dt.date(2026, 1, 12),
    )
    AwayPeriod.objects.create(
        member=outsider,
        start_date=dt.date(2026, 1, 10),
        end_date=dt.date(2026, 1, 20),
    )
    mine = make_turn(dt.date(2026, 1, 12), assignee=members[0], cycle=1)
    away(members[0], dt.date(2026, 1, 10), dt.date(2026, 1, 20))

    skipped, _ = skip_away_turns(Turn.objects.for_household(household), today=TODAY)

    assert skipped == 1
    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.status == TurnStatus.SKIPPED_AWAY
    assert theirs.status == TurnStatus.PENDING
