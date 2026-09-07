"""Enforce display_name uniqueness case-insensitively.

The field-level unique=True set in 0001_initial only rejects a byte-for-byte
duplicate. accounts/backends.py signs a roommate in with
``display_name__iexact``, so two rows differing only by case (``"Ana"`` /
``"ana"``) let that lookup match more than one row and raise
MultipleObjectsReturned instead of authenticating anyone -- a worse failure
than a rejected duplicate. See issue #2, acceptance criterion 5.

This is a follow-up migration rather than an edit to 0001_initial.py, which
is already applied and must stay first.
"""

from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Lower


def reject_existing_case_insensitive_duplicates(apps, schema_editor):
    """Fail loudly, before the schema change, if the fix can't apply cleanly.

    Adding the constraint below would otherwise fail with a raw
    IntegrityError from the database the moment two existing rows collide
    case-insensitively -- correct, but opaque. This gives whoever runs
    `migrate` a clear, actionable message instead, naming the colliding
    names so they can rename one of each pair (e.g. via the Django admin,
    already in place from #1) before retrying.
    """
    Member = apps.get_model("accounts", "Member")
    colliding = (
        Member.objects.annotate(display_name_lower=Lower("display_name"))
        .values("display_name_lower")
        .annotate(row_count=Count("id"))
        .filter(row_count__gt=1)
        .values_list("display_name_lower", flat=True)
    )
    names = sorted(colliding)
    if names:
        raise RuntimeError(
            "Cannot make display_name uniqueness case-insensitive: these "
            "names already have more than one member differing only by "
            f"case: {', '.join(names)}. Rename one member in each pair "
            "(e.g. via the Django admin) and re-run `migrate`."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_loginattempt"),
    ]

    operations = [
        migrations.RunPython(
            reject_existing_case_insensitive_duplicates,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="member",
            constraint=models.UniqueConstraint(
                Lower("display_name"), name="unique_display_name_ci"
            ),
        ),
    ]
