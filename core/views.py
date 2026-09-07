from django.shortcuts import render

from accounts.mixins import household_of
from schedule.services.transitions import refresh_household


def dashboard(request):
    """Placeholder landing page.

    Task 16 replaces this with the real due/overdue surface. What it already
    does is architecture.md §4's lazy refresh: generating and overdue-marking
    run here as well as on cron, so a household that never sets up a scheduler
    still sees the truth when someone opens the app.
    """
    generated, missed = refresh_household(household_of(request))
    return render(
        request,
        "core/dashboard.html",
        {"generated": generated, "newly_missed": missed},
    )
