"""Generating the upcoming schedule (task 12).

plan.md §2 chose fixed rotation for predictability: everyone should see their
turns coming well in advance. architecture.md §4 requires generation to be
idempotent, because it runs on cron *and* lazily on dashboard load.
"""

import datetime as dt
from itertools import pairwise

import pytest
from django.core.management import call_command
from django.utils import timezone

from chores.models import Cadence, Chore
from schedule.models import TurnStatus
from schedule.services.generation import (
    DEFAULT_HORIZON_WEEKS,
    generate_for_chore,
    generate_for_household,
)

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 1, 5)


@pytest.fixture(autouse=True)
def _clock(frozen_clock):
    """Freeze the whole module at TODAY.

    Generation's window starts at the later of the anchor and the day the chore
    was created, so a chore created at real wall-clock time would sit outside
    every window these tests describe. The fixture is what makes ``created_at``
    a date the test controls rather than whenever the suite happened to run.
    """


@pytest.fixture
def make_chore(household):
    def _make_chore(
        name="Bins", *, unit=Cadence.WEEK, interval=1, anchor=TODAY, **extra
    ):
        return Chore.objects.create(
            household=household,
            name=name,
            cadence_unit=unit,
            cadence_interval=interval,
            anchor_date=anchor,
            **extra,
        )

    return _make_chore


@pytest.fixture
def bins(make_chore, members):
    chore = make_chore("Bins")
    chore.set_rotation(members[:3])
    return chore


def due_dates(chore):
    return [t.due_date for t in chore.turns.order_by("cycle_index")]


def assignees(chore):
    return [t.assignee.display_name for t in chore.turns.order_by("cycle_index")]


# Criterion 1 — a horizon of turns, stepping by the chore's own cadence.


def test_generation_fills_the_default_eight_week_horizon(bins):
    generate_for_chore(bins, today=TODAY)

    assert DEFAULT_HORIZON_WEEKS == 8
    horizon_end = TODAY + dt.timedelta(weeks=8)
    dates = due_dates(bins)
    assert dates[0] == TODAY
    assert max(dates) <= horizon_end
    # Weekly over eight weeks, inclusive of both ends.
    assert dates == [TODAY + dt.timedelta(weeks=n) for n in range(9)]


def test_the_horizon_is_adjustable(bins):
    generate_for_chore(bins, today=TODAY, horizon_weeks=2)
    assert due_dates(bins) == [TODAY + dt.timedelta(weeks=n) for n in range(3)]


def test_a_fortnightly_chore_steps_by_two_weeks(make_chore, members):
    chore = make_chore("Oven", unit=Cadence.WEEK, interval=2)
    chore.set_rotation(members[:2])
    generate_for_chore(chore, today=TODAY, horizon_weeks=8)

    assert due_dates(chore) == [TODAY + dt.timedelta(weeks=n) for n in (0, 2, 4, 6, 8)]


def test_two_chores_on_different_cadences_interleave(make_chore, members, household):
    weekly = make_chore("Bins", unit=Cadence.WEEK)
    weekly.set_rotation(members[:2])
    monthly = make_chore("Oven", unit=Cadence.MONTH)
    monthly.set_rotation(members[2:4])

    generate_for_household(household, today=TODAY, horizon_weeks=8)

    assert len(due_dates(weekly)) == 9
    assert due_dates(monthly) == [TODAY, dt.date(2026, 2, 5)]


def test_each_turn_starts_the_day_after_the_previous_one_was_due(bins):
    generate_for_chore(bins, today=TODAY, horizon_weeks=3)
    turns = list(bins.turns.order_by("cycle_index"))

    assert turns[0].period_start == turns[0].due_date
    for earlier, later in pairwise(turns):
        assert later.period_start == earlier.due_date + dt.timedelta(days=1)


def test_generated_turns_start_pending(bins):
    generate_for_chore(bins, today=TODAY)
    assert {t.status for t in bins.turns.all()} == {TurnStatus.PENDING}


def test_cycle_indexes_are_monotonic_from_the_anchor(bins):
    generate_for_chore(bins, today=TODAY, horizon_weeks=4)
    assert [t.cycle_index for t in bins.turns.order_by("cycle_index")] == list(range(5))


# Criterion 2 — the assignee walks that chore's rotation, and wraps.


def test_assignees_follow_the_rotation_in_order(bins, members):
    generate_for_chore(bins, today=TODAY, horizon_weeks=2)
    assert assignees(bins)[:3] == ["Ana", "Ben", "Cleo"]


