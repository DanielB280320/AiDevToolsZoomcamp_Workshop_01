"""The turn record (task 11).

plan.md §4 wants a completion log per chore, per roommate, per cycle. That only
works if an occurrence is a stored row: architecture.md §4 rejects computing the
assignee on read, because membership changes would then rewrite the past.
"""

import datetime as dt

import pytest
from django.db import transaction
from django.db.utils import IntegrityError

from accounts.models import Household, Member
from chores.models import Chore
from schedule.models import TERMINAL_STATUSES, Turn, TurnStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def bins(household, today):
    return Chore.objects.create(
        household=household, name="Bins", anchor_date=today, grace_days=2
    )


@pytest.fixture
def make_turn(bins, members):
    def _make_turn(cycle_index=0, *, assignee=None, chore=None, **extra):
        chore = chore or bins
        return Turn.objects.create(
            chore=chore,
            assignee=assignee or members[cycle_index % len(members)],
            cycle_index=cycle_index,
            period_start=chore.due_date_for_cycle(cycle_index),
            due_date=chore.due_date_for_cycle(cycle_index),
            **extra,
        )

    return _make_turn


# Criterion 1 — the record holds what plan.md §4's log needs.


def test_a_turn_stores_its_chore_assignee_cycle_dates_and_status(
    make_turn, bins, members
):
    turn = make_turn(0)
    turn.refresh_from_db()

    assert turn.chore == bins
    assert turn.assignee == members[0]
    assert turn.cycle_index == 0
    assert turn.period_start == dt.date(2026, 1, 5)
    assert turn.due_date == dt.date(2026, 1, 5)
    assert turn.status == TurnStatus.PENDING
    assert turn.completed_at is None
    assert turn.completed_by is None


def test_a_new_turn_is_pending_by_default(make_turn):
    assert make_turn(0).status == TurnStatus.PENDING


def test_the_deadline_is_the_due_date_plus_the_chores_grace(make_turn, bins):
    turn = make_turn(0)
    assert bins.grace_days == 2
    assert turn.deadline() == dt.date(2026, 1, 7)


def test_turns_read_back_in_due_date_order(make_turn):
    later = make_turn(3)
    earlier = make_turn(1)
    assert list(Turn.objects.all()) == [earlier, later]


# Criterion 2 — the statuses, and SKIPPED_AWAY standing on its own.


def test_every_status_the_state_machine_names_exists():
    assert set(TurnStatus.values) == {
        "PENDING",
        "COMPLETED",
        "MISSED",
        "SKIPPED_AWAY",
        "SWAPPED",
    }


def test_skipped_away_is_its_own_status_and_not_a_kind_of_missed():
    """plan.md §8: a planned absence must never be recorded as a failure."""
    assert TurnStatus.SKIPPED_AWAY != TurnStatus.MISSED
    assert TurnStatus.SKIPPED_AWAY in TERMINAL_STATUSES
    assert TurnStatus.MISSED not in TERMINAL_STATUSES


def test_skipped_away_reads_as_an_absence_not_a_failure(make_turn):
    turn = make_turn(0, status=TurnStatus.SKIPPED_AWAY)
    assert turn.get_status_display() == "Skipped — away"
    assert "miss" not in turn.get_status_display().lower()


def test_missed_is_not_terminal_because_a_chore_can_be_done_late(make_turn):
    """architecture.md §4: MISSED → COMPLETED is a legal move."""
    turn = make_turn(0, status=TurnStatus.MISSED)
    assert turn.is_terminal is False


@pytest.mark.parametrize(
    "status",
    [TurnStatus.COMPLETED, TurnStatus.SKIPPED_AWAY, TurnStatus.SWAPPED],
)
def test_the_terminal_statuses_are_terminal(make_turn, status):
    assert make_turn(0, status=status).is_terminal is True


def test_outstanding_covers_pending_and_missed_but_nothing_settled(make_turn):
    pending = make_turn(0, status=TurnStatus.PENDING)
    missed = make_turn(1, status=TurnStatus.MISSED)
    make_turn(2, status=TurnStatus.COMPLETED)
    make_turn(3, status=TurnStatus.SKIPPED_AWAY)

    assert set(Turn.objects.outstanding()) == {pending, missed}


# Criterion 3 — the same turn can never be created twice.


def test_a_chore_cannot_have_two_turns_for_one_cycle(make_turn, members):
    make_turn(0)
    with pytest.raises(IntegrityError):
        make_turn(0, assignee=members[1])


def test_the_uniqueness_holds_even_with_a_different_assignee_and_date(
    bins, members, make_turn
):
    """Identity is (chore, cycle), not the due date — a date can be moved."""
    make_turn(0)
    with transaction.atomic(), pytest.raises(IntegrityError):
        Turn.objects.create(
            chore=bins,
            assignee=members[4],
            cycle_index=0,
            period_start=dt.date(2030, 1, 1),
            due_date=dt.date(2030, 1, 1),
        )


