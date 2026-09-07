"""The change log (task 20).

plan.md §4 justifies tracking by the need to settle disputes, and a turn's
current status alone cannot say who changed it, when, or from what — which is
exactly what a disagreement turns on. "It says missed but I did it on Sunday"
is unanswerable from the turn row and answerable from here.
"""

import datetime as dt

import pytest

from chores.models import Chore
from schedule.models import ActivityLog, AwayPeriod, LogVerb, Turn, TurnStatus
from schedule.services.transitions import (
    complete_turn,
    mark_overdue,
    skip_away_turns,
    swap_turns,
)

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 1, 5)
EVENING = dt.datetime(2026, 1, 5, 19, 30, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _clock(frozen_clock):
    """Entries stamp `timezone.now()`; pin it."""


@pytest.fixture
def bins(household, members):
    chore = Chore.objects.create(
        household=household, name="Bins", anchor_date=TODAY, grace_days=1
    )
    chore.set_rotation(members[:3])
    return chore


@pytest.fixture
def make_turn(bins, members):
    def _make_turn(due, assignee=None, *, status=TurnStatus.PENDING):
        return Turn.objects.create(
            chore=bins,
            assignee=assignee or members[0],
            cycle_index=bins.turns.count(),
            period_start=due,
            due_date=due,
            status=status,
        )

    return _make_turn


def entries(verb=None):
    qs = ActivityLog.objects.all()
    return list(qs.filter(verb=verb) if verb else qs)


# Criterion 1 — what an entry holds.


def test_an_entry_records_household_actor_verb_turn_time_and_detail(
    make_turn, members, household
):
    turn = make_turn(TODAY, members[0])

    complete_turn(turn, members[0], when=EVENING)

    entry = ActivityLog.objects.get()
    assert entry.household == household
    assert entry.actor == members[0]
    assert entry.verb == LogVerb.COMPLETED
    assert entry.turn == turn
    assert entry.chore == turn.chore
    assert entry.at is not None
    assert entry.detail["due_date"] == "2026-01-05"


def test_entries_read_newest_first(make_turn, members):
    first = make_turn(TODAY, members[0])
    second = make_turn(TODAY, members[1])
    complete_turn(first, members[0], when=EVENING)
    complete_turn(second, members[1], when=EVENING + dt.timedelta(minutes=5))

    assert [e.turn for e in ActivityLog.objects.all()] == [second, first]


# Criterion 2 — completion.


def test_completing_writes_an_entry_naming_who_acted(make_turn, members):
    turn = make_turn(TODAY, members[0])

    complete_turn(turn, members[3], when=EVENING)

    entry = ActivityLog.objects.get(verb=LogVerb.COMPLETED)
    assert entry.actor == members[3]
    assert entry.detail["assignee"] == "Ana"
    assert entry.detail["covered"] is True


def test_the_log_answers_who_actually_did_it_when_someone_covered(make_turn, members):
    """The dispute this exists for: 'that was my turn but Dev did it'."""
    turn = make_turn(TODAY, members[0])

    complete_turn(turn, members[3], when=EVENING)

    entry = ActivityLog.objects.get()
    assert entry.actor.display_name == "Dev"
    assert entry.detail["assignee"] == "Ana"


def test_a_late_completion_says_so_in_the_log(make_turn, members):
    turn = make_turn(dt.date(2026, 1, 1), members[0])

    complete_turn(turn, members[0], when=EVENING)

    assert ActivityLog.objects.get().detail["late"] is True


def test_a_second_tap_writes_no_second_entry(make_turn, members):
    """The no-op must not look like two people each doing the chore."""
    turn = make_turn(TODAY, members[0])

    complete_turn(turn, members[0], when=EVENING)
    complete_turn(turn, members[1], when=EVENING)

    assert ActivityLog.objects.count() == 1


def test_a_refused_completion_writes_nothing(make_turn, members):
    from schedule.services.transitions import TransitionRefused

    turn = make_turn(TODAY, members[0], status=TurnStatus.SKIPPED_AWAY)

    with pytest.raises(TransitionRefused):
        complete_turn(turn, members[0], when=EVENING)

    assert ActivityLog.objects.count() == 0


# Criterion 3 — missed and skipped, with nobody to blame for the act itself.


def test_marking_missed_writes_an_entry_with_no_actor(make_turn, members):
    """Nobody *did* this; a deadline passed. Inventing an author would lie."""
    turn = make_turn(dt.date(2025, 12, 1), members[1])

    mark_overdue(today=TODAY)

    entry = ActivityLog.objects.get(verb=LogVerb.MISSED)
    assert entry.actor is None
    assert entry.turn == turn
    assert entry.detail["assignee"] == "Ben"
    assert entry.detail["deadline"] == "2025-12-02"


def test_every_missed_turn_gets_its_own_entry(make_turn, members):
    make_turn(dt.date(2025, 12, 1), members[0])
    make_turn(dt.date(2025, 12, 2), members[1])

    mark_overdue(today=TODAY)

    assert len(entries(LogVerb.MISSED)) == 2
    assert {e.detail["assignee"] for e in entries(LogVerb.MISSED)} == {"Ana", "Ben"}


def test_a_second_overdue_run_writes_no_duplicate_entries(make_turn, members):
    make_turn(dt.date(2025, 12, 1), members[0])

    mark_overdue(today=TODAY)
    mark_overdue(today=TODAY)

    assert len(entries(LogVerb.MISSED)) == 1


def test_skipping_for_an_absence_is_logged_as_its_own_thing(make_turn, members):
    turn = make_turn(dt.date(2026, 1, 12), members[0])
    AwayPeriod.objects.create(
        member=members[0],
        start_date=dt.date(2026, 1, 10),
        end_date=dt.date(2026, 1, 20),
    )

    skip_away_turns(today=TODAY)

    entry = ActivityLog.objects.get(verb=LogVerb.SKIPPED_AWAY)
    assert entry.turn == turn
    assert entry.actor is None
    assert entry.detail["assignee"] == "Ana"
    # Never recorded as a miss — that is the whole point of plan.md §8.
    assert not entries(LogVerb.MISSED)


def test_handing_the_turn_on_is_logged_with_both_names(make_turn, members):
    make_turn(dt.date(2026, 1, 12), members[0])
    AwayPeriod.objects.create(
        member=members[0],
        start_date=dt.date(2026, 1, 10),
        end_date=dt.date(2026, 1, 20),
    )

    skip_away_turns(today=TODAY)

    entry = ActivityLog.objects.get(verb=LogVerb.REASSIGNED)
    assert entry.detail["from_member"] == "Ana"
    assert entry.detail["to_member"] == "Ben"
    assert entry.detail["because"] == "away"


def test_a_second_skip_run_writes_no_duplicate_entries(make_turn, members):
    make_turn(dt.date(2026, 1, 12), members[0])
    AwayPeriod.objects.create(
        member=members[0],
        start_date=dt.date(2026, 1, 10),
        end_date=dt.date(2026, 1, 20),
    )

    skip_away_turns(today=TODAY)
    skip_away_turns(today=TODAY)

    assert len(entries(LogVerb.SKIPPED_AWAY)) == 1
    assert len(entries(LogVerb.REASSIGNED)) == 1


# Criterion 4 — swaps.


def test_a_swap_writes_an_entry_for_each_turn(make_turn, members):
    mine = make_turn(dt.date(2026, 1, 12), members[0])
    theirs = make_turn(dt.date(2026, 1, 19), members[1])

    swap_turns(mine, theirs)

    swapped = entries(LogVerb.SWAPPED)
    assert len(swapped) == 2
    assert {e.turn_id for e in swapped} == {mine.pk, theirs.pk}


def test_a_swap_entry_names_both_sides_and_what_was_traded(make_turn, members):
    """Looking a turn up should not need knowing what it was traded for."""
    mine = make_turn(dt.date(2026, 1, 12), members[0])
    theirs = make_turn(dt.date(2026, 1, 19), members[1])

    swap_turns(mine, theirs)

    entry = ActivityLog.objects.get(verb=LogVerb.SWAPPED, turn=mine)
    assert entry.detail["from_member"] == "Ana"
    assert entry.detail["to_member"] == "Ben"
    assert entry.detail["traded_for"] == "Bins on 2026-01-19"


def test_a_refused_swap_writes_nothing(make_turn, members):
    from schedule.services.transitions import TransitionRefused

    mine = make_turn(dt.date(2026, 1, 12), members[0])
    done = make_turn(dt.date(2026, 1, 19), members[1], status=TurnStatus.COMPLETED)

    with pytest.raises(TransitionRefused):
        swap_turns(mine, done)

    assert ActivityLog.objects.count() == 0


# Criterion 5 — append-only, enforced rather than assumed.


def test_an_entry_cannot_be_edited(make_turn, members):
    """A log that can be quietly edited is worth less than no log."""
    turn = make_turn(TODAY, members[0])
    complete_turn(turn, members[0], when=EVENING)
    entry = ActivityLog.objects.get()

    entry.detail = {"assignee": "somebody else"}
    with pytest.raises(ActivityLog.Immutable):
        entry.save()

    entry.refresh_from_db()
    assert entry.detail["assignee"] == "Ana"


def test_an_entry_cannot_be_deleted(make_turn, members):
    turn = make_turn(TODAY, members[0])
    complete_turn(turn, members[0], when=EVENING)
    entry = ActivityLog.objects.get()

    with pytest.raises(ActivityLog.Immutable):
        entry.delete()

    assert ActivityLog.objects.count() == 1


def test_the_actor_going_away_does_not_take_the_entry_with_them(make_turn, members):
    """plan.md §1 deactivates rather than deletes, but the log must survive
    either way — leaving must not launder your record."""
    turn = make_turn(TODAY, members[3])
    complete_turn(turn, members[3], when=EVENING)

    Turn.objects.filter(assignee=members[3]).delete()
    members[3].delete()

    entry = ActivityLog.objects.get()
    assert entry.actor is None
    assert entry.detail["assignee"] == "Dev"


def test_the_names_in_detail_outlive_the_rows_they_came_from(make_turn, members):
    """Detail holds names, not ids, precisely so the story stays readable."""
    turn = make_turn(TODAY, members[0])
    complete_turn(turn, members[3], when=EVENING)

    assert ActivityLog.objects.get().detail["assignee"] == "Ana"


# Criterion 6 — nothing changes state without a trace.


def test_every_transition_leaves_a_trace(make_turn, members, household):
    """One of each, and the log accounts for all of them."""
    complete_turn(make_turn(TODAY, members[0]), members[0], when=EVENING)
    make_turn(dt.date(2025, 12, 1), members[1])
    mark_overdue(today=TODAY)
    mine = make_turn(dt.date(2026, 3, 2), members[0])
    theirs = make_turn(dt.date(2026, 3, 9), members[1])
    swap_turns(mine, theirs)
    make_turn(dt.date(2026, 1, 12), members[2])
    AwayPeriod.objects.create(
        member=members[2],
        start_date=dt.date(2026, 1, 10),
        end_date=dt.date(2026, 1, 20),
    )
    skip_away_turns(today=TODAY)

    assert {e.verb for e in ActivityLog.objects.all()} == {
        LogVerb.COMPLETED,
        LogVerb.MISSED,
        LogVerb.SWAPPED,
        LogVerb.SKIPPED_AWAY,
        LogVerb.REASSIGNED,
    }
    assert all(e.household_id == household.pk for e in ActivityLog.objects.all())


def test_entries_are_scoped_to_their_own_household(make_turn, members, household):
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

    complete_turn(make_turn(TODAY, members[0]), members[0], when=EVENING)
    complete_turn(their_turn, outsider, when=EVENING)

    assert ActivityLog.objects.filter(household=household).count() == 1
    assert ActivityLog.objects.filter(household=other).count() == 1
