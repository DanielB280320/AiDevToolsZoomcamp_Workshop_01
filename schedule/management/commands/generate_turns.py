"""Materialise upcoming turns. Safe to run on a cron; a repeat run is a no-op."""

from django.core.management.base import BaseCommand

from accounts.models import Household
from schedule.services.generation import DEFAULT_HORIZON_WEEKS, generate_for_household


class Command(BaseCommand):
    help = "Create turns for every active chore, out to the horizon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--weeks",
            type=int,
            default=DEFAULT_HORIZON_WEEKS,
            help=f"How far ahead to generate (default {DEFAULT_HORIZON_WEEKS}).",
        )

    def handle(self, *args, **options):
        total = 0
        for household in Household.objects.all():
            created = generate_for_household(household, horizon_weeks=options["weeks"])
            total += len(created)
            self.stdout.write(f"{household.name}: {len(created)} new turns")
        self.stdout.write(
            self.style.SUCCESS(
                f"{total} new turns across {Household.objects.count()} household(s)."
            )
        )
