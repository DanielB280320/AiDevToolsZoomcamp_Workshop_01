"""Only admins change the chore list; everyone reads it (task 9).

plan.md §7 rejected open editing: with 5+ roommates it invites accidental
deletions, or one person unilaterally changing everyone's workload. The task is
explicit that hiding the buttons is not the test — the URLs themselves have to
refuse.
"""

import pytest
from django.urls import reverse

from accounts.mixins import is_household_admin
from chores.models import Chore

pytestmark = pytest.mark.django_db


@pytest.fixture
def bins(household, today):
    return Chore.objects.create(household=household, name="Bins", anchor_date=today)


@pytest.fixture
def as_admin(client, admin_member):
    client.force_login(admin_member)
    return client


@pytest.fixture
def as_roommate(client, roommate):
    client.force_login(roommate)
    return client


def editing_urls(chore):
    return [
        ("get", reverse("chore_create")),
        ("get", reverse("chore_edit", args=[chore.pk])),
        ("post", reverse("chore_create")),
        ("post", reverse("chore_edit", args=[chore.pk])),
        ("post", reverse("chore_set_active", args=[chore.pk])),
    ]


# Criterion 1 — reading is open to the whole household.


@pytest.mark.parametrize("view", ["chore_list", "chore_detail"])
def test_any_roommate_can_read_the_chore_screens(as_roommate, bins, view):
    args = [bins.pk] if view == "chore_detail" else []
    assert as_roommate.get(reverse(view, args=args)).status_code == 200


def test_the_chore_list_is_reachable_from_the_nav_by_a_non_admin(as_roommate, bins):
    body = as_roommate.get(reverse("chore_list")).content.decode()
    assert reverse("chore_list") in body


# Criterion 2 — a non-admin is refused by the URL, with 403 not a redirect.


def test_non_admin_is_refused_on_every_editing_url(as_roommate, bins):
    for verb, url in editing_urls(bins):
        response = getattr(as_roommate, verb)(url, {"active": "0"})
        assert response.status_code == 403, f"{verb.upper()} {url} was not refused"


def test_refusal_is_403_and_not_a_bounce_to_sign_in(as_roommate, bins):
    """A signed-in non-admin has no business on the login page.

    A redirect would imply signing in again might help. It would not — this is
    a permissions failure, not a missing session.
    """
    response = as_roommate.get(reverse("chore_edit", args=[bins.pk]))
    assert response.status_code == 403
    assert not hasattr(response, "url")


def test_a_refused_post_changes_nothing(as_roommate, bins):
    as_roommate.post(reverse("chore_set_active", args=[bins.pk]), {"active": "0"})
    bins.refresh_from_db()
    assert bins.is_active is True


def test_a_refused_create_writes_no_row(as_roommate, household):
    as_roommate.post(
        reverse("chore_create"),
        {
            "name": "Snuck in",
            "description": "",
            "cadence_unit": "WEEK",
            "cadence_interval": 1,
            "anchor_date": "2026-01-05",
            "grace_days": 1,
        },
    )
    assert not Chore.objects.filter(name="Snuck in").exists()


# Criterion 3 — an admin gets through all three.


def test_admin_reaches_every_editing_url(as_admin, bins):
    assert as_admin.get(reverse("chore_create")).status_code == 200
    assert as_admin.get(reverse("chore_edit", args=[bins.pk])).status_code == 200
    assert (
        as_admin.post(
            reverse("chore_set_active", args=[bins.pk]), {"active": "0"}
        ).status_code
        == 302
    )


# Criterion 4 — the affordances follow the permission, but are not the guard.


def test_edit_affordances_are_hidden_from_a_non_admin(as_roommate, bins):
    listing = as_roommate.get(reverse("chore_list"))
    detail = as_roommate.get(reverse("chore_detail", args=[bins.pk]))

    assert listing.context["can_edit"] is False
    assert reverse("chore_create") not in listing.content.decode()
    assert reverse("chore_edit", args=[bins.pk]) not in detail.content.decode()


def test_edit_affordances_are_shown_to_an_admin(as_admin, bins):
    listing = as_admin.get(reverse("chore_list"))
    detail = as_admin.get(reverse("chore_detail", args=[bins.pk]))

    assert listing.context["can_edit"] is True
    assert reverse("chore_create") in listing.content.decode()
    assert reverse("chore_edit", args=[bins.pk]) in detail.content.decode()


# Criterion 5 — a departed roommate reaches nothing.


def test_a_deactivated_member_is_shut_out_of_reading_and_editing(
    client, admin_member, bins
):
    admin_member.is_active = False
    admin_member.save(update_fields=["is_active"])
    client.force_login(admin_member)

    # The session no longer resolves to an active user, so every chore screen
    # bounces to sign-in -- reading included, and admin rights are gone with it.
    for view, args in [("chore_list", []), ("chore_edit", [bins.pk])]:
        response = client.get(reverse(view, args=args))
        assert response.status_code == 302
        assert reverse("login") in response.url
    assert not is_household_admin(admin_member)


def test_an_anonymous_visitor_is_sent_to_sign_in(client, bins):
    response = client.get(reverse("chore_list"))
    assert response.status_code == 302
    assert reverse("login") in response.url


# Criterion 6 — one guard, shared by both apps.


def test_the_guard_is_the_same_helper_the_accounts_screens_use():
    import accounts.views
    import chores.views

    assert chores.views.admin_required is accounts.views.admin_required


@pytest.mark.parametrize(
    "flags,expected",
    [
        ({"is_admin": True, "is_active": True}, True),
        ({"is_admin": False, "is_active": True}, False),
        ({"is_admin": True, "is_active": False}, False),
    ],
)
def test_is_household_admin_requires_both_admin_and_active(roommate, flags, expected):
    for field, value in flags.items():
        setattr(roommate, field, value)
    assert is_household_admin(roommate) is expected


def test_django_superuser_flag_alone_does_not_grant_household_admin(roommate):
    """plan.md §7's role flag is distinct from Django's operator flag."""
    roommate.is_superuser = True
    roommate.is_admin = False
    assert is_household_admin(roommate) is False
