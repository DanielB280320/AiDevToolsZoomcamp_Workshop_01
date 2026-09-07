"""Smoke tests: the fixtures save, and the model guarantees task 2 rests on hold."""

import datetime as dt
import importlib.util
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from accounts.models import Household, Member
from conftest import DEFAULT_PIN, REFERENCE_DATE

pytestmark = pytest.mark.django_db


def test_household_fixture_saves(household):
    assert household.pk is not None
    assert Household.objects.count() == 1


def test_five_roommates_one_admin(members, household):
    assert len(members) == 5
    assert Member.objects.count() == 5
    assert household.member_count == 5
    assert [m for m in members if m.is_admin] == [members[0]]


def test_members_belong_to_the_household(members, household):
    assert set(household.members.all()) == set(members)


class TestPinStorage:
    def test_pin_is_hashed_never_stored_in_plaintext(self, roommate):
        assert DEFAULT_PIN not in roommate.password
        assert roommate.password != DEFAULT_PIN

    def test_check_pin_accepts_the_right_pin_and_rejects_others(self, roommate):
        assert roommate.check_pin(DEFAULT_PIN) is True
        assert roommate.check_pin("000000") is False

    def test_set_pin_rehashes(self, roommate):
        roommate.set_pin("135791")
        roommate.save()
        roommate.refresh_from_db()
        assert roommate.check_pin("135791") is True
        assert roommate.check_pin(DEFAULT_PIN) is False


class TestSoftRemoval:
    """plan.md §4's history has to survive a roommate moving out."""

    def test_deactivating_keeps_the_row(self, members, household):
        departing = members[-1]
        departing.is_active = False
        departing.save()

        assert Member.objects.filter(pk=departing.pk).exists()
        assert household.member_count == 4
        assert departing not in Member.objects.active()


class TestHouseholdSize:
    """plan.md §1: the roommate list is variable, never a hardcoded count."""

    def test_household_grows(self, members, make_member, household):
        make_member("Frank")
        assert household.member_count == 6

    def test_household_smaller_than_the_fixture_is_fine(self, make_member):
        solo = Household.objects.create(name="Studio")
        Member.objects.create_user("Solo", password=DEFAULT_PIN, household=solo)
        assert solo.member_count == 1


def test_duplicate_display_name_is_rejected(make_member):
    make_member("Ana")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_member("Ana")


def test_duplicate_display_name_is_rejected_case_insensitively(make_member):
    """Sign-in (accounts/backends.py) looks members up with
    display_name__iexact, so "Ana" and "ana" must be treated as the same
    name at the database level too -- otherwise that lookup matches more
    than one row and raises MultipleObjectsReturned instead of
    authenticating anyone. See issue #2, acceptance criterion 5."""
    make_member("Zqx")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_member("zqx")


def test_migration_0003_guard_rejects_existing_case_insensitive_duplicates(household):
    """accounts/migrations/0003_member_unique_display_name_ci.py runs a
    RunPython pre-check before adding the case-insensitive constraint, so
    that a database with pre-existing case-variant duplicates fails
    `migrate` with a clear, actionable message instead of a raw
    IntegrityError from the schema change itself.

    The case-insensitive constraint is already applied in every test
    database (via the normal migration run), so producing a colliding pair
    to check the guard against means temporarily dropping just that index --
    undone automatically when this test's transaction rolls back.
    """
    with connection.cursor() as cursor:
        cursor.execute('DROP INDEX "unique_display_name_ci"')

    Member.objects.create_user(
        display_name="Dup", password=DEFAULT_PIN, household=household
    )
    Member.objects.create_user(
        display_name="dup", password=DEFAULT_PIN, household=household
    )

    migration_path = (
        Path(__file__).resolve().parent.parent
        / "migrations"
        / "0003_member_unique_display_name_ci.py"
    )
    spec = importlib.util.spec_from_file_location(
        "accounts_migration_0003_test", migration_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with pytest.raises(RuntimeError, match="dup"):
        module.reject_existing_case_insensitive_duplicates(django_apps, None)


def test_joined_on_defaults_to_today(frozen_clock, make_member):
    assert make_member("Gus").joined_on == REFERENCE_DATE


def test_household_rejects_an_unknown_timezone():
    with pytest.raises(ValidationError):
        Household(name="Bad", timezone="Mars/Olympus_Mons").full_clean()


def test_frozen_clock_can_move(frozen_clock):
    from django.utils import timezone as django_tz

    start = django_tz.localdate()
    frozen_clock.move_to(dt.datetime(2026, 3, 1, 9, 0, tzinfo=dt.UTC))
    assert django_tz.localdate() > start
