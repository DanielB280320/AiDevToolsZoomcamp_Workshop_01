from django.contrib.auth.base_user import BaseUserManager


class MemberManager(BaseUserManager):
    """Creates roommates.

    ``password`` throughout is the roommate's PIN. It is passed through
    ``set_password`` so only the hash is ever stored (plan.md §5) — nothing here
    keeps, returns or logs the plaintext.
    """

    use_in_migrations = True

    def _create_member(self, display_name, password, **extra_fields):
        display_name = (display_name or "").strip()
        if not display_name:
            raise ValueError("Members must have a display name.")

        member = self.model(display_name=display_name, **extra_fields)
        member.set_password(password)
        member.save(using=self._db)
        return member

    def create_user(self, display_name, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("is_admin", False)
        return self._create_member(display_name, password, **extra_fields)

    def create_superuser(self, display_name, password=None, **extra_fields):
        """The Django-admin operator account (architecture.md §6).

        Distinct from ``is_admin``, which is the household role from plan.md §7.
        A superuser is also given the household role so that a one-person
        bootstrap does not lock itself out of the chore screens.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_admin", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_member(display_name, password, **extra_fields)

    def active(self):
        """Current roommates — the ones a rotation may assign a turn to."""
        return self.get_queryset().filter(is_active=True)
