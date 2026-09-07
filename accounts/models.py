from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from accounts.managers import MemberManager
from accounts.validators import validate_timezone


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
        ]

    def __str__(self):
        return self.display_name

    def get_short_name(self):
        return self.display_name

    def get_full_name(self):
        return self.display_name

    def set_pin(self, raw_pin):
        """Hash and store a PIN. An alias for ``set_password``.

        Named for what it holds, so no caller is tempted to think the field
        keeps a plaintext PIN.
        """
        self.set_password(raw_pin)

    def check_pin(self, raw_pin):
        return self.check_password(raw_pin)
