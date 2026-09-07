"""Moving a turn from one state to another.

architecture.md §5: five-plus people share one dataset and the failure mode is
real — two roommates tap "done" on the same turn at once. Every transition here
takes the row's lock first and is guarded by the current state, so the second
write is a harmless no-op rather than a duplicate or an overwrite.
"""

import datetime as dt

from django.db import transaction
from django.utils import timezone

from schedule.models import TERMINAL_STATUSES, AwayPeriod, Turn, TurnStatus


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

    scoped = Turn.objects.for_household(household)
    created = generate_for_household(household, today=today)
    # Skipping runs before overdue marking, and the order is load-bearing:
    # marking first would stamp MISSED on a turn whose assignee was away, which
    # is exactly the accusation plan.md §8 exists to prevent.
    skip_away_turns(scoped, today=today)
    missed = mark_overdue(scoped, today=today)
    return len(created), missed


def _rotation_order_from(chore, member):
    """The chore's rotation, starting at whoever comes *after* ``member``.

    If the assignee is no longer in the rotation — they left, or an admin took
    them out — the walk starts at the top instead. Their turn still has to go
    somewhere.
    """
    rotation = chore.rotation
    if not rotation:
        return []
    ids = [m.pk for m in rotation]
    start = ids.index(member.pk) + 1 if member.pk in ids else 0
    return rotation[start:] + rotation[:start]


def _is_away(member, date, absences):
    return any(
        period.member_id == member.pk and period.covers(date) for period in absences
    )


@transaction.atomic
def skip_away_turns(queryset=None, *, today=None):
    """Hand on turns falling inside their assignee's declared absence.

    Returns ``(skipped, reassigned)``.

    plan.md §8 is explicit that a planned absence must be distinguishable from a
    genuine miss, so the original turn goes to SKIPPED_AWAY — its own terminal
    status — rather than being quietly reassigned and forgotten. Otherwise §4's
    record would blame someone for a chore they were never due to do.

    Passing it to the next roommate rather than leaving it undone answers the
    spec's open question: the household should not go without a clean bathroom
    because one person is on holiday.

    Idempotent. A turn already SKIPPED_AWAY is terminal and is never revisited,
    and a cycle that already has a live replacement is left alone.
    """
    today = today or timezone.localdate()
    turns = Turn.objects.all() if queryset is None else queryset

    candidates = list(
        turns.filter(status=TurnStatus.PENDING)
        .select_related("chore", "assignee")
        .order_by("due_date")
    )
    if not candidates:
        return 0, 0

    # One query for every absence that could matter, rather than one per turn.
    # "Could matter" includes everyone in the affected rotations, not only the
    # current assignees: the whole point is to hand a turn on, and deciding
    # whether the *next* person is free needs their absences loaded too.
    relevant_members = {t.assignee_id for t in candidates}
    for chore in {t.chore for t in candidates}:
        relevant_members.update(m.pk for m in chore.rotation)

    absences = list(
        AwayPeriod.objects.filter(
            member__in=relevant_members,
            start_date__lte=max(t.due_date for t in candidates),
            end_date__gte=min(t.due_date for t in candidates),
        )
    )
    if not absences:
        return 0, 0

    skipped = reassigned = 0
    for turn in candidates:
        if not _is_away(turn.assignee, turn.due_date, absences):
            continue

        turn.status = TurnStatus.SKIPPED_AWAY
        turn.save(update_fields=["status"])
        skipped += 1

        # Hand it on to the first person in the rotation who is actually here.
        # If the next one is away too, keep walking; if the whole flat is away,
        # nobody takes it and the cycle simply goes undone -- which is honest,
        # and still not anybody's failure.
        for candidate in _rotation_order_from(turn.chore, turn.assignee):
            if _is_away(candidate, turn.due_date, absences):
                continue
            Turn.objects.create(
                chore=turn.chore,
                assignee=candidate,
                cycle_index=turn.cycle_index,
                period_start=turn.period_start,
                due_date=turn.due_date,
                replaces=turn,
            )
            reassigned += 1
            break

    return skipped, reassigned


@transaction.atomic
def swap_turns(first, second):
    """Trade the assignees of two turns. Returns the pair, refreshed.

    plan.md §8 asks for swapping alongside skipping, and §4's accountability
    goal means the trade should be *recorded* rather than silently rewriting who
    was assigned — so the two rows are linked, and the swap stays visible in
    history rather than looking like the rota was always that way.

    Both turns stay PENDING. Only the assignee moves. (architecture.md §4's
    prose and tasks.md §19 both say so; its state diagram shows a SWAPPED state
    instead. Following the two that agree — a turn still has to be done by
    somebody, so retiring it into a terminal state would lose the work.)
    """
    if first.pk == second.pk:
        raise TransitionRefused("A turn cannot be swapped with itself.")

    # Deterministic lock order, so two swaps racing over the same pair cannot
    # deadlock by taking the rows in opposite orders.
    low, high = sorted([first.pk, second.pk])
    locked = {
        turn.pk: turn
        for turn in Turn.objects.select_for_update()
        .select_related("chore", "assignee")
        .filter(pk__in=[low, high])
    }
    first, second = locked[first.pk], locked[second.pk]

    if first.chore.household_id != second.chore.household_id:
        raise TransitionRefused("Those turns belong to different households.")

    for turn in (first, second):
        if turn.status != TurnStatus.PENDING:
            raise TransitionRefused(
                f"“{turn.chore.name}” on {turn.due_date} is already "
                f"{turn.get_status_display().lower()} and cannot be swapped."
            )
        if turn.swap_partner is not None:
            raise TransitionRefused(
                f"“{turn.chore.name}” on {turn.due_date} has already been swapped."
            )

    if first.assignee_id == second.assignee_id:
        raise TransitionRefused("Both turns already belong to the same person.")

    first.assignee, second.assignee = second.assignee, first.assignee
    first.swapped_with = second
    first.save(update_fields=["assignee", "swapped_with"])
    second.save(update_fields=["assignee"])
    return first, second
