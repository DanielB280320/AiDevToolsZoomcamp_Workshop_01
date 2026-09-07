import datetime as dt

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from accounts.managers import MemberManager
from accounts.validators import validate_pin, validate_timezone


class Household(models.Model):
    """A shared home, and the scoping key for every other row in the system.

    There is one household in the MVP, but it is a row rather than a constant
    from day one: plan.md §1 calls for a custom, variable-length roommate list,
    which means "the roommates" has to be a queryset off something. It is also
    what every view filters by (architecture.md §6) so a stray PK in a URL can
    never reach another household's data.
    """

    name = models.CharField(max_length=100)
    timezone = models.CharField(
        max_length=64,
        default="UTC",
        validators=[validate_timezone],
        help_text=(
            "IANA timezone name. Due dates and overdue checks are evaluated in "
            "this timezone."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def member_count(self):
        """Current roommates. Never a hardcoded number — plan.md §1."""
        return self.members.filter(is_active=True).count()


class Member(AbstractBaseUser, PermissionsMixin):
    """A roommate, and the project's ``AUTH_USER_MODEL``.

    Authentication is by display name plus PIN (plan.md §5), so ``password`` —
    inherited from ``AbstractBaseUser`` — holds the *hashed PIN*. The PIN is
    never stored or logged in plaintext. The PIN-checking backend, its six-digit
    minimum and the lockout on repeated failures are tasks 4 and 5; this model
    only has to store the hash.
    """

    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name="members",
        null=True,
        blank=True,
        help_text=(
            "Every roommate belongs to a household. Left empty only for an "
            "operator superuser, who administers the deployment rather than "
            "living in it."
        ),
    )

    # USERNAME_FIELD. Unique across the table rather than per household: Django
    # requires the username field to be globally unique, and with one household
    # the two are the same rule. Multi-household (architecture.md §9) would make
    # this a (household, display_name) constraint and add a household step to
    # sign-in.
    display_name = models.CharField(
        max_length=50,
        unique=True,
        help_text="The name other roommates see, and the name signed in with.",
    )

    # plan.md §7: only some roommates may add, edit or remove chores. Distinct
    # from is_superuser, which is Django-admin access for the operator.
    is_admin = models.BooleanField(
        default=False,
        verbose_name="household admin",
        help_text="Can add, edit and archive chores, and manage the roommate list.",
    )

    # plan.md §4's history has to survive someone moving out, so a departed
    # roommate is deactivated, never deleted — deleting would cascade away the
    # completion record their housemates may later need to settle a dispute.
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Uncheck when a roommate moves out. This keeps their history intact "
            "and stops them being given new turns; it does not delete anything."
        ),
    )

    is_staff = models.BooleanField(
        default=False,
        help_text="Can sign in to the Django admin site.",
    )

    joined_on = models.DateField(
        default=timezone.localdate,
        help_text="When they moved in. The insert point for chore rotations.",
    )

    # Internal bookkeeping only — never listed in a form or fieldset, never
    # shown anywhere. True exactly when the current ``password`` hash was
    # set through ``set_pin()`` (which runs ``validate_pin`` first);
    # ``set_password()`` — called directly by ``create_superuser``, Django's
    # own admin password-change form, ``manage.py changepassword``, and any
    # stock ``ModelForm`` such as the admin's built-in ``UserCreationForm``
    # (accounts/admin.py's "Add member" screen) — always clears it. Persisted
    # (not merely tracked in memory for the lifetime of one Python object)
    # so the guarantee survives a reload in a later request, not just the
    # process that first set the password. See ``save()`` below, which is
    # what actually enforces task 4 criterion 6's invariant using this field.
    pin_is_validated = models.BooleanField(default=False, editable=False)

    objects = MemberManager()

    USERNAME_FIELD = "display_name"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["display_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "display_name"],
                name="unique_display_name_per_household",
            ),
            # The field-level unique=True above is only byte-for-byte. Sign-in
            # (accounts/backends.py) looks members up with display_name__iexact,
            # so "Ana" and "ana" must be treated as the same name at the
            # database level too, or that lookup can match more than one row
            # and raise MultipleObjectsReturned instead of authenticating
            # anyone. Added in 0003_member_display_name_unique_ci; see that
            # migration for what happens to any pre-existing case-variant rows.
            models.UniqueConstraint(
                Lower("display_name"),
                name="unique_display_name_ci",
            ),
        ]

    def __str__(self):
        return self.display_name

    def get_short_name(self):
        return self.display_name

    def get_full_name(self):
        return self.display_name

    def set_pin(self, raw_pin):
        """Validate, hash and store a PIN.

        Named for what it holds, so no caller is tempted to think the field
        keeps a plaintext PIN. The only setter that marks
        ``pin_is_validated`` True — see ``set_password()`` and ``save()``
        below for what that flag actually enforces, and why.
        """
        validate_pin(raw_pin)
        self.set_password(raw_pin)
        self.pin_is_validated = True

    def set_password(self, raw_password):
        """Hash and store a credential, exactly like the inherited method —
        Django internals (the admin's own password-change form,
        ``manage.py changepassword``), ``create_superuser`` (legitimately
        exempt from the PIN policy while ``household`` stays ``None``, see
        ``MemberManager``), and any stock ``ModelForm`` all call this
        directly and must keep working, unconstrained, exactly as before.

        The one addition: this always clears ``pin_is_validated``, because
        a call here — as opposed to ``set_pin()`` — is proof the six-digit
        minimum was *not* checked for whatever was just set. ``save()``
        below is what turns that into an actual guarantee.
        """
        super().set_password(raw_password)
        self.pin_is_validated = False

    def save(self, *args, **kwargs):
        """Task 4 criterion 6's invariant, enforced at the one layer every
        write to this model passes through, rather than as a growing list
        of guarded call sites (each of which was, in turn, defeated by a
        new one): a row may never be persisted with ``household`` set and a
        credential that was never run through ``validate_pin``.

        This is checked against ``pin_is_validated`` (a real column, not an
        in-memory-only flag) precisely so the guarantee survives a reload
        in a later request — an operator created household-less, then
        loaded fresh in a separate request and given a household there,
        must be caught exactly the same as doing both in one breath.

        ``create_superuser`` stays exempt: it always constructs the row
        with ``household=None`` (enforced in ``MemberManager``), so the
        check below never triggers for it — the exemption holds only for
        as long as that stays true, which is the whole point.
        """
        if self.household_id is not None and not self.pin_is_validated:
            raise ValidationError(
                "This member has a household but its current credential was "
                "never validated as a roommate PIN (accounts/validators.py, "
                "validate_pin). Set it with member.set_pin(raw_pin) before "
                "saving, or use MemberManager.create_user(...) which does "
                "this for you."
            )
        # A caller updating only ["password"] (accounts/views.py's PIN-reset
        # view, out of this issue's scope to edit) must not leave this flag
        # stale in the database — keep the two in lockstep without needing
        # every such call site to remember to list both.
        update_fields = kwargs.get("update_fields")
        if (
            update_fields is not None
            and "password" in update_fields
            and "pin_is_validated" not in update_fields
        ):
            kwargs["update_fields"] = [*update_fields, "pin_is_validated"]
        super().save(*args, **kwargs)

    def check_pin(self, raw_pin):
        return self.check_password(raw_pin)


