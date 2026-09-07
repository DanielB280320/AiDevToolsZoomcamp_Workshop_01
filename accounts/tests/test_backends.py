"""plan.md §5: a roommate signs in with their display name and a PIN."""

from unittest.mock import patch

import pytest
from django.contrib.auth import authenticate
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError

from accounts.backends import PinBackend
from accounts.models import Member
from accounts.validators import validate_pin
from conftest import DEFAULT_PIN

pytestmark = pytest.mark.django_db


class TestCorrectPin:
    def test_signs_the_roommate_in(self, roommate):
        assert authenticate(None, display_name="Ana", pin=DEFAULT_PIN) is not None

    def test_returns_the_right_member(self, members):
        assert authenticate(None, display_name="Ben", pin=DEFAULT_PIN) == members[1]

    def test_name_matching_ignores_case_and_padding(self, roommate):
        assert authenticate(None, display_name="  aNa  ", pin=DEFAULT_PIN) is not None


class TestRejection:
    """Every failure returns None. The form's wording is task 5's concern; what
    matters here is that nothing but the right name and PIN gets in."""

    def test_wrong_pin(self, roommate):
        assert authenticate(None, display_name="Ana", pin="000000") is None

    def test_unknown_name(self, members):
        assert authenticate(None, display_name="Nobody", pin=DEFAULT_PIN) is None

    def test_empty_pin(self, roommate):
        assert authenticate(None, display_name="Ana", pin="") is None

    def test_empty_name(self, roommate):
        assert authenticate(None, display_name="", pin=DEFAULT_PIN) is None

    def test_deactivated_member_cannot_sign_in(self, members):
        departed = members[-1]
        departed.is_active = False
        departed.save()
        assert (
            authenticate(None, display_name=departed.display_name, pin=DEFAULT_PIN)
            is None
        )

    def test_another_roommates_pin_does_not_work(self, members):
        members[1].set_pin("135791")
        members[1].save()
        assert authenticate(None, display_name="Ana", pin="135791") is None

    def test_operator_with_no_household_cannot_sign_in(self):
        """Task 4, criterion 7. Member.household's own help text: "Left empty
        only for an operator superuser, who administers the deployment
        rather than living in it" -- this task's Goal is "a roommate
        identifies themself," and an operator explicitly is not one."""
        operator = Member.objects.create_superuser(
            display_name="OpRoot", password="an-operator-password-123"
        )
        assert operator.household is None
        assert (
            authenticate(None, display_name="OpRoot", pin="an-operator-password-123")
            is None
        )

    def test_operator_keeps_admin_access_via_model_backend(self):
        """The fix above must not lock the operator out of /admin/:
        ModelBackend (second in AUTHENTICATION_BACKENDS) authenticates the
        same account independently via username=/password=, unaffected by
        PinBackend's household check."""
        operator = Member.objects.create_superuser(
            display_name="OpRoot", password="an-operator-password-123"
        )
        assert (
            ModelBackend().authenticate(
                None, username="OpRoot", password="an-operator-password-123"
            )
            == operator
        )


def test_authenticate_dispatch_falls_through_from_pinbackend_to_modelbackend():
    """QA gap on task 4's first pass: the tests above prove PinBackend
    declines a household-less account, and separately that ModelBackend
    accepts the same credentials in isolation -- neither proves the actual
    entry point /admin/'s login view uses, the top-level
    django.contrib.auth.authenticate() dispatcher, genuinely falls through
    from one configured backend to the next for the same call.

    This calls only that dispatcher, with the username=/password= kwargs
    the admin login form sends, against an operator PinBackend must decline
    (no household) and only ModelBackend (second in AUTHENTICATION_BACKENDS,
    config/settings/base.py) can accept -- so this can only pass if the
    fall-through genuinely happens.
    """
    operator = Member.objects.create_superuser(
        display_name="DispatchOp", password="an-operator-password-123"
    )
    # Sanity check the premise: PinBackend alone declines this account.
    assert (
        PinBackend().authenticate(
            None, username="DispatchOp", password="an-operator-password-123"
        )
        is None
    )
    # The real entry point still succeeds, by falling through to ModelBackend.
    assert (
        authenticate(None, username="DispatchOp", password="an-operator-password-123")
        == operator
    )


def test_unknown_name_still_hashes(members):
    """An early return for an unknown name would make the response measurably
    faster than for a known one, which is enough to enumerate the household.
    Both branches end in the same shape of work."""
    assert (
        PinBackend().authenticate(None, display_name="Ghost", pin=DEFAULT_PIN) is None
    )


def test_unknown_name_actually_hashes(members):
    """Not just a comment claiming the unknown-name branch hashes -- proves
    it, so a timing or logging observer cannot use response cost to
    enumerate real names."""
    with patch(
        "django.contrib.auth.base_user.AbstractBaseUser.set_password",
        autospec=True,
    ) as mocked:
        authenticate(None, display_name="NoSuchPerson", pin="000000")
        assert mocked.call_count == 1


class TestPinValidation:
    """architecture.md §6: six digits minimum is what keeps plan.md §5 defensible."""

    @pytest.mark.parametrize("bad", ["12345", "1234", "", "9"])
    def test_short_pins_rejected(self, bad):
        with pytest.raises(ValidationError):
            validate_pin(bad)

    @pytest.mark.parametrize("bad", ["abcdef", "12345a", "12 456", "123-456"])
    def test_non_numeric_pins_rejected(self, bad):
        with pytest.raises(ValidationError):
            validate_pin(bad)

    @pytest.mark.parametrize("good", ["918273", "1234567", "000000"])
    def test_six_or_more_digits_accepted(self, good):
        validate_pin(good)


