"""Fixtures shared by the whole suite.

The household here is deliberately the shape plan.md §1 describes — five
roommates, one of them an admin — because that is what every later feature has
to behave correctly against. Nothing in the app may assume this *number*; the
fixture is a realistic sample, not a contract.
"""

import datetime as dt

import pytest
from freezegun import freeze_time

from accounts.models import Household, Member

# A fixed Monday. The date logic in later tasks steps by weeks and months, so a
# stable, known weekday makes expected due dates readable in the tests rather
# than something the reader has to recompute.
REFERENCE_DATE = dt.date(2026, 1, 5)
REFERENCE_DATETIME = dt.datetime(2026, 1, 5, 9, 0, tzinfo=dt.UTC)

DEFAULT_PIN = "918273"

ROOMMATE_NAMES = ["Ana", "Ben", "Cleo", "Dev", "Elif"]


@pytest.fixture
def frozen_clock():
    """Freeze time at REFERENCE_DATETIME; yields the freezegun factory.

    Tests move time with ``frozen_clock.move_to(...)`` or ``.tick(...)``, which
    is how the overdue and cadence logic in later tasks gets exercised without
    sleeping or waiting for a real calendar to turn over.
    """
    with freeze_time(REFERENCE_DATETIME) as clock:
        yield clock


@pytest.fixture
def today():
    return REFERENCE_DATE


@pytest.fixture
def household(db):
    return Household.objects.create(name="Flat 3B", timezone="Europe/Madrid")


@pytest.fixture
def make_member(household):
    """Build extra roommates inside a test.

    Takes a household so a test can create a *second* household and prove no
    query leaks across the boundary (architecture.md §6).
    """

    def _make_member(display_name, *, pin=DEFAULT_PIN, house=None, **extra):
        return Member.objects.create_user(
            display_name=display_name,
            password=pin,
            household=house or household,
            **extra,
        )

    return _make_member


@pytest.fixture
def members(make_member):
    """Five roommates, the first of whom is the household admin."""
    return [
        make_member(name, is_admin=(index == 0))
        for index, name in enumerate(ROOMMATE_NAMES)
    ]


@pytest.fixture
def admin_member(members):
    return members[0]


@pytest.fixture
def roommate(members):
    """A roommate with no admin rights — the other side of every permission test."""
    return members[1]
