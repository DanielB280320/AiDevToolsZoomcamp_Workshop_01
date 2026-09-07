from django.contrib.auth.base_user import BaseUserManager


class MemberManager(BaseUserManager):
    """Creates roommates.

    ``password`` throughout is the roommate's PIN. It is passed through
    ``set_password`` so only the hash is ever stored (plan.md §5) — nothing here
    keeps, returns or logs the plaintext.
    """

    use_in_migrations = True

    def _create_member(
        self, display_name, password, *, enforce_pin_policy, **extra_fields
    ):
        display_name = (display_name or "").strip()
        if not display_name:
            raise ValueError("Members must have a display name.")

        member = self.model(display_name=display_name, **extra_fields)
        if enforce_pin_policy:
            # set_pin validates the six-digit minimum (accounts/validators.py)
            # before hashing — see create_user vs. create_superuser below for
            # which path this applies to and why.
            member.set_pin(password)
        else:
            member.set_password(password)
        member.save(using=self._db)
        return member

    def create_user(self, display_name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("is_admin", False)
        return self._create_member(
            display_name, password, enforce_pin_policy=True, **extra_fields
        )

    def create_superuser(self, display_name, password=None, **extra_fields):
        """The Django-admin operator account (architecture.md §6).

        Distinct from ``is_admin``, which is the household role from plan.md §7.
        A superuser is also given the household role so that a one-person
        bootstrap does not lock itself out of the chore screens.

        Deliberately *not* subject to the roommate PIN policy
        (``enforce_pin_policy=False``, so this goes through ``set_password``
        directly, exactly like ``create_user`` did before task 4): this
        credential is what signs the operator into ``/admin/`` via
        ``ModelBackend`` (``username=``/``password=``), a login typed once by
        whoever runs the deployment, not a PIN read off a shared household
        touchscreen. Restricting it to six digits, numeric-only would be a
        strictly *weaker* admin credential, not a safer one. The roommate-side
        risk this task closes — PinBackend accepting a short PIN — is already
        shut for this account regardless of its password shape, because a
        member with no household can no longer authenticate through
        PinBackend at all (accounts/backends.py, task 4 criterion 7); a
        household-scoped admin, if one is later bootstrapped with a real
        household attached, should be created through ``create_user`` plus an
        ``is_admin=True`` flag instead, which does enforce the PIN policy.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_admin", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_member(
            display_name, password, enforce_pin_policy=False, **extra_fields
        )

    def active(self):
        """Current roommates — the ones a rotation may assign a turn to."""
        return self.get_queryset().filter(is_active=True)
