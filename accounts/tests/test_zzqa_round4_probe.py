"""QA round-4 throwaway probe file. Deleted after the run."""

import pytest
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client
from unittest.mock import patch

from accounts.models import Household, Member

pytestmark = pytest.mark.django_db


# --- criterion 5, verbatim from the issue -------------------------------
def test_unknown_name_actually_hashes(members):
    with patch(
        "django.contrib.auth.base_user.AbstractBaseUser.set_password",
        autospec=True,
    ) as mocked:
        authenticate(None, display_name="NoSuchPerson", pin="000000")
        assert mocked.call_count == 1


# --- criterion 6 already-closed regression ------------------------------
def test_create_superuser_household_kwarg_still_rejected():
    h = Household.objects.create(name="PinCheck")
    with pytest.raises(ValueError):
        Member.objects.create_superuser(display_name="SneakyOp", password="x", household=h)
    assert Member.objects.filter(display_name="SneakyOp").count() == 0
    print("\nC6-closed-door: OK rejected")


# --- bypass 1, verbatim -------------------------------------------------
def test_bypass1_verbatim():
    h, _ = Household.objects.get_or_create(name="PostHocCheck")
    su = Member.objects.create_superuser(display_name="PostHocOp", password="x")
    raised = None
    try:
        su.household = h
        su.save()
    except Exception as exc:  # noqa: BLE001
        raised = exc
    su.refresh_from_db()
    print("\nBYPASS1 raised:", type(raised).__name__ if raised else None)
    print("BYPASS1 household after save:", su.household)
    print("BYPASS1 authenticate result:", authenticate(None, display_name="PostHocOp", pin="x"))


# --- bypass 2, verbatim, with a real login ------------------------------
def test_bypass2_verbatim(client):
    h = Household.objects.create(name="AdminBypassHouse")
    Member.objects.create_superuser(display_name="AdminOp", password="whatever-op-pw")
    assert client.login(username="AdminOp", password="whatever-op-pw")
    raised = None
    try:
        resp = client.post(
            "/admin/accounts/member/add/",
            {
                "display_name": "AdminSneak",
                "household": h.pk,
                "password1": "Zq7!Xk2",
                "password2": "Zq7!Xk2",
            },
        )
        print("\nBYPASS2 status:", resp.status_code)
    except Exception as exc:  # noqa: BLE001
        raised = exc
        print("\nBYPASS2 propagated exception:", type(exc).__name__)
    print("BYPASS2 row created:", Member.objects.filter(display_name="AdminSneak").first())
    assert Member.objects.filter(display_name="AdminSneak").first() is None


def test_bypass2_what_the_operator_actually_sees():
    """Same POST, but with raise_request_exception=False so we observe the
    real HTTP response an operator's browser would receive."""
    c = Client(raise_request_exception=False)
    h = Household.objects.create(name="AdminBypassHouse2")
    Member.objects.create_superuser(display_name="AdminOp2", password="whatever-op-pw")
    assert c.login(username="AdminOp2", password="whatever-op-pw")
    resp = c.post(
        "/admin/accounts/member/add/",
        {
            "display_name": "AdminSneak2",
            "household": h.pk,
            "password1": "Zq7!Xk2",
            "password2": "Zq7!Xk2",
        },
    )
    print("\nADMIN-ADD-BAD-PIN status:", resp.status_code)
    body = resp.content.decode(errors="replace")
    print("ADMIN-ADD-BAD-PIN body length:", len(body))
    print("ADMIN-ADD-BAD-PIN body head:", body[:400].replace("\n", " "))
    print("ADMIN-ADD-BAD-PIN row:", Member.objects.filter(display_name="AdminSneak2").first())


def test_admin_add_with_a_GOOD_pin_still_works():
    c = Client(raise_request_exception=False)
    h = Household.objects.create(name="AdminGoodHouse")
    Member.objects.create_superuser(display_name="AdminOp3", password="whatever-op-pw")
    assert c.login(username="AdminOp3", password="whatever-op-pw")
    resp = c.post(
        "/admin/accounts/member/add/",
        {
            "display_name": "AdminGood",
            "household": h.pk,
            "password1": "123456",
            "password2": "123456",
        },
    )
    print("\nADMIN-ADD-GOOD-PIN status:", resp.status_code)
    print("ADMIN-ADD-GOOD-PIN row:", Member.objects.filter(display_name="AdminGood").first())


