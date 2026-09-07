"""Moving a turn from one state to another.

architecture.md §5: five-plus people share one dataset and the failure mode is
real — two roommates tap "done" on the same turn at once. Every transition here
takes the row's lock first and is guarded by the current state, so the second
write is a harmless no-op rather than a duplicate or an overwrite.
"""

from django.db import transaction
from django.utils import timezone

from schedule.models import TERMINAL_STATUSES, Turn, TurnStatus


class TransitionRefused(Exception):
    """The turn was not in a state this transition can act on."""


@transaction.atomic
def complete_turn(turn, actor, *, when=None):
    """Mark ``turn`` done by ``actor``. Returns ``(turn, changed)``.

    ``changed`` is False when the turn was already completed — which is what
    makes two people tapping at once safe. The second tap finds the row already
    settled and leaves the first person's attribution alone rather than
    overwriting it with their own name.

    Any roommate may complete any turn. plan.md §4 treats covering for someone
    as a feature, not an anomaly, which is why ``completed_by`` is recorded
    apart from ``assignee`` instead of replacing it.
    """
    # Re-read under a lock. Whatever the caller handed us may already be stale.
    locked = Turn.objects.select_for_update().get(pk=turn.pk)

    if locked.status == TurnStatus.COMPLETED:
        return locked, False

    if locked.status in TERMINAL_STATUSES:
        # SKIPPED_AWAY and SWAPPED are settled by someone else's decision.
        # Quietly completing over them would erase that decision.
        raise TransitionRefused(
            f"This turn is already {locked.get_status_display().lower()}."
        )

    when = when or timezone.now()
    locked.status = TurnStatus.COMPLETED
    locked.completed_by = actor
    locked.completed_at = when
    # Recorded as a fact of its own so a late completion stays visible once the
    # status reads COMPLETED — otherwise being done at all would launder having
    # been late (plan.md §4).
    locked.was_late = timezone.localdate(when) > locked.deadline()
    locked.save(update_fields=["status", "completed_by", "completed_at", "was_late"])
    return locked, True
