import zoneinfo

from django.core.exceptions import ValidationError


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