def test_two_chores_may_each_have_their_own_cycle_zero(household, members, make_turn):
    other = Chore.objects.create(
        household=household, name="Bathroom", anchor_date=dt.date(2026, 1, 5)
    )
    make_turn(0)
    make_turn(0, chore=other)
    assert Turn.objects.filter(cycle_index=0).count() == 2


def test_one_chore_may_have_many_cycles(make_turn):
    for cycle in range(5):
        make_turn(cycle)
    assert Turn.objects.count() == 5


# Criterion 4 — who did it is recorded apart from whose turn it was.


def test_completed_by_is_separate_from_assignee_so_covering_is_visible(
    make_turn, members, frozen_clock
):
    turn = make_turn(0, assignee=members[0])
    turn.status = TurnStatus.COMPLETED
    turn.completed_by = members[3]
    turn.completed_at = dt.datetime(2026, 1, 5, 18, 0, tzinfo=dt.UTC)
    turn.save()
    turn.refresh_from_db()

    assert turn.assignee == members[0]
    assert turn.completed_by == members[3]
    assert turn.was_covered is True


def test_doing_your_own_turn_is_not_covering(make_turn, members):
    turn = make_turn(0, assignee=members[0])
    turn.completed_by = members[0]
    turn.save(update_fields=["completed_by"])
    assert turn.was_covered is False


def test_an_uncompleted_turn_is_not_covering(make_turn):
    assert make_turn(0).was_covered is False


def test_a_late_completion_is_distinguishable_from_an_on_time_one(make_turn):
    on_time = make_turn(0, status=TurnStatus.COMPLETED)
    late = make_turn(1, status=TurnStatus.COMPLETED, was_late=True)

    assert on_time.was_late is False
    assert late.was_late is True


# Criterion 5 — a turn is a row, and keeps its assignee whatever the rota does.


def test_a_turn_keeps_its_assignee_when_the_chores_rotation_changes(
    make_turn, bins, members
):
    bins.set_rotation([members[0], members[1]])
    turn = make_turn(0, assignee=members[0])

    bins.set_rotation([members[4], members[3], members[2]])
    turn.refresh_from_db()

    assert turn.assignee == members[0]
    assert members[0] not in bins.rotation


def test_a_turn_keeps_its_assignee_when_a_roommate_is_deactivated(make_turn, members):
    turn = make_turn(0, assignee=members[2])
    members[2].is_active = False
    members[2].save(update_fields=["is_active"])

    turn.refresh_from_db()
    assert turn.assignee == members[2]


def test_a_member_with_turns_cannot_be_deleted_out_from_under_the_history(
    make_turn, members
):
    """PROTECT, not CASCADE: deleting a roommate must not erase who did what.

    plan.md §1's departed roommate is deactivated, never deleted, and the
    database enforces that rather than trusting every future call site.
    """
    from django.db.models import ProtectedError

    make_turn(0, assignee=members[0])
    with pytest.raises(ProtectedError):
        members[0].delete()


def test_turns_are_scoped_by_household(make_turn, household, today):
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )
    their_chore = Chore.objects.create(
        household=other, name="Their bins", anchor_date=today
    )
    mine = make_turn(0)
    theirs = Turn.objects.create(
        chore=their_chore,
        assignee=outsider,
        cycle_index=0,
        period_start=today,
        due_date=today,
    )

    scoped = Turn.objects.for_household(household)
    assert mine in scoped
    assert theirs not in scoped


# Criterion 6 — a swap links the pair it traded with.


def test_a_swap_links_two_turns_to_each_other(make_turn, members):
    mine = make_turn(0, assignee=members[0])
    yours = make_turn(1, assignee=members[1])

    mine.swapped_with = yours
    mine.save(update_fields=["swapped_with"])

    assert mine.swapped_with == yours
    assert yours.swapped_from == mine


def test_a_turn_is_linked_to_at_most_one_other(make_turn, members):
    first = make_turn(0)
    second = make_turn(1)
    third = make_turn(2)

    first.swapped_with = second
    first.save(update_fields=["swapped_with"])

    third.swapped_with = second
    with transaction.atomic(), pytest.raises(IntegrityError):
        third.save(update_fields=["swapped_with"])


def test_deleting_one_side_of_a_swap_leaves_the_other_standing(make_turn):
    mine = make_turn(0)
    yours = make_turn(1)
    mine.swapped_with = yours
    mine.save(update_fields=["swapped_with"])

    yours.delete()
    mine.refresh_from_db()

    assert mine.swapped_with is None
    assert Turn.objects.filter(pk=mine.pk).exists()
