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
        """A deactivated roommate has moved out and may no longer sign in.

        Their history stays intact (plan.md §4); only access is withdrawn.
        """
        return bool(member.is_active)

    def get_user(self, user_id):
        try:
            member = UserModel.objects.get(pk=user_id)
        except UserModel.DoesNotExist:
            return None
        return member if self.user_can_authenticate(member) else None
