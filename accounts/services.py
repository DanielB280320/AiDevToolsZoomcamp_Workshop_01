"""Sign-in as a single operation: throttle check, authenticate, record."""

from dataclasses import dataclass

from django.contrib.auth import authenticate

from accounts.models import LoginAttempt

# plan.md §5 asks for a lightweight sign-in, and architecture.md §6 requires the
# form never to reveal which names exist. One message covers a wrong PIN, an
# unknown name and a deactivated member, so none of the three can be told apart.
GENERIC_FAILURE = "That name and PIN don't match. Please try again."
LOCKED_OUT = (
    "Too many attempts. For security this sign-in is paused for a few minutes — "
    "try again shortly, or ask a household admin to reset your PIN."
)


@dataclass(frozen=True)
class LoginResult:
    member: object | None
    error: str | None
    locked_out: bool = False

    @property
    def ok(self):
        return self.member is not None


def client_ip(request):
    """Best-effort client address, used only as a throttling key.

    X-Forwarded-For is spoofable, so this is not a security boundary on its own;
    it narrows the lockout so one roommate's fumbling does not lock the whole
    household out from a shared address.
    """
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def attempt_login(request, display_name, pin):
    """Try to sign a roommate in, honouring the lockout.

    A locked-out attempt is not passed to the backend at all — checking the PIN
    anyway would leak, through timing, whether the guess was right.
    """
    ip_address = client_ip(request)

    if LoginAttempt.is_locked_out(display_name, ip_address):
        LoginAttempt.record(display_name, ip_address, succeeded=False)
        return LoginResult(member=None, error=LOCKED_OUT, locked_out=True)

    member = authenticate(request, display_name=display_name, pin=pin)
    LoginAttempt.record(display_name, ip_address, succeeded=member is not None)

    if member is None:
        return LoginResult(member=None, error=GENERIC_FAILURE)
    return LoginResult(member=member, error=None)