def test_the_rotation_wraps_around_past_its_end(bins):
    generate_for_chore(bins, today=TODAY, horizon_weeks=8)
    # Three in the rota, nine turns: three full laps.
    assert assignees(bins) == ["Ana", "Ben", "Cleo"] * 3


def test_two_chores_walk_their_own_rotations_independently(
    make_chore, members, household
):
    bins = make_chore("Bins")
    bins.set_rotation([members[0], members[1]])
    bathroom = make_chore("Bathroom")
    bathroom.set_rotation([members[1], members[0]])

    generate_for_household(household, today=TODAY, horizon_weeks=2)

    assert assignees(bins) == ["Ana", "Ben", "Ana"]
    assert assignees(bathroom) == ["Ben", "Ana", "Ben"]


def test_the_assignee_is_written_onto_the_row_not_derived_later(bins, members):
    """The guarantee plan.md §4 rests on."""
    generate_for_chore(bins, today=TODAY, horizon_weeks=2)
    before = assignees(bins)

    bins.set_rotation([members[4], members[3]])

    assert assignees(bins) == before


# Criterion 3 — running it again changes nothing.


def test_a_second_run_creates_nothing(bins):
    first = generate_for_chore(bins, today=TODAY)
    second = generate_for_chore(bins, today=TODAY)

    assert len(first) == 9
    assert second == []
    assert bins.turns.count() == 9


def test_a_second_run_does_not_touch_the_existing_rows(bins):
    generate_for_chore(bins, today=TODAY)
    snapshot = {(t.pk, t.assignee_id, t.due_date, t.status) for t in bins.turns.all()}

    generate_for_chore(bins, today=TODAY)

    assert {
        (t.pk, t.assignee_id, t.due_date, t.status) for t in bins.turns.all()
    } == snapshot


def test_a_second_run_after_a_rotation_change_leaves_history_alone(bins, members):
    generate_for_chore(bins, today=TODAY, horizon_weeks=2)
    before = assignees(bins)

    bins.set_rotation([members[4]])
    generate_for_chore(bins, today=TODAY, horizon_weeks=2)

    assert assignees(bins) == before


def test_rolling_the_horizon_forward_adds_only_the_new_tail(bins):
    generate_for_chore(bins, today=TODAY, horizon_weeks=2)
    assert bins.turns.count() == 3

    added = generate_for_chore(bins, today=TODAY, horizon_weeks=4)

    assert len(added) == 2
    assert bins.turns.count() == 5


def test_a_completed_turn_is_not_regenerated_or_reset(bins, members):
    generate_for_chore(bins, today=TODAY, horizon_weeks=2)
    turn = bins.turns.order_by("cycle_index").first()
    turn.status = TurnStatus.COMPLETED
    turn.completed_by = members[0]
    turn.save(update_fields=["status", "completed_by"])

    generate_for_chore(bins, today=TODAY, horizon_weeks=2)

    turn.refresh_from_db()
    assert turn.status == TurnStatus.COMPLETED
    assert bins.turns.count() == 3


# Criterion 4 — nothing to generate for an archived or unmanned chore.


def test_an_archived_chore_generates_nothing(bins):
    bins.is_active = False
    bins.save(update_fields=["is_active"])

    assert generate_for_chore(bins, today=TODAY) == []
    assert bins.turns.count() == 0


def test_archiving_stops_new_turns_but_keeps_the_old_ones(bins):
    generate_for_chore(bins, today=TODAY, horizon_weeks=2)
    bins.is_active = False
    bins.save(update_fields=["is_active"])

    generate_for_chore(bins, today=TODAY, horizon_weeks=8)

    assert bins.turns.count() == 3


def test_a_chore_with_nobody_in_its_rotation_generates_nothing(make_chore):
    lonely = make_chore("Nobody's job")
    assert generate_for_chore(lonely, today=TODAY) == []
    assert lonely.turns.count() == 0


def test_household_generation_skips_archived_chores(make_chore, members, household):
    live = make_chore("Bins")
    live.set_rotation(members[:2])
    dead = make_chore("Old", is_active=False)
    dead.set_rotation(members[:2])

    generate_for_household(household, today=TODAY, horizon_weeks=2)

    assert live.turns.count() == 3
    assert dead.turns.count() == 0


def test_generation_does_not_reach_into_another_household(make_chore, members):
    from accounts.models import Household, Member

    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )
    theirs = Chore.objects.create(household=other, name="Their bins", anchor_date=TODAY)
    theirs.set_rotation([outsider])
    mine = make_chore("Bins")
    mine.set_rotation(members[:2])

    generate_for_household(mine.household, today=TODAY, horizon_weeks=2)

    assert mine.turns.count() == 3
    assert theirs.turns.count() == 0


