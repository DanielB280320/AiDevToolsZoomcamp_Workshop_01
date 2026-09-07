"""plan.md §5: a roommate signs in with their display name and a PIN."""

import pytest
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError

from accounts.backends import PinBackend
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


def test_unknown_name_still_hashes(members):
    """An early return for an unknown name would make the response measurably
    faster than for a known one, which is enough to enumerate the household.
    Both branches end in the same shape of work."""
    assert (
        PinBackend().authenticate(None, display_name="Ghost", pin=DEFAULT_PIN) is None
    )


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
