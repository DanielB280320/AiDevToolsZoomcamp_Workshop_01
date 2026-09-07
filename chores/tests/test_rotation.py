"""Each chore cycles through the roommates in its own order (task 10).

plan.md §2 is explicit that the rotation belongs to the chore: the bins rota
and the bathroom rota should be able to run through people differently. The
order is stored and reorderable, never derived from join date or name.
"""

import pytest
from django.db.utils import IntegrityError
from django.urls import reverse

from accounts.models import Household, Member
from chores.models import Chore, RotationSlot

pytestmark = pytest.mark.django_db


@pytest.fixture
def bins(household, today):
    return Chore.objects.create(household=household, name="Bins", anchor_date=today)


@pytest.fixture
def bathroom(household, today):
    return Chore.objects.create(household=household, name="Bathroom", anchor_date=today)


@pytest.fixture
def as_admin(client, admin_member):
    client.force_login(admin_member)
    return client


@pytest.fixture
def as_roommate(client, roommate):
    client.force_login(roommate)
    return client


def post_data(order):
    """Positions for an ordered list of members; everyone else left blank."""
    return {f"position_{m.pk}": str(i) for i, m in enumerate(order)}


# Criterion 1 — a slot is (chore, member, position), read back in order.


def test_a_slot_stores_chore_member_and_position(bins, members):
    slot = RotationSlot.objects.create(chore=bins, member=members[0], position=0)
    slot.refresh_from_db()
    assert slot.chore == bins
    assert slot.member == members[0]
    assert slot.position == 0


def test_rotation_reads_back_in_position_order_not_insertion_order(bins, members):
    RotationSlot.objects.create(chore=bins, member=members[2], position=2)
    RotationSlot.objects.create(chore=bins, member=members[0], position=0)
    RotationSlot.objects.create(chore=bins, member=members[1], position=1)

    assert bins.rotation == [members[0], members[1], members[2]]


def test_a_chore_with_no_rotation_has_an_empty_one(bins):
    assert bins.rotation == []


def test_set_rotation_writes_dense_positions_from_zero(bins, members):
    bins.set_rotation([members[3], members[1], members[4]])

    slots = list(bins.rotation_slots.all())
    assert [s.position for s in slots] == [0, 1, 2]
    assert [s.member for s in slots] == [members[3], members[1], members[4]]


def test_set_rotation_replaces_rather_than_appends(bins, members):
    bins.set_rotation([members[0], members[1]])
    bins.set_rotation([members[2]])

    assert bins.rotation == [members[2]]
    assert bins.rotation_slots.count() == 1


def test_set_rotation_to_nothing_empties_it(bins, members):
    bins.set_rotation([members[0]])
    bins.set_rotation([])
    assert bins.rotation == []


# Criterion 2 — the whole point: two chores, same people, different orders.


def test_two_chores_run_through_the_same_people_in_different_orders(
    bins, bathroom, members
):
    bins.set_rotation([members[0], members[1], members[2]])
    bathroom.set_rotation([members[2], members[0], members[1]])

    assert bins.rotation == [members[0], members[1], members[2]]
    assert bathroom.rotation == [members[2], members[0], members[1]]


def test_two_chores_may_have_rotations_of_different_lengths(bins, bathroom, members):
    bins.set_rotation(members)
    bathroom.set_rotation([members[0], members[1]])

    assert len(bins.rotation) == 5
    assert len(bathroom.rotation) == 2


def test_changing_one_chores_rotation_leaves_the_other_alone(bins, bathroom, members):
    bins.set_rotation([members[0], members[1]])
    bathroom.set_rotation([members[0], members[1]])

    bins.set_rotation([members[1], members[0]])

    assert bathroom.rotation == [members[0], members[1]]


# Criterion 3 — the database refuses a duplicate member or a duplicate position.


def test_a_member_cannot_hold_two_slots_in_one_chore(bins, members):
    RotationSlot.objects.create(chore=bins, member=members[0], position=0)
    with pytest.raises(IntegrityError):
        RotationSlot.objects.create(chore=bins, member=members[0], position=1)


def test_two_members_cannot_share_a_position_in_one_chore(bins, members):
    RotationSlot.objects.create(chore=bins, member=members[0], position=0)
    with pytest.raises(IntegrityError):
        RotationSlot.objects.create(chore=bins, member=members[1], position=0)


def test_the_same_member_may_hold_position_zero_in_two_different_chores(
    bins, bathroom, members
):
    RotationSlot.objects.create(chore=bins, member=members[0], position=0)
    RotationSlot.objects.create(chore=bathroom, member=members[0], position=0)
    assert RotationSlot.objects.filter(member=members[0]).count() == 2


def test_the_order_is_not_alphabetical_or_by_join_date(bins, members):
    """Explicitly stored, so it can contradict both."""
    reversed_names = list(reversed(members))
    bins.set_rotation(reversed_names)

    names = [m.display_name for m in bins.rotation]
    assert names == ["Elif", "Dev", "Cleo", "Ben", "Ana"]
    assert names != sorted(names)


# Criterion 4 — an admin sets and reorders the rotation through the screen.