class LoginAttempt(models.Model):
    """One sign-in attempt, kept so repeated failures can be throttled.

    plan.md §5 chose a short numeric PIN for daily convenience. Six digits is a
    million combinations, which an unthrottled endpoint gives away in minutes.
    This model is the other half of that decision: without it the PIN choice is
    not safe enough even for a household tool (architecture.md §6).

    Attempts are recorded against the *name that was typed*, not a Member FK,
    so guesses at a name that does not exist are throttled too — otherwise the
    lockout itself would reveal which names are real.
    """

    WINDOW = dt.timedelta(minutes=15)
    MAX_FAILURES = 5

    display_name = models.CharField(max_length=50, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    succeeded = models.BooleanField(default=False)
    attempted_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-attempted_at"]
        indexes = [
            models.Index(fields=["display_name", "ip_address", "attempted_at"]),
        ]

    def __str__(self):
        outcome = "ok" if self.succeeded else "failed"
        return f"{self.display_name} {outcome} at {self.attempted_at:%Y-%m-%d %H:%M}"

    @classmethod
    def _recent_failures(cls, display_name, ip_address):
        since = timezone.now() - cls.WINDOW
        return cls.objects.filter(
            display_name__iexact=(display_name or "").strip(),
            ip_address=ip_address,
            succeeded=False,
            attempted_at__gte=since,
        )

    @classmethod
    def is_locked_out(cls, display_name, ip_address):
        return (
            cls._recent_failures(display_name, ip_address).count() >= cls.MAX_FAILURES
        )

    @classmethod
    def record(cls, display_name, ip_address, *, succeeded):
        attempt = cls.objects.create(
            display_name=(display_name or "").strip(),
            ip_address=ip_address,
            succeeded=succeeded,
        )
        if succeeded:
            # A correct PIN clears the slate, so a roommate who fumbles twice
            # and then gets it right is not one slip away from a lockout.
            cls._recent_failures(display_name, ip_address).delete()
        return attempt

    @classmethod
    def locked_until(cls, display_name, ip_address):
        """When the current lockout lifts, or None if there is no lockout.

        The window slides: it expires MAX_FAILURES-th-most-recent failure plus
        WINDOW, so waiting it out works without any scheduled cleanup.
        """
        failures = cls._recent_failures(display_name, ip_address).order_by(
            "-attempted_at"
        )[: cls.MAX_FAILURES]
        failures = list(failures)
        if len(failures) < cls.MAX_FAILURES:
            return None
        return failures[-1].attempted_at + cls.WINDOW


def purge_old_login_attempts(older_than=None):
    """Drop attempts too old to affect any lockout.

    Nothing depends on this running — the lockout query is time-bounded — but
    the table would otherwise grow without limit.
    """
    cutoff = timezone.now() - (older_than or LoginAttempt.WINDOW * 4)
    deleted, _ = LoginAttempt.objects.filter(attempted_at__lt=cutoff).delete()
    return deleted
