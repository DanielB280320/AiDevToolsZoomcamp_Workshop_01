"""Chore definitions and their per-chore cadence (task 8).

The point of these tests is plan.md §2's decision that frequency belongs to the
chore rather than to the household: two chores in one flat must be able to run
on different clocks, and each must work out its own due dates from its own
anchor.
"""

import datetime as dt

import pytest
from django.db.utils import IntegrityError

from chores.models import Cadence, Chore, add_months


@pytest.fixture
def make_chore(household, today):
    def _make_chore(name, *, unit=Cadence.WEEK, interval=1, anchor=None, **extra):
        return Chore.objects.create(
            household=household,
            name=name,
            cadence_unit=unit,
            cadence_interval=interval,
            anchor_date=anchor or today,
            **extra,
        )

    return _make_chore


# Criterion 1 — a chore carries the fields the task names.


def test_chore_stores_name_description_cadence_start_date_and_active_flag(make_chore):
    chore = make_chore(
        "Bins",
        description="Kerb by 7am Tuesday.",
        unit=Cadence.WEEK,
        interval=2,
    )
    chore.refresh_from_db()

    assert chore.name == "Bins"
    assert chore.description == "Kerb by 7am Tuesday."
    assert chore.cadence_unit == Cadence.WEEK
    assert chore.cadence_interval == 2
    assert chore.anchor_date == dt.date(2026, 1, 5)
    assert chore.is_active is True


def test_description_is_optional(make_chore):
    assert make_chore("Recycling").description == ""


def test_chore_names_are_unique_within_a_household(make_chore):
    make_chore("Bins")
    with pytest.raises(IntegrityError):
        make_chore("Bins")


def test_the_same_chore_name_may_exist_in_another_household(make_chore, make_member):
    from accounts.models import Household

    make_chore("Bins")
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    # No clash: the constraint is per household, not global.
    Chore.objects.create(household=other, name="Bins", anchor_date=dt.date(2026, 1, 5))
    assert Chore.objects.filter(name="Bins").count() == 2


# Criterion 2 — cadence is per chore, and each chore steps on its own clock.


def test_two_chores_in_one_household_run_on_different_cadences(make_chore):
    bins = make_chore("Bins", unit=Cadence.WEEK, interval=1)
    oven = make_chore("Oven", unit=Cadence.MONTH, interval=1)

    assert bins.due_date_for_cycle(1) == dt.date(2026, 1, 12)
    assert oven.due_date_for_cycle(1) == dt.date(2026, 2, 5)
    # The household holds both without either one imposing its clock.
    assert bins.household_id == oven.household_id


@pytest.mark.parametrize(
    ("unit", "interval", "cycle", "expected"),
    [
        (Cadence.DAY, 1, 3, dt.date(2026, 1, 8)),
        (Cadence.DAY, 10, 1, dt.date(2026, 1, 15)),
        (Cadence.WEEK, 1, 4, dt.date(2026, 2, 2)),
        (Cadence.WEEK, 2, 3, dt.date(2026, 2, 16)),
        (Cadence.MONTH, 1, 2, dt.date(2026, 3, 5)),
        (Cadence.MONTH, 3, 2, dt.date(2026, 7, 5)),
    ],
)
def test_due_date_for_cycle_steps_by_the_chores_own_cadence(
    make_chore, unit, interval, cycle, expected
):
    chore = make_chore("Anything", unit=unit, interval=interval)
    assert chore.due_date_for_cycle(cycle) == expected


def test_cycle_zero_is_the_anchor_itself(make_chore):
    assert make_chore("Bins").due_date_for_cycle(0) == dt.date(2026, 1, 5)


def test_cadence_label_reads_naturally(make_chore):
    assert make_chore("A", unit=Cadence.WEEK, interval=1).cadence_label == "Weekly"
    assert make_chore("B", unit=Cadence.MONTH, interval=1).cadence_label == "Monthly"
    assert make_chore("C", unit=Cadence.DAY, interval=1).cadence_label == "Daily"
    assert (
        make_chore("D", unit=Cadence.WEEK, interval=2).cadence_label == "Every 2 weeks"
    )


# Criterion 6 — month-end, the case that quietly corrupts a monthly rota.


def test_a_chore_anchored_on_the_31st_clamps_into_short_months(make_chore):
    chore = make_chore("Oven", unit=Cadence.MONTH, anchor=dt.date(2026, 1, 31))

    assert chore.due_date_for_cycle(1) == dt.date(2026, 2, 28)
    assert chore.due_date_for_cycle(2) == dt.date(2026, 3, 31)
    assert chore.due_date_for_cycle(3) == dt.date(2026, 4, 30)


def test_month_end_clamping_does_not_drift_the_chore_permanently(make_chore):
    """February must not pin every later month to the 28th.

    This is why due dates are computed from the anchor rather than by adding to
    the previous result — the drifting version passes February and then quietly
    moves the chore a few days earlier for the rest of the year.
    """
    chore = make_chore("Oven", unit=Cadence.MONTH, anchor=dt.date(2026, 1, 31))
    assert [chore.due_date_for_cycle(n).day for n in range(1, 6)] == [
        28,
        31,
        30,
        31,
        30,
    ]


def test_february_29_in_a_leap_year(make_chore):
    chore = make_chore("Oven", unit=Cadence.MONTH, anchor=dt.date(2028, 1, 31))
    assert chore.due_date_for_cycle(1) == dt.date(2028, 2, 29)


def test_add_months_crosses_the_year_boundary():
    assert add_months(dt.date(2026, 11, 30), 2) == dt.date(2027, 1, 30)
    assert add_months(dt.date(2026, 12, 31), 1) == dt.date(2027, 1, 31)
    assert add_months(dt.date(2026, 12, 31), 2) == dt.date(2027, 2, 28)


# Criterion 5 — archiving is a flag, not a delete.


def test_archiving_keeps_the_row_and_leaves_the_active_queryset(make_chore):
    chore = make_chore("Bins")
    chore.is_active = False
    chore.save(update_fields=["is_active"])

    assert Chore.objects.filter(pk=chore.pk).exists()
    assert chore not in Chore.objects.active()
    assert chore in Chore.objects.all()


def test_for_household_does_not_leak_across_households(make_chore, household):
    from accounts.models import Household

    mine = make_chore("Bins")
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    theirs = Chore.objects.create(
        household=other, name="Their bins", anchor_date=dt.date(2026, 1, 5)
    )

    scoped = Chore.objects.for_household(household)
    assert mine in scoped
    assert theirs not in scoped