def test_admin_sets_a_rotation_through_the_screen(as_admin, bins, members):
    order = [members[2], members[0], members[4]]
    response = as_admin.post(
        reverse("chore_rotation", args=[bins.pk]), post_data(order), follow=True
    )

    assert response.status_code == 200
    assert bins.rotation == order


def test_admin_reorders_an_existing_rotation(as_admin, bins, members):
    bins.set_rotation([members[0], members[1], members[2]])

    as_admin.post(
        reverse("chore_rotation", args=[bins.pk]),
        post_data([members[2], members[1], members[0]]),
    )

    assert bins.rotation == [members[2], members[1], members[0]]


def test_positions_need_not_be_contiguous_only_ordered(as_admin, bins, members):
    """10/20/30 is a valid way to say first/second/third."""
    as_admin.post(
        reverse("chore_rotation", args=[bins.pk]),
        {
            f"position_{members[1].pk}": "10",
            f"position_{members[3].pk}": "20",
            f"position_{members[0].pk}": "30",
        },
    )

    assert bins.rotation == [members[1], members[3], members[0]]
    assert [s.position for s in bins.rotation_slots.all()] == [0, 1, 2]


def test_a_blank_position_leaves_that_roommate_out(as_admin, bins, members):
    as_admin.post(
        reverse("chore_rotation", args=[bins.pk]), post_data([members[0], members[1]])
    )
    assert bins.rotation == [members[0], members[1]]
    assert members[2] not in bins.rotation


def test_two_roommates_at_the_same_position_is_refused_with_a_visible_error(
    as_admin, bins, members
):
    response = as_admin.post(
        reverse("chore_rotation", args=[bins.pk]),
        {f"position_{members[0].pk}": "1", f"position_{members[1].pk}": "1"},
    )

    assert response.status_code == 200
    assert "are both at position 1" in response.content.decode()
    assert bins.rotation == []


def test_a_rejected_rotation_leaves_the_previous_one_intact(as_admin, bins, members):
    bins.set_rotation([members[0], members[1]])

    as_admin.post(
        reverse("chore_rotation", args=[bins.pk]),
        {f"position_{members[2].pk}": "3", f"position_{members[3].pk}": "3"},
    )

    assert bins.rotation == [members[0], members[1]]


def test_the_form_is_prefilled_with_the_current_positions(as_admin, bins, members):
    bins.set_rotation([members[1], members[0]])

    form = as_admin.get(reverse("chore_rotation", args=[bins.pk])).context["form"]
    assert form.fields[f"position_{members[1].pk}"].initial == 0
    assert form.fields[f"position_{members[0].pk}"].initial == 1
    assert form.fields[f"position_{members[2].pk}"].initial is None


# Criterion 5 — everyone reads it; only an admin changes it.


def test_a_non_admin_can_see_the_rotation(as_roommate, bins, members):
    bins.set_rotation([members[0], members[1]])

    response = as_roommate.get(reverse("chore_rotation", args=[bins.pk]))
    assert response.status_code == 200
    assert response.context["can_edit"] is False
    assert "Ana" in response.content.decode()


def test_a_non_admin_sees_no_edit_form(as_roommate, bins, members):
    body = as_roommate.get(reverse("chore_rotation", args=[bins.pk])).content.decode()
    assert "Save rotation" not in body


def test_a_non_admin_posting_a_rotation_is_refused(as_roommate, bins, members):
    response = as_roommate.post(
        reverse("chore_rotation", args=[bins.pk]), post_data([members[0]])
    )
    assert response.status_code == 403
    assert bins.rotation == []


# Criterion 6 — only this household's active members are candidates.


def test_a_deactivated_roommate_is_not_offered_for_the_rotation(
    as_admin, bins, members
):
    members[3].is_active = False
    members[3].save(update_fields=["is_active"])

    form = as_admin.get(reverse("chore_rotation", args=[bins.pk])).context["form"]
    assert members[3] not in form.candidates
    assert f"position_{members[3].pk}" not in form.fields


def test_a_position_posted_for_a_deactivated_roommate_is_ignored(
    as_admin, bins, members
):
    members[3].is_active = False
    members[3].save(update_fields=["is_active"])

    as_admin.post(
        reverse("chore_rotation", args=[bins.pk]),
        {f"position_{members[0].pk}": "0", f"position_{members[3].pk}": "1"},
    )

    assert bins.rotation == [members[0]]


def test_another_households_member_is_never_a_candidate(as_admin, bins, members):
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )

    form = as_admin.get(reverse("chore_rotation", args=[bins.pk])).context["form"]
    assert outsider not in form.candidates

    as_admin.post(
        reverse("chore_rotation", args=[bins.pk]), {f"position_{outsider.pk}": "0"}
    )
    assert bins.rotation == []


def test_another_households_chore_rotation_is_not_reachable(as_admin, today):
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    theirs = Chore.objects.create(household=other, name="Their bins", anchor_date=today)
    assert as_admin.get(reverse("chore_rotation", args=[theirs.pk])).status_code == 404


def test_deleting_a_chore_takes_its_slots_but_not_its_members(bins, members):
    bins.set_rotation([members[0], members[1]])
    bins.delete()

    assert RotationSlot.objects.count() == 0
    assert Member.objects.filter(pk=members[0].pk).exists()
