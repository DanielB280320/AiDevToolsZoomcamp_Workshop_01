"""History survives roommate changes (task 13).

This is a standalone task because it is the guarantee most easily broken by a
later change, and the one plan.md §4 depends on entirely. plan.md §1 lets the
roommate list change over time; §4 needs the record of who was responsible to
be trustworthy. Those two only coexist if history is fixed once written.

The failure mode being guarded against is not exotic. It is someone deciding
that ``Turn.assignee`` is redundant -- the rotation and the cycle index are
right there, so why store it? -- and replacing it with a property. Everything
would look fine until the day a sixth roommate joined, at which point every
past turn would silently change hands and the log would start lying about who
did what. These tests fail loudly if that happens.
"""

import datetime as dt

import pytest

from accounts.models import Member
from chores.models import Cadence, Chore
from conftest import DEFAULT_PIN
from schedule.models import TurnStatus
from schedule.services.generation import generate_for_chore

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 1, 5)


@pytest.fixture(autouse=True)
def _clock(frozen_clock):
    """Generation's window depends on ``created_at``; pin it to TODAY."""


@pytest.fixture
def bins(household, members):
    """A weekly chore with all five roommates in its rotation."""
    chore = Chore.objects.create(
        household=household,
        name="Bins",
        cadence_unit=Cadence.WEEK,
        anchor_date=TODAY,
    )
    chore.set_rotation(members)
    return chore


def snapshot(chore):
    """(cycle, assignee id, status, completed_by id) for every turn."""
    return {
        t.cycle_index: (t.assignee_id, t.status, t.completed_by_id)
        for t in chore.turns.all()
    }


def assignee_names(chore):
    return [t.assignee.display_name for t in chore.turns.order_by("cycle_index")]


# The scenario the task describes, told once, start to finish.


def test_the_whole_scenario_adding_and_removing_leaves_the_past_untouched(
    bins, members, household, frozen_clock
):
    # Eight weeks of turns over five roommates.
    generate_for_chore(bins, today=TODAY, horizon_weeks=8)
    assert assignee_names(bins) == [
        "Ana",
        "Ben",
        "Cleo",
        "Dev",
        "Elif",
        "Ana",
        "Ben",
        "Cleo",
        "Dev",
    ]

    # Some of them get done.
    for turn in bins.turns.order_by("cycle_index")[:3]:
        turn.status = TurnStatus.COMPLETED
        turn.completed_by = turn.assignee
        turn.completed_at = dt.datetime(2026, 1, 6, 19, 0, tzinfo=dt.UTC)
        turn.save()

    before = snapshot(bins)

    # A sixth roommate moves in; one of the five moves out.
    frozen_clock.move_to("2026-02-02 09:00:00")
    fran = Member.objects.create_user(
        display_name="Fran", password=DEFAULT_PIN, household=household
    )
    members[1].is_active = False  # Ben leaves
    members[1].save(update_fields=["is_active"])

    # The admin rebuilds the rota around who actually lives there now.
    bins.set_rotation([members[0], members[2], members[3], members[4], fran])

    # Nothing that already existed moved.
    assert snapshot(bins) == before

    # Extending the horizon writes new turns from the new rota, and only those.
    new_turns = generate_for_chore(bins, today=dt.date(2026, 2, 2), horizon_weeks=8)
    assert new_turns, "the rolling horizon should have produced more turns"

    # Every turn that existed before still reads exactly as it did.
    after = snapshot(bins)
    for cycle, record in before.items():
        assert after[cycle] == record, f"cycle {cycle} changed"

    # And the ones that did not exist before draw only on the new rota --
    # Ben, who left, is in none of them.
    # And the new ones draw only on the new rota. It is a subset, not the whole
    # set: four new turns do not complete a lap of five people.
    new_names = {t.assignee.display_name for t in new_turns}
    assert new_names <= {"Ana", "Cleo", "Dev", "Elif", "Fran"}
    assert "Fran" in new_names, "the new roommate should be picking up turns"
    assert "Ben" not in new_names, "the roommate who left should not be"


# Criterion 1 — no existing turn changes hands.


def test_adding_a_roommate_changes_no_existing_turn(bins, members, household):
    generate_for_chore(bins, today=TODAY, horizon_weeks=8)
    before = snapshot(bins)

    fran = Member.objects.create_user(
        display_name="Fran", password=DEFAULT_PIN, household=household
    )
    bins.set_rotation([*members, fran])

    assert snapshot(bins) == before


def test_deactivating_a_roommate_changes_no_existing_turn(bins, members):
    generate_for_chore(bins, today=TODAY, horizon_weeks=8)
    before = snapshot(bins)

    members[2].is_active = False
    members[2].save(update_fields=["is_active"])
    bins.set_rotation([m for m in members if m.is_active])

    assert snapshot(bins) == before


def test_reordering_the_rotation_changes_no_existing_turn(bins, members):
    generate_for_chore(bins, today=TODAY, horizon_weeks=8)
    before = snapshot(bins)

    bins.set_rotation(list(reversed(members)))

    assert snapshot(bins) == before


