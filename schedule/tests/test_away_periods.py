"""Declaring an absence (task 17).

plan.md §8 requires away handling and leaves open who may mark someone away.
Answered by allowing both — a roommate declares their own, an admin can enter
one for the person already on a plane — with created_by recording which it was.

Recording only. The effect on the schedule is task 18.
"""

import datetime as dt

import pytest
from django.db import transaction
from django.db.utils import IntegrityError
from django.urls import reverse

from accounts.models import Household, Member
from schedule.models import AwayPeriod

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 1, 5)


@pytest.fixture(autouse=True)
def _clock(frozen_clock):
    """The screen compares against today; pin it."""


@pytest.fixture
def as_admin(client, admin_member):
    """conftest's members[0]. Ana is the household admin, not a plain roommate."""
    client.force_login(admin_member)
    return client


@pytest.fixture
def as_roommate(client, roommate):
    """conftest's members[1] -- Ben, with no admin rights."""
    client.force_login(roommate)
    return client


def form_data(member, **overrides):
    data = {
        "member": str(member.pk),
        "start_date": "2026-02-01",
        "end_date": "2026-02-14",
        "reason": "Holiday",
    }
    data.update(overrides)
    return data


# Criterion 1 — what the record holds.


def test_an_absence_stores_member_dates_reason_and_who_declared_it(members):
    away = AwayPeriod.objects.create(
        member=members[1],
        start_date=dt.date(2026, 2, 1),
        end_date=dt.date(2026, 2, 14),
        reason="Holiday",
        created_by=members[0],
    )
    away.refresh_from_db()

    assert away.member == members[1]
    assert away.start_date == dt.date(2026, 2, 1)
    assert away.end_date == dt.date(2026, 2, 14)
    assert away.reason == "Holiday"
    assert away.created_by == members[0]


def test_a_reason_is_optional(members):
    away = AwayPeriod.objects.create(
        member=members[0], start_date=TODAY, end_date=TODAY
    )
    assert away.reason == ""


def test_a_single_day_absence_is_allowed(members):
    away = AwayPeriod.objects.create(
        member=members[0], start_date=TODAY, end_date=TODAY
    )
    assert away.covers(TODAY)


# Criterion 5 — the dates make sense, and covers() answers task 18's question.


def test_the_database_refuses_an_absence_that_ends_before_it_starts(members):
    with transaction.atomic(), pytest.raises(IntegrityError):
        AwayPeriod.objects.create(
            member=members[0],
            start_date=dt.date(2026, 2, 14),
            end_date=dt.date(2026, 2, 1),
        )


def test_the_form_refuses_it_with_a_readable_message(as_roommate, roommate):
    response = as_roommate.post(
        reverse("away_list"),
        form_data(roommate, start_date="2026-02-14", end_date="2026-02-01"),
    )

    assert response.status_code == 200
    assert "cannot be before the first one" in response.content.decode()
    assert AwayPeriod.objects.count() == 0


@pytest.mark.parametrize(
    ("date", "expected"),
    [
        (dt.date(2026, 1, 31), False),
        (dt.date(2026, 2, 1), True),  # first day, inclusive
        (dt.date(2026, 2, 7), True),
        (dt.date(2026, 2, 14), True),  # last day, inclusive
        (dt.date(2026, 2, 15), False),
    ],
)
def test_covers_includes_both_end_days(members, date, expected):
    away = AwayPeriod.objects.create(
        member=members[0],
        start_date=dt.date(2026, 2, 1),
        end_date=dt.date(2026, 2, 14),
    )
    assert away.covers(date) is expected


def test_covering_finds_the_absences_around_a_date(members):
    match = AwayPeriod.objects.create(
        member=members[0],
        start_date=dt.date(2026, 2, 1),
        end_date=dt.date(2026, 2, 14),
    )
    AwayPeriod.objects.create(
        member=members[1],
        start_date=dt.date(2026, 3, 1),
        end_date=dt.date(2026, 3, 4),
    )

    assert list(AwayPeriod.objects.covering(dt.date(2026, 2, 7))) == [match]
    assert list(AwayPeriod.objects.covering(dt.date(2026, 5, 1))) == []


# Criterion 2 — declaring your own.


def test_a_roommate_declares_their_own_absence(as_roommate, roommate):
    response = as_roommate.post(reverse("away_list"), form_data(roommate), follow=True)

    assert response.status_code == 200
    away = AwayPeriod.objects.get()
    assert away.member == roommate
    assert away.created_by == roommate
    assert away.declared_on_their_behalf is False
    assert "You are down as away" in response.content.decode()


def test_the_form_offers_a_non_admin_only_themselves(as_roommate, roommate):
    form = as_roommate.get(reverse("away_list")).context["form"]

    assert list(form.fields["member"].queryset) == [roommate]
    assert form.fields["member"].disabled is True


