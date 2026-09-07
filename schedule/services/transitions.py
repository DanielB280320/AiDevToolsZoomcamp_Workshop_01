"""Moving a turn from one state to another.

architecture.md §5: five-plus people share one dataset and the failure mode is
real — two roommates tap "done" on the same turn at once. Every transition here
takes the row's lock first and is guarded by the current state, so the second
write is a harmless no-op rather than a duplicate or an overwrite.
"""

import datetime as dt

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


def mark_overdue(queryset=None, *, today=None):
    """Move pending turns past their deadline to MISSED. Returns how many moved.

    plan.md §4 names surfacing who missed which chores as a core requirement,
    and §6 keeps reminders inside the app — so this has to be correct at the
    moment someone looks, not only after a cron ran. It is therefore called
    both ways (architecture.md §4), which is why it must be idempotent: the
    filter is on PENDING, so a second run finds nothing left to move.

    The deadline is per chore, since grace is a chore's own setting. Rather than
    date arithmetic across a relation — which is where portability between
    SQLite and PostgreSQL gets awkward — this issues one UPDATE per distinct
    grace value. A household has a handful of those, not thousands.
    """
    today = today or timezone.localdate()
    turns = Turn.objects.all() if queryset is None else queryset
    pending = turns.filter(status=TurnStatus.PENDING)

    moved = 0
    grace_values = (
        pending.values_list("chore__grace_days", flat=True).order_by().distinct()
    )
    for grace in list(grace_values):
        cutoff = today - dt.timedelta(days=grace)
        moved += pending.filter(chore__grace_days=grace, due_date__lt=cutoff).update(
            status=TurnStatus.MISSED
        )
    return moved


def refresh_household(household, *, today=None):
    """Bring one household's turns up to date, for a page that is about to render.

    Generation first, then overdue marking: a turn that was never materialised
    cannot be marked missed, and architecture.md §4 wants both correct at the
    moment someone opens the app rather than whenever cron last ran.
    """
    from schedule.services.generation import generate_for_household

    created = generate_for_household(household, today=today)
    missed = mark_overdue(Turn.objects.for_household(household), today=today)
    return len(created), missed
