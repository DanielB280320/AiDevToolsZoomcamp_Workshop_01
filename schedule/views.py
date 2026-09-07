from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from accounts.mixins import household_of
from schedule.forms import AwayPeriodForm, SwapForm
from schedule.models import AwayPeriod, Turn
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