def test_a_non_admin_cannot_declare_one_for_someone_else(
    as_roommate, roommate, members
):
    """Quietly booking a flatmate off the rota would be a way to dodge a turn.

    The member field is disabled for a non-admin, so Django ignores whatever is
    posted and falls back to the initial. The tampered value is not rejected
    with an error -- it simply never had any effect, which is the stronger
    outcome: there is no path from this form to someone else's name.
    """
    as_roommate.post(reverse("away_list"), form_data(members[2]))

    assert not AwayPeriod.objects.filter(member=members[2]).exists()
    assert AwayPeriod.objects.get().member == roommate


# Criterion 3 — an admin acting for someone else, and the record of who did it.


def test_an_admin_declares_an_absence_on_someone_elses_behalf(
    as_admin, admin_member, members
):
    response = as_admin.post(reverse("away_list"), form_data(members[3]), follow=True)

    away = AwayPeriod.objects.get()
    assert away.member == members[3]
    assert away.created_by == admin_member
    assert away.declared_on_their_behalf is True
    assert "Recorded Dev away" in response.content.decode()


def test_the_form_offers_an_admin_the_whole_household(as_admin, members):
    form = as_admin.get(reverse("away_list")).context["form"]

    assert set(form.fields["member"].queryset) == set(members)
    assert form.fields["member"].disabled is False


def test_an_admin_declaring_their_own_is_not_on_someone_elses_behalf(
    as_admin, admin_member
):
    as_admin.post(reverse("away_list"), form_data(admin_member))

    away = AwayPeriod.objects.get()
    assert away.declared_on_their_behalf is False


def test_the_screen_says_when_someone_else_entered_it(as_roommate, as_admin, members):
    as_admin.post(reverse("away_list"), form_data(members[1]))

    body = as_roommate.get(reverse("away_list")).content.decode()

    assert "added by Ana" in body


def test_a_deactivated_roommate_is_not_offered(as_admin, members):
    members[3].is_active = False
    members[3].save(update_fields=["is_active"])

    form = as_admin.get(reverse("away_list")).context["form"]

    assert members[3] not in form.fields["member"].queryset


# Criterion 6 — visibility, cancelling, and scoping.


def test_everyone_sees_everyones_absences(as_roommate, members):
    AwayPeriod.objects.create(
        member=members[0], start_date=TODAY, end_date=TODAY, reason="Holiday"
    )

    body = as_roommate.get(reverse("away_list")).content.decode()

    assert "Ana" in body
    assert "Holiday" in body


def test_a_roommate_can_cancel_their_own_absence(as_roommate, roommate):
    away = AwayPeriod.objects.create(member=roommate, start_date=TODAY, end_date=TODAY)

    as_roommate.post(reverse("away_delete", args=[away.pk]))

    assert not AwayPeriod.objects.filter(pk=away.pk).exists()


def test_a_roommate_cannot_cancel_someone_elses(as_roommate, members):
    away = AwayPeriod.objects.create(
        member=members[2], start_date=TODAY, end_date=TODAY
    )

    assert as_roommate.post(reverse("away_delete", args=[away.pk])).status_code == 403
    assert AwayPeriod.objects.filter(pk=away.pk).exists()


def test_an_admin_can_cancel_anyones(as_admin, members):
    away = AwayPeriod.objects.create(
        member=members[2], start_date=TODAY, end_date=TODAY
    )

    as_admin.post(reverse("away_delete", args=[away.pk]))

    assert not AwayPeriod.objects.filter(pk=away.pk).exists()


def test_cancelling_is_post_only(as_roommate, roommate):
    away = AwayPeriod.objects.create(member=roommate, start_date=TODAY, end_date=TODAY)
    assert as_roommate.get(reverse("away_delete", args=[away.pk])).status_code == 405


def test_another_households_absence_is_invisible_and_unreachable(as_roommate):
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )
    theirs = AwayPeriod.objects.create(
        member=outsider, start_date=TODAY, end_date=TODAY, reason="Their trip"
    )

    body = as_roommate.get(reverse("away_list")).content.decode()
    assert "Outsider" not in body
    assert "Their trip" not in body

    assert as_roommate.post(reverse("away_delete", args=[theirs.pk])).status_code == 404
    assert AwayPeriod.objects.filter(pk=theirs.pk).exists()


def test_an_admin_cannot_declare_an_absence_for_another_household(as_admin):
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )

    response = as_admin.post(reverse("away_list"), form_data(outsider))

    assert response.status_code == 200
    assert not AwayPeriod.objects.filter(member=outsider).exists()


def test_the_away_page_requires_signing_in(client):
    response = client.get(reverse("away_list"))
    assert response.status_code == 302
    assert reverse("login") in response.url


def test_the_away_page_is_reachable_from_the_nav(as_roommate):
    body = as_roommate.get(reverse("dashboard")).content.decode()
    assert reverse("away_list") in body
