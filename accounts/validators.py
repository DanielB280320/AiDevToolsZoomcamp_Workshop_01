import re
import zoneinfo

from django.core.exceptions import ValidationError

# plan.md §5 traded password strength for daily convenience. architecture.md §6
# sets the floor that keeps that trade defensible: six digits is a million
# combinations rather than the ten thousand a four-digit PIN offers.
PIN_MIN_LENGTH = 6
PIN_MAX_LENGTH = 12

_DIGITS_ONLY = re.compile(r"^\d+$")


def validate_timezone(value):
    """Reject a timezone name the standard library cannot resolve.

    Due dates, grace periods and overdue checks are all evaluated in the
    household's local time, so an unresolvable name here would surface much
    later as wrong dates rather than as an error.
    """
    if value not in zoneinfo.available_timezones():
        raise ValidationError(
            "%(value)s is not a known timezone name (for example "
            "'Europe/Madrid' or 'America/New_York').",
            params={"value": value},
        )


def validate_pin(value):
    """A PIN is digits only, at least PIN_MIN_LENGTH of them."""
    value = value or ""
    if not _DIGITS_ONLY.match(value):
        raise ValidationError("Your PIN must be digits only.", code="pin_not_numeric")
    if len(value) < PIN_MIN_LENGTH:
        raise ValidationError(
            "Your PIN must be at least %(min)d digits.",
            code="pin_too_short",
            params={"min": PIN_MIN_LENGTH},
        )
    if len(value) > PIN_MAX_LENGTH:
        raise ValidationError(
            "Your PIN can be at most %(max)d digits.",
            code="pin_too_long",
            params={"max": PIN_MAX_LENGTH},
        )