# --- save()-bypassing routes -------------------------------------------
def test_route_bulk_create(household):
    m = Member(display_name="BulkSneak", household=household)
    m.set_password("Zq7!Xk2")
    raised = None
    try:
        Member.objects.bulk_create([m])
    except Exception as exc:  # noqa: BLE001
        raised = exc
    row = Member.objects.filter(display_name="BulkSneak").first()
    print("\nBULK_CREATE raised:", type(raised).__name__ if raised else None)
    print("BULK_CREATE row:", row, "pin_is_validated:", getattr(row, "pin_is_validated", None))
    if row:
        print("BULK_CREATE check_password('Zq7!Xk2'):", row.check_password("Zq7!Xk2"))
        print("BULK_CREATE authenticate:", authenticate(None, display_name="BulkSneak", pin="Zq7!Xk2"))


def test_route_queryset_update_password(household):
    m = Member.objects.create_user(display_name="QsPw", password="123456", household=household)
    scratch = Member(display_name="scratch")
    scratch.set_password("Zq7!Xk2")
    n = Member.objects.filter(pk=m.pk).update(password=scratch.password)
    row = Member.objects.get(pk=m.pk)
    print("\nQS_UPDATE_PASSWORD rows updated:", n)
    print("QS_UPDATE_PASSWORD pin_is_validated:", row.pin_is_validated)
    print("QS_UPDATE_PASSWORD check_password('Zq7!Xk2'):", row.check_password("Zq7!Xk2"))
    print("QS_UPDATE_PASSWORD authenticate:", authenticate(None, display_name="QsPw", pin="Zq7!Xk2"))


def test_route_queryset_update_household(household):
    su = Member.objects.create_superuser(display_name="QsHouse", password="x")
    n = Member.objects.filter(pk=su.pk).update(household=household)
    row = Member.objects.get(pk=su.pk)
    print("\nQS_UPDATE_HOUSEHOLD rows updated:", n)
    print("QS_UPDATE_HOUSEHOLD household:", row.household, "pin_is_validated:", row.pin_is_validated)
    print("QS_UPDATE_HOUSEHOLD check_password('x'):", row.check_password("x"))
    print("QS_UPDATE_HOUSEHOLD authenticate:", authenticate(None, display_name="QsHouse", pin="x"))


def test_route_raw_sql(household):
    su = Member.objects.create_superuser(display_name="RawSql", password="x")
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE accounts_member SET household_id = %s WHERE id = %s",
            [household.pk, su.pk],
        )
    row = Member.objects.get(pk=su.pk)
    print("\nRAW_SQL household:", row.household, "pin_is_validated:", row.pin_is_validated)
    print("RAW_SQL authenticate:", authenticate(None, display_name="RawSql", pin="x"))


def test_route_queryset_update_both_flag_and_household(household):
    """The nastiest QuerySet.update(): set household AND lie about the flag."""
    su = Member.objects.create_superuser(display_name="QsBoth", password="x")
    Member.objects.filter(pk=su.pk).update(household=household, pin_is_validated=True)
    row = Member.objects.get(pk=su.pk)
    print("\nQS_UPDATE_BOTH household:", row.household, "flag:", row.pin_is_validated)
    print("QS_UPDATE_BOTH authenticate:", authenticate(None, display_name="QsBoth", pin="x"))
    # and a later ordinary save is now happily allowed
    row.is_admin = True
    row.save()
    print("QS_UPDATE_BOTH later save OK, household still:", Member.objects.get(pk=su.pk).household)


# --- nothing legitimate broke ------------------------------------------
def test_create_user_still_works(household):
    m = Member.objects.create_user(display_name="LegitUser", password="654321", household=household)
    print("\nCREATE_USER ok:", m, m.pin_is_validated, authenticate(None, display_name="LegitUser", pin="654321"))


