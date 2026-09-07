"""Creating, editing and archiving a chore through the browser (task 8).

Task 8 covers the screens themselves. Whether a *non*-admin is refused is
task 9's criterion, and is tested there.
"""

import datetime as dt

import pytest
from django.urls import reverse

from chores.models import Cadence, Chore

pytestmark = pytest.mark.django_db


@pytest.fixture
def as_admin(client, admin_member):
    client.force_login(admin_member)
    return client


@pytest.fixture
def bins(household, today):
    return Chore.objects.create(
        household=household,
        name="Bins",
        description="Kerb by 7am.",
        cadence_unit=Cadence.WEEK,
        cadence_interval=1,
        anchor_date=today,
    )


def form_data(**overrides):
    data = {
        "name": "Bathroom",
        "description": "Sink, mirror, floor.",
        "cadence_unit": Cadence.WEEK,
        "cadence_interval": 2,
        "anchor_date": "2026-01-05",
        "grace_days": 1,
    }
    data.update(overrides)
    return data


# Criterion 3 — an admin creates a chore and it shows up.


def test_admin_creates_a_chore_and_it_appears_in_the_list(as_admin, household):
    response = as_admin.post(reverse("chore_create"), form_data(), follow=True)
    assert response.status_code == 200

    chore = Chore.objects.get(household=household, name="Bathroom")
    assert chore.cadence_unit == Cadence.WEEK
    assert chore.cadence_interval == 2
    assert chore.anchor_date == dt.date(2026, 1, 5)
    assert chore.is_active is True

    listing = as_admin.get(reverse("chore_list"))
    assert "Bathroom" in listing.content.decode()


def test_a_new_chore_lands_in_the_creators_own_household(as_admin, household):
    """The household comes from the session, never from the submitted form."""
    as_admin.post(reverse("chore_create"), form_data())
    assert Chore.objects.get(name="Bathroom").household_id == household.pk


def test_two_chores_created_through_the_form_keep_separate_cadences(
    as_admin, household
):
    as_admin.post(reverse("chore_create"), form_data(name="Bathroom"))
    as_admin.post(
        reverse("chore_create"),
        form_data(name="Oven", cadence_unit=Cadence.MONTH, cadence_interval=1),
    )

    bathroom = Chore.objects.get(name="Bathroom")
    oven = Chore.objects.get(name="Oven")
    assert bathroom.cadence_label == "Every 2 weeks"
    assert oven.cadence_label == "Monthly"


def test_a_duplicate_name_is_refused_with_a_visible_error(as_admin, bins):
    response = as_admin.post(reverse("chore_create"), form_data(name="bins"))

    assert response.status_code == 200
    assert "already a chore with that name" in response.content.decode()
    assert Chore.objects.filter(name__iexact="bins").count() == 1


def test_an_interval_below_one_is_refused(as_admin):
    response = as_admin.post(reverse("chore_create"), form_data(cadence_interval=0))
    assert response.status_code == 200
    assert not Chore.objects.filter(name="Bathroom").exists()


# Criterion 4 — an admin edits an existing chore.


def test_admin_edits_a_chores_name_and_cadence(as_admin, bins):
    response = as_admin.post(
        reverse("chore_edit", args=[bins.pk]),
        form_data(
            name="Bins and recycling",
            cadence_unit=Cadence.MONTH,
            cadence_interval=1,
        ),
        follow=True,
    )
    assert response.status_code == 200

    bins.refresh_from_db()
    assert bins.name == "Bins and recycling"
    assert bins.cadence_unit == Cadence.MONTH
    assert bins.cadence_interval == 1
    # Edited in place, not replaced.
    assert Chore.objects.count() == 1


def test_editing_a_chore_keeps_its_own_name_available(as_admin, bins):
    """The uniqueness check must exclude the row being edited."""
    response = as_admin.post(
        reverse("chore_edit", args=[bins.pk]),
        form_data(name="Bins", description="Kerb by 7am Tuesday."),
        follow=True,
    )
    bins.refresh_from_db()
    assert response.status_code == 200
    assert bins.description == "Kerb by 7am Tuesday."


def test_the_edit_form_is_prefilled_with_the_current_values(as_admin, bins):
    body = as_admin.get(reverse("chore_edit", args=[bins.pk])).content.decode()
    assert 'value="Bins"' in body
    assert 'value="2026-01-05"' in body


def test_a_chore_from_another_household_is_not_reachable(as_admin, today):
    from accounts.models import Household

    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    theirs = Chore.objects.create(household=other, name="Their bins", anchor_date=today)

    assert as_admin.get(reverse("chore_detail", args=[theirs.pk])).status_code == 404
    assert as_admin.get(reverse("chore_edit", args=[theirs.pk])).status_code == 404


# Criterion 5 — archiving through the screen keeps the row.


def test_archiving_through_the_screen_keeps_the_row(as_admin, bins):
    as_admin.post(reverse("chore_set_active", args=[bins.pk]), {"active": "0"})

    bins.refresh_from_db()
    assert bins.is_active is False
    assert Chore.objects.filter(pk=bins.pk).exists()


def test_an_archived_chore_is_listed_separately_not_dropped(as_admin, bins):
    as_admin.post(reverse("chore_set_active", args=[bins.pk]), {"active": "0"})

    response = as_admin.get(reverse("chore_list"))
    assert list(response.context["chores"]) == []
    assert list(response.context["archived"]) == [bins]
    assert "Bins" in response.content.decode()


def test_an_archived_chore_can_be_brought_back(as_admin, bins):
    url = reverse("chore_set_active", args=[bins.pk])
    as_admin.post(url, {"active": "0"})
    as_admin.post(url, {"active": "1"})

    bins.refresh_from_db()
    assert bins.is_active is True


def test_archiving_is_post_only(as_admin, bins):
    assert as_admin.get(reverse("chore_set_active", args=[bins.pk])).status_code == 405


# Every roommate can read the list — plan.md §7 restricts editing, not seeing.


def test_a_non_admin_can_still_read_the_chore_list(client, roommate, bins):
    client.force_login(roommate)
    response = client.get(reverse("chore_list"))
    assert response.status_code == 200
    assert "Bins" in response.content.decode()
    assert response.context["can_edit"] is False
