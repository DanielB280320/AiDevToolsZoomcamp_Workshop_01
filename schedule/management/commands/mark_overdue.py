"""Flag turns nobody did in time. Safe to run on a cron; a repeat run is a no-op."""

from django.core.management.base import BaseCommand

from schedule.services.transitions import mark_overdue


class Command(BaseCommand):
    help = "Move pending turns past their due date and grace to MISSED."

    def handle(self, *args, **options):
        moved = mark_overdue()
        self.stdout.write(self.style.SUCCESS(f"{moved} turn(s) marked missed."))
