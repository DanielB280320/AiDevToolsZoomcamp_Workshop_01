"""Smoke tests: the fixtures save, and the model guarantees task 2 rests on hold."""

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

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
