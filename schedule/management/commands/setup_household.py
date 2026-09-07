"""Bring a fresh installation up: one household, one admin, optionally chores.

plan.md §5 has no public signup and §7 requires an admin to exist before chores
can be added, which leaves the first admin with nowhere to come from inside the
app. This command is that outside — the spec's open question on how the first
admin is designated, answered.
"""

import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Household, Member
from chores.models import Cadence, Chore

SEED_EXAMPLE = Path("seed.example.json")


class Command(BaseCommand):
    help = "Create the household and its first admin. Optionally seed chores."

    def add_arguments(self, parser):
        parser.add_argument("--household", required=True, help="Household name.")
        parser.add_argument(
            "--admin", required=True, help="Display name of the first admin."
        )
        parser.add_argument(
            "--pin",
            required=True,
            help=(
                "The admin's starting PIN, six digits or more. Prefer piping it "
                "in rather than typing it where a shell history can keep it."
            ),
        )
        parser.add_argument("--timezone", default="UTC")
        parser.add_argument(
            "--seed",
            type=Path,
            help=f"JSON file of chores and rotations. See {SEED_EXAMPLE}.",
        )

    def handle(self, *args, **options):
        if Household.objects.exists():
            # Refuse rather than add a second one. This command is for an empty
            # database; running it twice by accident should not quietly split
            # the flat into two households nobody can see across.
            raise CommandError(
                "A household already exists. This command is for a fresh "
                "install; add roommates and chores through the app instead."
            )

        seed = self._read_seed(options["seed"]) if options["seed"] else None

        try:
            with transaction.atomic():
                household = Household.objects.create(
                    name=options["household"], timezone=options["timezone"]
                )
                admin = Member.objects.create_user(
                    display_name=options["admin"],
                    password=options["pin"],
                    household=household,
                    is_admin=True,
                )
                chores = self._apply_seed(household, admin, seed) if seed else 0
        except ValidationError as invalid:
            # Nothing is left behind: the transaction rolls the household back
            # with it, so a rejected PIN does not leave a half-built flat.
            raise CommandError("; ".join(invalid.messages)) from invalid

        # Never echo the PIN back, not even on success (plan.md §5).
        self.stdout.write(f"Household “{household.name}” created.")
        self.stdout.write(f"Admin “{admin.display_name}” created with the PIN given.")
        if seed:
            self.stdout.write(f"{chores} chore(s) seeded.")
        self.stdout.write(
            self.style.SUCCESS("Ready. Sign in and add the other roommates.")
        )

    def _read_seed(self, path):
        # call_command() bypasses argparse's type=, so a caller in Python can
        # legitimately hand us a plain string where the CLI would give a Path.
        path = Path(path)
        if not path.exists():
            raise CommandError(f"No seed file at {path}.")
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as broken:
            raise CommandError(f"{path} is not valid JSON: {broken}") from broken
        if not isinstance(data, dict) or "chores" not in data:
            raise CommandError(f'{path} needs a top-level "chores" list.')
        return data

    def _apply_seed(self, household, admin, seed):
        """Create the seeded roommates and chores, and their rotations.

        Rotation names are resolved against the roommates this seed creates plus
        the admin, so a typo is an error rather than a silently shorter rota --
        a rota missing someone is exactly the kind of unfairness this app is
        supposed to settle.
        """
        by_name = {admin.display_name: admin}
        for name in seed.get("roommates", []):
            if name == admin.display_name:
                continue
            by_name[name] = Member.objects.create_user(
                display_name=name,
                password=seed.get("starting_pin", "000000"),
                household=household,
            )

        for entry in seed["chores"]:
            chore = Chore.objects.create(
                household=household,
                name=entry["name"],
                description=entry.get("description", ""),
                cadence_unit=entry.get("cadence_unit", Cadence.WEEK),
                cadence_interval=entry.get("cadence_interval", 1),
                anchor_date=entry["anchor_date"],
                grace_days=entry.get("grace_days", 1),
            )
            rotation = []
            for name in entry.get("rotation", []):
                if name not in by_name:
                    raise CommandError(
                        f"“{entry['name']}” lists {name!r} in its rotation, but no "
                        f"such roommate is in the seed file."
                    )
                rotation.append(by_name[name])
            if rotation:
                chore.set_rotation(rotation)

        return len(seed["chores"])