class TestValidatePinNeverLeaksTheRawPin:
    """Task 4, criterion 9's grep for logger./print( calls would not catch a
    PIN embedded in a raised exception's own message. validate_pin's three
    ValidationErrors don't interpolate the raw value today, but nothing
    stops someone adding params={"value": value} later, the way
    validate_timezone (right above it in accounts/validators.py) already
    does for its own argument.

    Each PIN below is deliberately distinctive -- not a substring of the
    static wording, which itself interpolates PIN_MIN_LENGTH (6) and
    PIN_MAX_LENGTH (12) -- so this can only pass by coincidence if the raw
    PIN genuinely never appears in the message text, and fails immediately
    if a future change starts echoing it back (verified by temporarily
    reproducing that regression by hand: params={"value": value} in the
    "not digits only" branch makes this exact assertion fail).
    """

    @pytest.mark.parametrize(
        "bad_pin",
        [
            "ZzMarkerNotDigits",  # not-digits-only branch
            "24681",  # too-short branch
            "888888888888888",  # too-long branch
        ],
    )
    def test_rejected_pin_does_not_appear_in_the_error_message(self, bad_pin):
        with pytest.raises(ValidationError) as excinfo:
            validate_pin(bad_pin)
        message = " ".join(excinfo.value.messages)
        assert bad_pin not in message


class TestSixDigitMinimumEnforcedEverywhere:
    """Task 4, criterion 6: validate_pin was only wired into the form
    classes; any code setting a PIN directly through the model layer --
    a shell, a future management command such as #22's bootstrap -- must
    be caught too, not just the forms in accounts/forms.py."""

    def test_set_pin_rejects_a_short_pin(self, roommate):
        with pytest.raises(ValidationError):
            roommate.set_pin("1")

    def test_set_pin_leaves_the_existing_hash_untouched_on_rejection(self, roommate):
        original_password = roommate.password
        with pytest.raises(ValidationError):
            roommate.set_pin("1")
        assert roommate.password == original_password

    def test_create_user_rejects_a_short_pin(self, household):
        with pytest.raises(ValidationError):
            Member.objects.create_user(
                display_name="Shorty", password="1", household=household
            )
        assert not Member.objects.filter(display_name="Shorty").exists()

    def test_create_user_rejects_a_non_numeric_pin(self, household):
        with pytest.raises(ValidationError):
            Member.objects.create_user(
                display_name="Wordy", password="abcdef", household=household
            )

    def test_create_superuser_is_not_bound_by_the_roommate_pin_shape(self):
        """Deliberately exempt: this credential signs the operator into
        /admin/ via ModelBackend, typed once by whoever runs the deployment
        -- not a PIN read off a shared household touchscreen. Restricting it
        to six numeric digits would weaken, not strengthen, that account.
        The roommate-facing risk (a short PIN reachable through
        PinBackend) is independently closed by criterion 7: a member with no
        household can never authenticate through PinBackend regardless of
        its password's shape."""
        operator = Member.objects.create_superuser(
            display_name="RootAdmin", password="Not-Digits-Only!"
        )
        assert operator.check_password("Not-Digits-Only!")


class TestCreateSuperuserCannotBeGivenAHousehold:
    """QA's second-round finding on task 4: create_superuser's PIN-policy
    exemption is only safe if the account it creates is genuinely
    unreachable through PinBackend, which gates on household_id is not
    None. The manager used to forward **extra_fields unfiltered, so
    create_superuser(..., household=some_household) produced an
    admin-privileged, household-scoped "roommate" with a one-character,
    unvalidated PIN, fully reachable through PinBackend -- indistinguishable
    from a compliant roommate admin. Both directions of the fix are covered
    here: the manager refuses to create such a row at all, and (as a
    second, independent line of defense) an operator account it does create
    is confirmed to stay locked out of PinBackend even carrying a
    policy-violating credential.
    """

    def test_household_kwarg_is_rejected(self, household):
        with pytest.raises(ValueError):
            Member.objects.create_superuser(
                display_name="SneakyOp", password="x", household=household
            )
        assert not Member.objects.filter(display_name="SneakyOp").exists()

    def test_household_id_kwarg_is_rejected(self, household):
        with pytest.raises(ValueError):
            Member.objects.create_superuser(
                display_name="SneakyOp2", password="x", household_id=household.pk
            )
        assert not Member.objects.filter(display_name="SneakyOp2").exists()

    def test_household_is_none_is_accepted(self, household):
        """Passing the field's own default explicitly must not be treated
        as an attempt to set a household."""
        operator = Member.objects.create_superuser(
            display_name="ExplicitNoneOp", password="whatever-shape", household=None
        )
        assert operator.household is None

    def test_created_operator_always_has_no_household(self):
        operator = Member.objects.create_superuser(
            display_name="PlainOp", password="whatever-shape-this-is"
        )
        assert operator.household is None

    def test_operator_with_a_short_pin_still_cannot_sign_in_via_pinbackend(self):
        """The other direction: even though create_superuser lets a
        non-numeric, one-character-shape credential through (by design),
        confirm end-to-end that PinBackend still cannot be tricked into
        authenticating that account -- the household=None invariant this
        class enforces is what the exemption actually depends on."""
        Member.objects.create_superuser(display_name="ShortCredOp", password="x")
        assert (
            PinBackend().authenticate(None, display_name="ShortCredOp", pin="x") is None
        )