def test_emptying_the_rotation_entirely_changes_no_existing_turn(bins, members):
    generate_for_chore(bins, today=TODAY, horizon_weeks=8)
    before = snapshot(bins)

    bins.set_rotation([])

    assert snapshot(bins) == before
    assert assignee_names(bins)[0] == "Ana"


# Criterion 2 — a completion survives the change.


def test_a_completed_turn_keeps_its_whole_record(bins, members, household):
    generate_for_chore(bins, today=TODAY, horizon_weeks=2)
    turn = bins.turns.order_by("cycle_index").first()
    done_at = dt.datetime(2026, 1, 5, 20, 30, tzinfo=dt.UTC)
    turn.status = TurnStatus.COMPLETED
    turn.completed_by = members[3]  # Dev covered for Ana
    turn.completed_at = done_at
    turn.save()

    fran = Member.objects.create_user(
        display_name="Fran", password=DEFAULT_PIN, household=household
    )
    members[3].is_active = False  # the person who actually did it leaves
    members[3].save(update_fields=["is_active"])
    bins.set_rotation([fran])

    turn.refresh_from_db()
    assert turn.assignee == members[0]
    assert turn.completed_by == members[3]
    assert turn.completed_at == done_at
    assert turn.status == TurnStatus.COMPLETED
    assert turn.was_covered is True


# Criteria 3 and 5 — only the new turns reflect the new rota.


def test_only_turns_generated_after_the_change_use_the_new_rotation(
    bins, members, household
):
    generate_for_chore(bins, today=TODAY, horizon_weeks=2)
    old_cycles = set(bins.turns.values_list("cycle_index", flat=True))
    assert assignee_names(bins) == ["Ana", "Ben", "Cleo"]

    fran = Member.objects.create_user(
        display_name="Fran", password=DEFAULT_PIN, household=household
    )
    bins.set_rotation([fran])

    generate_for_chore(bins, today=TODAY, horizon_weeks=5)

    old = bins.turns.filter(cycle_index__in=old_cycles).order_by("cycle_index")
    new = bins.turns.exclude(cycle_index__in=old_cycles)
    assert [t.assignee.display_name for t in old] == ["Ana", "Ben", "Cleo"]
    assert {t.assignee.display_name for t in new} == {"Fran"}


def test_a_new_roommate_never_appears_in_a_turn_that_predates_them(
    bins, members, household
):
    generate_for_chore(bins, today=TODAY, horizon_weeks=8)
    existing = set(bins.turns.values_list("pk", flat=True))

    fran = Member.objects.create_user(
        display_name="Fran", password=DEFAULT_PIN, household=household
    )
    bins.set_rotation([*members, fran])
    generate_for_chore(bins, today=TODAY, horizon_weeks=16)

    assert not bins.turns.filter(pk__in=existing, assignee=fran).exists()


# Criterion 4 — a departed roommate keeps their name on their turns.


def test_a_deactivated_roommates_turns_still_point_at_them(bins, members):
    generate_for_chore(bins, today=TODAY, horizon_weeks=8)
    ben_turns = set(bins.turns.filter(assignee=members[1]).values_list("pk", flat=True))
    assert ben_turns

    members[1].is_active = False
    members[1].save(update_fields=["is_active"])
    bins.set_rotation([m for m in members if m.pk != members[1].pk])

    assert (
        set(bins.turns.filter(assignee=members[1]).values_list("pk", flat=True))
        == ben_turns
    )


def test_a_departed_roommates_misses_stay_on_their_record(bins, members):
    """plan.md §4: the log is what settles who missed what. Leaving must not
    launder that."""
    generate_for_chore(bins, today=TODAY, horizon_weeks=2)
    turn = bins.turns.get(assignee=members[1])
    turn.status = TurnStatus.MISSED
    turn.save(update_fields=["status"])

    members[1].is_active = False
    members[1].save(update_fields=["is_active"])

    turn.refresh_from_db()
    assert turn.assignee == members[1]
    assert turn.status == TurnStatus.MISSED


# Criterion 6 — the trap this task exists to catch.


def test_assignees_deliberately_disagree_with_a_recomputed_rotation(bins, members):
    """The canary for compute-on-read.

    After the rota is reversed, ``rotation[cycle % len(rotation)]`` gives a
    different answer than the stored assignee for almost every turn. If someone
    replaces ``Turn.assignee`` with a property computing exactly that, this test
    is where it shows up -- and it shows up as history changing hands, which is
    the actual harm.
    """
    generate_for_chore(bins, today=TODAY, horizon_weeks=8)
    stored = assignee_names(bins)

    bins.set_rotation(list(reversed(members)))

    rota = bins.rotation
    recomputed = [
        rota[t.cycle_index % len(rota)].display_name
        for t in bins.turns.order_by("cycle_index")
    ]

    assert assignee_names(bins) == stored
    assert recomputed != stored, "the rotation change must actually be observable"
    assert sum(a != b for a, b in zip(stored, recomputed, strict=True)) >= 6


def test_the_assignee_column_is_real_and_not_a_property():
    """A property would satisfy every read in this file until the day it didn't."""
    from schedule.models import Turn

    field = Turn._meta.get_field("assignee")
    assert field.concrete is True
    assert field.many_to_one is True
