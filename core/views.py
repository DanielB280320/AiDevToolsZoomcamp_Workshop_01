import datetime as dt

from django.shortcuts import render
from django.utils import timezone

from accounts.mixins import household_of
from schedule.models import Turn, TurnStatus
from schedule.services.transitions import refresh_household

#: What counts as "due soon" on the home screen. Long enough to plan an evening
#: around, short enough that the list stays glanceable — plan.md §6 makes this
#: screen the only reminder channel, and a fortnight of turns would bury the
#: two that actually matter tonight.
SOON_DAYS = 7


def dashboard(request):
    """What you owe, and what the household is late on.

    plan.md §6 chose in-app reminders as the only notification channel, which
    puts the entire reminder burden here: if it is not obvious on this screen,
    nobody finds out at all.

    Overdue is shown to *everyone*, not only the assignee — that answers the
    spec's open question on visibility. In a peer household the shared sight of
    it is what gives a reminder any weight; a private nudge nobody else can see
    is just a nag.
    """
    household = household_of(request)
    # architecture.md §4: correct at the moment someone looks, not whenever
    # cron last ran.
    refresh_household(household)

    today = timezone.localdate()
    turns = Turn.objects.for_household(household).select_related(
        "chore", "assignee", "completed_by"
    )

    overdue = turns.filter(status=TurnStatus.MISSED).order_by("due_date")
    pending = turns.pending()

    mine = pending.filter(assignee=request.user).order_by("due_date")
    soon = pending.filter(due_date__lte=today + dt.timedelta(days=SOON_DAYS))

    return render(
        request,
        "core/dashboard.html",
        {
            "today": today,
            "overdue": overdue,
            "mine_today": [t for t in mine if t.due_date <= today],
            "mine_upcoming": [t for t in mine if t.due_date > today],
            "due_soon": soon.exclude(assignee=request.user).order_by("due_date"),
            "my_overdue_count": overdue.filter(assignee=request.user).count(),
        },
    )
