"""Authentication by display name and PIN (plan.md §5)."""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend

UserModel = get_user_model()


class PinBackend(BaseBackend):
    """Check a roommate's PIN against the stored hash.

    Deliberately built on Django's hasher stack rather than a bespoke check, so
    PINs get the same treatment as any password: hashed with PBKDF2, verified in
    constant time, and transparently upgraded when the hasher changes.
    """

    def authenticate(self, request, display_name=None, pin=None, **kwargs):
        # Django's login() calls authenticate() with username=/password=; accept
        # those spellings too so the standard machinery keeps working.
        if display_name is None:
            display_name = kwargs.get("username") or kwargs.get(
                UserModel.USERNAME_FIELD
            )
        if pin is None:
            pin = kwargs.get("password")

        if not display_name or not pin:
            return None

        try:
            member = UserModel.objects.get(display_name__iexact=display_name.strip())
        except UserModel.DoesNotExist:
            # Hash anyway. Returning early for an unknown name would make the
            # response measurably faster than for a known one, which is enough
            # to enumerate the household's roommates.
            UserModel().set_password(pin)
            return None

        if not member.check_password(pin):
            return None
        if not self.user_can_authenticate(member):
            return None
        return member

    def user_can_authenticate(self, member):
        """Only an active roommate may sign in through this backend.

        A deactivated roommate has moved out (plan.md §4); their history
        stays intact, only access is withdrawn.

        A member with no household is the deployment operator, not a
        roommate (``Member.household``'s own help text: "Left empty only for
        an operator superuser, who administers the deployment rather than
        living in it"). This task's Goal is "a roommate identifies
        themself" — an operator explicitly is not one, so PinBackend must
        never authenticate that account. This does not lock the operator out
        of ``/admin/``: ``django.contrib.auth.backends.ModelBackend``, second
        in ``AUTHENTICATION_BACKENDS``, authenticates the same superuser
        independently via ``username=``/``password=``, unaffected by this
        check.
        """
        return bool(member.is_active) and member.household_id is not None

    def get_user(self, user_id):
        try:
            member = UserModel.objects.get(pk=user_id)
        except UserModel.DoesNotExist:
            return None
        return member if self.user_can_authenticate(member) else None