# Criterion 5 — month-end, and the window's own boundaries.


def test_a_monthly_chore_anchored_at_month_end_does_not_drift(make_chore, members):
    chore = make_chore("Oven", unit=Cadence.MONTH, anchor=dt.date(2026, 1, 31))
    chore.set_rotation(members[:2])

    generate_for_chore(chore, today=dt.date(2026, 1, 31), horizon_weeks=20)

    assert due_dates(chore)[:5] == [
        dt.date(2026, 1, 31),
        dt.date(2026, 2, 28),
        dt.date(2026, 3, 31),
        dt.date(2026, 4, 30),
        dt.date(2026, 5, 31),
    ]


def test_nothing_is_generated_before_the_chore_existed(make_chore, members):
    """An admin back-dating an anchor must not invent turns everyone missed."""
    chore = make_chore("Bins", anchor=dt.date(2025, 1, 1))
    chore.set_rotation(members[:2])

    generate_for_chore(chore, today=TODAY, horizon_weeks=2)

    created_on = timezone.localdate(chore.created_at)
    assert min(due_dates(chore)) >= created_on
    assert dt.date(2025, 1, 1) not in due_dates(chore)


def test_the_cadence_phase_survives_a_back_dated_anchor(make_chore, members):
    """Back-dating is how you set which day of the week a chore lands on."""
    # 2025-01-01 was a Wednesday; every generated turn should also be one.
    chore = make_chore("Bins", anchor=dt.date(2025, 1, 1))
    chore.set_rotation(members[:2])

    generate_for_chore(chore, today=TODAY, horizon_weeks=4)

    assert {d.weekday() for d in due_dates(chore)} == {2}


def test_a_chore_starting_in_the_future_waits_for_its_anchor(make_chore, members):
    chore = make_chore("Bins", anchor=dt.date(2026, 2, 1))
    chore.set_rotation(members[:2])

    generate_for_chore(chore, today=TODAY, horizon_weeks=8)

    assert min(due_dates(chore)) == dt.date(2026, 2, 1)


def test_a_chore_anchored_past_the_horizon_generates_nothing_yet(make_chore, members):
    chore = make_chore("Bins", anchor=dt.date(2027, 1, 1))
    chore.set_rotation(members[:2])

    assert generate_for_chore(chore, today=TODAY, horizon_weeks=8) == []


def test_late_cron_still_gets_the_turns_it_slept_through(bins):
    """Not generating from `today` is deliberate: a gap would lose turns.

    If nobody opens the app for a fortnight, the turns due in that fortnight
    still have to exist, or task 15 could never mark them missed.
    """
    generate_for_chore(bins, today=TODAY + dt.timedelta(weeks=2), horizon_weeks=1)

    assert TODAY in due_dates(bins)
    assert min(due_dates(bins)) == TODAY


# Criterion 6 — the management command.


def test_the_management_command_generates_and_reports(bins, capsys):
    call_command("generate_turns", "--weeks", "2")

    assert bins.turns.count() == 3
    out = capsys.readouterr().out
    assert "Flat 3B: 3 new turns" in out
    assert "3 new turns across 1 household(s)." in out


def test_running_the_command_twice_is_harmless(bins, capsys):
    call_command("generate_turns", "--weeks", "2")
    capsys.readouterr()
    call_command("generate_turns", "--weeks", "2")

    assert bins.turns.count() == 3
    assert "0 new turns" in capsys.readouterr().out


def test_the_command_defaults_to_the_eight_week_horizon(bins):
    call_command("generate_turns")
    assert bins.turns.count() == 9


def test_a_concurrent_run_collides_harmlessly_rather_than_raising(bins, monkeypatch):
    """architecture.md §5: two generation runs racing must not blow up.

    The `existing` check is the ordinary idempotency mechanism, but it can go
    stale — another run may insert between our reading it and our writing. This
    simulates exactly that by making the check lie, which is the only state the
    unique constraint is left to handle alone.
    """
    from schedule.services import generation

    generation.generate_for_chore(bins, today=TODAY, horizon_weeks=2)
    assert bins.turns.count() == 3

    monkeypatch.setattr(generation, "existing_cycles", lambda chore, cycles: set())

    # Every row it tries to write is already there. It must not raise, and must
    # not double-book the cycle.
    generation.generate_for_chore(bins, today=TODAY, horizon_weeks=2)

    assert bins.turns.count() == 3
    assert [t.cycle_index for t in bins.turns.order_by("cycle_index")] == [0, 1, 2]
