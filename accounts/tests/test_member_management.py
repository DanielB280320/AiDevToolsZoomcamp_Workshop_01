"""plan.md §1 and §7: an admin keeps the roommate list current."""

import pytest
from django.urls import reverse

from accounts.models import Household, Member
from conftest import DEFAULT_PIN

pytestmark = pytest.mark.django_db


@pytest.fixture
def as_admin(client, admin_member):
    client.force_login(admin_member)
    return client


@pytest.fixture
def as_roommate(client, roommate):
    client.force_login(roommate)
    return client


class TestOnlyAdminsGetIn:
    """plan.md §7 rejected open editing. Hiding the buttons is not enough —
    the URLs themselves have to refuse."""

    @pytest.mark.parametrize(
        "name,args",
        [
            ("member_list", ()),
            ("member_add", ()),
            ("member_reset_pin", (1,)),
        ],
    )
    def test_non_admin_is_refused(self, as_roommate, members, name, args):
        args = (members[2].pk,) if args else ()
        assert as_roommate.get(reverse(name, args=args)).status_code == 403

    @pytest.mark.parametrize("name", ["member_toggle_admin", "member_set_active"])
    def test_non_admin_cannot_post(self, as_roommate, members, name):
        url = reverse(name, args=(members[2].pk,))
        assert as_roommate.post(url, {"active": "0"}).status_code == 403

    def test_admin_gets_in(self, as_admin):
        assert as_admin.get(reverse("member_list")).status_code == 200

    def test_signed_out_is_bounced_to_login(self, client):
        response = client.get(reverse("member_list"))
        assert response.status_code == 302
        assert reverse("login") in response.url


class TestAddingARoommate:
    def test_admin_adds_one(self, as_admin, household):
        response = as_admin.post(
            reverse("member_add"),
            {"display_name": "Frank", "pin": "246813", "pin_confirm": "246813"},
        )
        assert response.status_code == 302
        frank = Member.objects.get(display_name="Frank")
        assert frank.household == household
        assert frank.is_active and not frank.is_admin

    def test_the_new_roommate_can_sign_in(self, as_admin, client):
        as_admin.post(reverse("member_add"), {"display_name": "Frank", "pin": "246813"})
        assert client.login(display_name="Frank", pin="246813")

    def test_short_pin_is_rejected(self, as_admin):
        as_admin.post(reverse("member_add"), {"display_name": "Frank", "pin": "12"})
        assert not Member.objects.filter(display_name="Frank").exists()

    def test_household_size_is_not_capped(self, as_admin, household):
        """plan.md §1: nothing may hardcode a household size."""
        for i in range(6):
            as_admin.post(
                reverse("member_add"),
                {"display_name": f"Extra{i}", "pin": "246813"},
            )
        assert household.member_count == 11


class TestResettingAPin:
    """plan.md §5 has no email, so recovery cannot be self-service."""

    def test_admin_sets_a_new_pin(self, as_admin, client, members):
        target = members[2]
        as_admin.post(
            reverse("member_reset_pin", args=(target.pk,)),
            {"pin": "555444", "pin_confirm": "555444"},
        )
        target.refresh_from_db()
        assert target.check_pin("555444")
        assert not target.check_pin(DEFAULT_PIN)

    def test_mismatched_confirmation_is_rejected(self, as_admin, members):
        target = members[2]
        as_admin.post(
            reverse("member_reset_pin", args=(target.pk,)),
            {"pin": "555444", "pin_confirm": "555999"},
        )
        target.refresh_from_db()
        assert target.check_pin(DEFAULT_PIN)


class TestMovingOut:
    def test_deactivating_is_a_flag_not_a_delete(self, as_admin, members):
        target = members[3]
        as_admin.post(reverse("member_set_active", args=(target.pk,)), {"active": "0"})
        target.refresh_from_db()
        assert not target.is_active
        assert Member.objects.filter(pk=target.pk).exists()

    def test_a_departed_roommate_cannot_sign_in(self, as_admin, client, members):
        target = members[3]
        as_admin.post(reverse("member_set_active", args=(target.pk,)), {"active": "0"})
        assert not client.login(display_name=target.display_name, pin=DEFAULT_PIN)

    def test_they_can_move_back_in(self, as_admin, members):
        target = members[3]
        url = reverse("member_set_active", args=(target.pk,))
        as_admin.post(url, {"active": "0"})
        as_admin.post(url, {"active": "1"})
        target.refresh_from_db()
        assert target.is_active


class TestAdminRole:
    def test_admin_can_promote_someone(self, as_admin, members):
        target = members[2]
        as_admin.post(reverse("member_toggle_admin", args=(target.pk,)))
        target.refresh_from_db()
        assert target.is_admin

    def test_admin_can_demote_someone(self, as_admin, members):
        target = members[2]
        target.is_admin = True
        target.save()
        as_admin.post(reverse("member_toggle_admin", args=(target.pk,)))
        target.refresh_from_db()
        assert not target.is_admin

    def test_the_last_admin_cannot_be_demoted(self, as_admin, admin_member):
        """A household with no admin can never add a chore or reset a PIN
        again without someone reaching the database directly."""
        as_admin.post(reverse("member_toggle_admin", args=(admin_member.pk,)))
        admin_member.refresh_from_db()
        assert admin_member.is_admin

    def test_the_last_admin_cannot_be_deactivated(self, as_admin, admin_member):
        as_admin.post(
            reverse("member_set_active", args=(admin_member.pk,)), {"active": "0"}
        )
        admin_member.refresh_from_db()
        assert admin_member.is_active

    def test_a_second_admin_frees_the_first(self, as_admin, members, admin_member):
        other = members[2]
        as_admin.post(reverse("member_toggle_admin", args=(other.pk,)))
        as_admin.post(reverse("member_toggle_admin", args=(admin_member.pk,)))
        admin_member.refresh_from_db()
        assert not admin_member.is_admin


class TestHouseholdScoping:
    """architecture.md §6.3: never trust a PK from the URL."""

    def test_another_households_member_is_invisible(self, as_admin):
        other_house = Household.objects.create(name="Next Door")
        stranger = Member.objects.create_user(
            "Stranger", password=DEFAULT_PIN, household=other_house
        )

        assert (
            as_admin.get(reverse("member_reset_pin", args=(stranger.pk,))).status_code
            == 404
        )
        assert (
            as_admin.post(
                reverse("member_set_active", args=(stranger.pk,)), {"active": "0"}
            ).status_code
            == 404
        )
        stranger.refresh_from_db()
        assert stranger.is_active

    def test_the_list_shows_only_this_household(self, as_admin, members):
        other_house = Household.objects.create(name="Next Door")
        Member.objects.create_user(
            "Stranger", password=DEFAULT_PIN, household=other_house
        )
        body = as_admin.get(reverse("member_list")).content.decode()
        assert "Stranger" not in body
        assert "Ana" in body
