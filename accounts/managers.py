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

        Deliberately *not* subject to the roommate PIN policy
        (``enforce_pin_policy=False``, so this goes through ``set_password``
        directly, exactly like ``create_user`` did before task 4): this
        credential is what signs the operator into ``/admin/`` via
        ``ModelBackend`` (``username=``/``password=``), a login typed once by
        whoever runs the deployment, not a PIN read off a shared household
        touchscreen. Restricting it to six digits, numeric-only would be a
        strictly *weaker* admin credential, not a safer one.

        That exemption only holds if this account is genuinely unreachable
        through the roommate-facing ``PinBackend`` (accounts/backends.py),
        which gates on ``household_id is not None`` — so this method makes
        household-lessness a real, enforced invariant rather than a
        convention: it *always* creates the member with ``household=None``,
        regardless of what a caller passes. An explicit, non-``None``
        ``household``/``household_id`` kwarg is rejected outright rather
        than silently dropped, because silently discarding an argument a
        caller deliberately supplied would hide a bug instead of surfacing
        it. (A previous version of this method forwarded ``**extra_fields``
        unfiltered and let a caller do exactly that —
        ``create_superuser(..., household=some_household)`` — producing an
        admin-privileged, household-scoped "roommate" with an unvalidated,
        arbitrarily short PIN, fully reachable through ``PinBackend``. See
        task 4 criterion 6.)

        A household's first admin *is* a roommate and should get a
        policy-compliant PIN: create them with
        ``create_user(..., is_admin=True)`` instead (the path #22's bootstrap
        command must use for that step), not this method.
        """
        if extra_fields.get("household") is not None:
            raise ValueError(
                "create_superuser() never sets a household — the operator "
                "account must stay unreachable through the roommate-facing "
                "PinBackend, which depends on household being None. Create "
                "a household's first admin with create_user(..., "
                "is_admin=True) instead, which enforces the roommate PIN "
                "policy."
            )
        if extra_fields.get("household_id") is not None:
            raise ValueError(
                "create_superuser() never sets a household — pass neither "
                "household nor household_id."
            )
        # Force it explicitly rather than merely defaulting it, and drop
        # household_id so the two can never disagree: this line is what
        # makes household-lessness true regardless of what was checked above.
        extra_fields.pop("household_id", None)
        extra_fields["household"] = None

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
