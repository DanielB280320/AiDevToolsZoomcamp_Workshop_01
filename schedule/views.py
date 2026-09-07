from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from accounts.mixins import household_of
from schedule.forms import AwayPeriodForm, HistoryFilterForm, SwapForm
from schedule.models import AwayPeriod, Turn, TurnStatus
from schedule.services.transitions import TransitionRefused, complete_turn


@require_POST
def turn_complete(request, pk):
    """Mark a turn done, attributed to whoever tapped it.

    Deliberately open to every roommate rather than the assignee alone: plan.md
    §4 wants covering captured accurately, and refusing it here would just push
    people into lying about who did the work.
    """
    turn = get_object_or_404(Turn.objects.for_household(household_of(request)), pk=pk)
    try:
        turn, changed = complete_turn(turn, request.user)
    except TransitionRefused as refusal:
        messages.error(request, str(refusal))
    else:
        if changed:
            messages.success(request, f"“{turn.chore.name}” marked done. Thanks.")
        else:
            # The other tap won. Say so plainly rather than claiming credit.
            messages.info(
                request,
                f"“{turn.chore.name}” was already marked done by "
                f"{turn.completed_by.display_name}.",
            )
    return redirect(request.POST.get("next") or turn.chore.get_absolute_url())


@require_http_methods(["GET", "POST"])
def away_list(request):
    """Absences for the whole household, and the form to declare one.

    Everyone sees everyone's: the rota is shared, so knowing who is away next
    week is ordinary household information rather than something private.
    """
    household = household_of(request)
    form = AwayPeriodForm(request.POST or None, actor=request.user)

    if request.method == "POST" and form.is_valid():
        away = form.save()
        if away.declared_on_their_behalf:
            messages.success(
                request,
                f"Recorded {away.member.display_name} away "
                f"{away.start_date} to {away.end_date}.",
            )
        else:
            messages.success(
                request, f"You are down as away {away.start_date} to {away.end_date}."
            )
        return redirect("away_list")

    periods = (
        AwayPeriod.objects.for_household(household)
        .select_related("member", "created_by")
        .order_by("-start_date")
    )
    return render(
        request,
        "schedule/away_list.html",
        {"form": form, "periods": periods, "today": timezone.localdate()},
    )


@require_POST
def away_delete(request, pk):
    """Cancel an absence. Yours, or anyone's if you are an admin."""
    away = get_object_or_404(
        AwayPeriod.objects.for_household(household_of(request)), pk=pk
    )
    if away.member_id != request.user.pk and not request.user.is_admin:
        raise PermissionDenied("You can only cancel your own time away.")

    away.delete()
    messages.success(request, "Absence removed.")
    return redirect("away_list")


@require_http_methods(["GET", "POST"])
def swap_list(request):
    """Trade a turn with a flatmate.

    The swap happens in the form's clean(), so a refusal comes back as a form
    error on the page the roommate is already looking at rather than as a
    redirect carrying a message about something they can no longer see.
    """
    form = SwapForm(request.POST or None, actor=request.user)

    if request.method == "POST" and form.is_valid():
        mine, theirs = form.cleaned_data["mine"], form.cleaned_data["theirs"]
        messages.success(
            request,
            f"Swapped. You now have “{mine.chore.name}” on {mine.due_date}; "
            f"{theirs.assignee.display_name} takes “{theirs.chore.name}” "
            f"on {theirs.due_date}.",
        )
        return redirect("swap_list")

    household = household_of(request)
    swapped = (
        Turn.objects.for_household(household)
        .filter(swapped_with__isnull=False)
        .select_related("chore", "assignee", "swapped_with__assignee")
        .order_by("-due_date")
    )
    return render(
        request,
        "schedule/swap_list.html",
        {"form": form, "swapped": swapped},
    )


#: Long enough that a month of a five-person flat fits on one page, short
#: enough to stay readable on a phone.
HISTORY_PAGE_SIZE = 25


def fairness_summary(household, turns):
    """Per roommate: work actually done, turns missed, absences skipped.

    Completed counts by ``completed_by`` rather than ``assignee`` -- the
    question this table answers is who did the work, and plan.md §4 records
    covering precisely so it can be credited to the person who turned up.
    Missed counts by ``assignee``, because that is whose turn went undone.

    Skipped is shown alongside rather than folded into either. It is neither a
    contribution nor a failure, and hiding it would make a roommate who was
    away look idle (plan.md §8).
    """
    rows = []
    for member in household.members.order_by("display_name"):
        done = turns.filter(status=TurnStatus.COMPLETED, completed_by=member).count()
        missed = turns.filter(status=TurnStatus.MISSED, assignee=member).count()
        skipped = turns.filter(status=TurnStatus.SKIPPED_AWAY, assignee=member).count()
        covered = (
            turns.filter(status=TurnStatus.COMPLETED, completed_by=member)
            .exclude(assignee=member)
            .count()
        )
        if done or missed or skipped:
            rows.append(
                {
                    "member": member,
                    "done": done,
                    "missed": missed,
                    "skipped": skipped,
                    "covered": covered,
                }
            )
    return rows


def history(request):
    """Who did what, and how the load has fallen.

    plan.md §4 calls for a history log and for surfacing who missed which
    chores; this is the screen where both are actually read. It favours clarity
    over density on purpose -- people open it when they disagree, and a dense
    table is easy to misread in your own favour.
    """
    household = household_of(request)
    form = HistoryFilterForm(request.GET or None, household=household)

    turns = (
        Turn.objects.for_household(household)
        .settled()
        .select_related("chore", "assignee", "completed_by")
        .order_by("-due_date", "chore__name")
    )
    turns = form.narrow(turns)

    page = Paginator(turns, HISTORY_PAGE_SIZE).get_page(request.GET.get("page"))

    query = request.GET.copy()
    query.pop("page", None)

    return render(
        request,
        "schedule/history.html",
        {
            "form": form,
            "page": page,
            "summary": fairness_summary(household, turns),
            "is_filtered": bool(query),
            "querystring": query.urlencode(),
        },
    )