def test_memberform_save_still_works(household):
    from accounts.forms import MemberForm

    f = MemberForm({"display_name": "FormUser", "is_admin": False}, household=household)
    assert f.is_valid(), f.errors
    m = f.save()
    print("\nMEMBERFORM: form rejects bad pin?", MemberForm({"display_name": "X", "is_admin": False, "pin": "abc"}, household=household).is_valid())
    print("MEMBERFORM saved:", m, m.pin_is_validated)


def test_member_reset_pin_view_end_to_end(client, household, members):
    admin = members[0]
    target = members[1]
    admin.is_admin = True
    admin.save(update_fields=["is_admin"])
    assert client.login(username=admin.display_name, password="918273")
    resp = client.post(f"/members/{target.pk}/reset-pin/", {"pin": "778899", "pin_confirm": "778899"})
    print("\nRESET_PIN status:", resp.status_code)
    row = Member.objects.get(pk=target.pk)
    print("RESET_PIN flag:", row.pin_is_validated, "check:", row.check_pin("778899"))
    print("RESET_PIN authenticate:", authenticate(None, display_name=target.display_name, pin="778899"))


def test_admin_edit_existing_member(household):
    c = Client(raise_request_exception=False)
    Member.objects.create_superuser(display_name="EditOp", password="whatever-op-pw")
    m = Member.objects.create_user(display_name="EditMe", password="123456", household=household)
    assert c.login(username="EditOp", password="whatever-op-pw")
    get = c.get(f"/admin/accounts/member/{m.pk}/change/")
    print("\nADMIN_EDIT get status:", get.status_code)
    resp = c.post(
        f"/admin/accounts/member/{m.pk}/change/",
        {
            "display_name": "EditMeRenamed",
            "household": household.pk,
            "joined_on": m.joined_on.isoformat(),
            "is_admin": "on",
            "is_active": "on",
            "last_login": "",
        },
    )
    print("ADMIN_EDIT post status:", resp.status_code)
    row = Member.objects.get(pk=m.pk)
    print("ADMIN_EDIT name now:", row.display_name, "flag:", row.pin_is_validated, "check 123456:", row.check_pin("123456"))


def test_admin_password_change_form_on_a_roommate(household):
    """Django's own /admin/.../password/ screen calls set_password()."""
    c = Client(raise_request_exception=False)
    Member.objects.create_superuser(display_name="PwOp", password="whatever-op-pw")
    m = Member.objects.create_user(display_name="PwMe", password="123456", household=household)
    assert c.login(username="PwOp", password="whatever-op-pw")
    resp = c.post(
        f"/admin/accounts/member/{m.pk}/password/",
        {"password1": "654321", "password2": "654321"},
    )
    print("\nADMIN_PWCHANGE status:", resp.status_code)
    row = Member.objects.get(pk=m.pk)
    print("ADMIN_PWCHANGE flag:", row.pin_is_validated, "check 654321:", row.check_pin("654321"), "check 123456:", row.check_pin("123456"))


# --- criteria 7, 8, 9 ---------------------------------------------------
def test_criterion7_operator_cannot_pin_sign_in():
    su = Member.objects.create_superuser(display_name="OpRoot", password="rootpin123")
    print("\nC7 household:", su.household)
    print("C7 authenticate result:", authenticate(None, display_name="OpRoot", pin="rootpin123"))


def test_criterion7b_operator_reaches_admin():
    from django.contrib.auth.backends import ModelBackend

    Member.objects.create_superuser(display_name="OpAdmin", password="rootpin123")
    print("\nC7b ModelBackend:", ModelBackend().authenticate(None, username="OpAdmin", password="rootpin123"))
    print("C7b dispatcher:", authenticate(None, username="OpAdmin", password="rootpin123"))
    c = Client()
    print("C7b client.login:", c.login(username="OpAdmin", password="rootpin123"))
    print("C7b /admin/ status:", c.get("/admin/").status_code)


def test_criterion8_username_password_kwargs():
    h, _ = Household.objects.get_or_create(name="KwargCheck")
    Member.objects.filter(household=h).delete()
    Member.objects.create_user(display_name="Kwarg", password="246813", household=h)
    print("\nC8:", authenticate(None, username="Kwarg", password="246813"))
