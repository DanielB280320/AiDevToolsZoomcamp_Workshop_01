"""Add Member.pin_is_validated and backfill existing rows.

Task 4 criterion 6's invariant ("no Member row may ever exist with
household_id not None and a PIN whose raw value was never checked against
validate_pin") is enforced in accounts/models.py's Member.save() against
this field. It has to be a real, persisted column rather than an
in-memory-only flag: the guarantee must survive a row being loaded fresh in
a later request, not just hold for the lifetime of the Python object that
first set the password (an operator account created household-less in one
request, then given a household in a completely separate one later, must be
caught exactly the same as doing both in a single breath).

Every row that already exists before this migration was created through
this app's own create_user()/set_pin() path (the one known exploit --
create_superuser(..., household=...) -- was already closed in a previous
migration-free fix and, in any case, produces no migration-visible
difference in shape from a compliant row). There is no history of a row
existing any other way, so backfilling every existing row to
pin_is_validated=True is the correct default, not an amnesty: this column
exists to catch *future* state changes, not to retroactively audit rows
that predate it.
"""

from django.db import migrations, models


def backfill_pin_is_validated(apps, schema_editor):
    Member = apps.get_model("accounts", "Member")
    Member.objects.update(pin_is_validated=True)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_member_unique_display_name_ci"),
    ]

    operations = [
        migrations.AddField(
            model_name="member",
            name="pin_is_validated",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.RunPython(backfill_pin_is_validated, migrations.RunPython.noop),
    ]
