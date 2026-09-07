"""Permission guards shared by every admin-gated screen (architecture.md §6)."""

from functools import wraps

from django.core.exceptions import PermissionDenied


def is_household_admin(user):
    """plan.md §7's role flag. Distinct from Django's is_superuser."""
    return bool(
        user.is_authenticated and user.is_active and getattr(user, "is_admin", False)
    )


def admin_required(view):
    """Refuse non-admins with 403 rather than bouncing them to sign-in.

    plan.md §9 asks that the chore list be *viewable* by everyone, so a
    non-admin reaching an editing URL is a permissions failure, not a missing
    session — and 403 says so, where a redirect to the login page would imply
    signing in again might help.
    """

    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not is_household_admin(request.user):
            raise PermissionDenied(
                "Only a household admin can change this. Ask one of them."
            )
        return view(request, *args, **kwargs)

    return _wrapped


class AdminRequiredMixin:
    """Class-based-view form of admin_required."""

    def dispatch(self, request, *args, **kwargs):
        if not is_household_admin(request.user):
            raise PermissionDenied(
                "Only a household admin can change this. Ask one of them."
            )
        return super().dispatch(request, *args, **kwargs)


def household_of(request):
    """The signed-in roommate's household.

    Every queryset resolves through this rather than through a PK in the URL
    (architecture.md §6.3), so a guessed id can never reach another household.
    """
    return request.user.household
