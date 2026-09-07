from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from accounts.mixins import household_of
from schedule.models import Turn
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
