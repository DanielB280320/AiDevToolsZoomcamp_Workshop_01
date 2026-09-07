"""Materialising future turns.

architecture.md §4: turns are created ahead of time with the assignee written
in, never computed on read. This module is the only thing that creates them.

It is safe to run repeatedly — on cron, on every deploy, lazily on dashboard
load, or twice at once. A second run over the same window creates nothing.
"""

import datetime as dt

from django.db import transaction
from django.utils import timezone

from chores.models import Chore
from schedule.models import Turn

#: How far ahead to materialise. plan.md §2 chose fixed rotation for
#: predictability — everyone should see their turns coming well in advance —
#: and eight weeks is long enough to plan a holiday around (plan.md §8) without
#: filling the table with turns nobody will look at.
DEFAULT_HORIZON_WEEKS = 8


def _window_start(chore, today):
    """The earliest due date this chore should have a turn for.

    Two boundaries, and the later one wins:

    - the chore's own anchor, since nothing happens before its first turn; and
    - the day the chore was created, because a household cannot be held to
      account for a chore that did not exist yet. An admin who back-dates an
      anchor to get the cadence phase right must not thereby invent a year of
      turns everyone "missed".

    Deliberately *not* ``today``: if cron is late, or nobody opens the app for a
    week, the turns due in that gap still have to exist, or task 15 could never
    mark them missed and the record would quietly lose them.
    """
    created_on = timezone.localdate(chore.created_at)
    return max(chore.anchor_date, created_on)


def cycles_in_window(chore, start, end):
    """Yield ``(cycle_index, due_date)`` for every cycle due within the window.

    Walks forward from the anchor rather than solving for the index: a month
    step is not a fixed number of days, so arithmetic on the interval would be
    wrong for exactly the month-end cases task 8 pinned down.
    """
    index = 0
    while True:
        due = chore.due_date_for_cycle(index)
        if due > end:
            return
        if due >= start:
            yield index, due
        index += 1
        # A chore whose cadence somehow fails to advance would spin here.
        if index > 10_000:  # pragma: no cover - guards a corrupt row
            raise RuntimeError(f"{chore} produced no progress in its cadence")


def existing_cycles(chore, cycle_indexes):
    """Which of these cycles this chore already has turns for.

    A named seam rather than an inline query: it is the half of idempotency
    that can go stale under a concurrent run, and the test for that race needs
    somewhere to stand.
    """
    return set(
        chore.turns.filter(cycle_index__in=cycle_indexes).values_list(
            "cycle_index", flat=True
        )
    )


@transaction.atomic
def generate_for_chore(chore, *, today=None, horizon_weeks=DEFAULT_HORIZON_WEEKS):
    """Materialise this chore's turns through the horizon. Returns the new ones.

    An archived chore, or one with nobody in its rotation, generates nothing —
    there is no honest answer to "whose turn is it" for either.
    """
    if not chore.is_active:
        return []

    rotation = chore.rotation
    if not rotation:
        return []

    today = today or timezone.localdate()
    start = _window_start(chore, today)
    end = today + dt.timedelta(weeks=horizon_weeks)

    wanted = dict(cycles_in_window(chore, start, end))
    if not wanted:
        return []

    existing = existing_cycles(chore, wanted)

    fresh = [
        Turn(
            chore=chore,
            # The rotation as it stands *now*, snapshotted onto the row. A later
            # rotation change cannot reach back and rewrite this.
            assignee=rotation[index % len(rotation)],
            cycle_index=index,
            # Periods abut rather than overlap: a cycle owns the days after
            # the previous turn was due, up to and including its own due date.
            period_start=(
                chore.due_date_for_cycle(index - 1) + dt.timedelta(days=1)
                if index
                else due
            ),
            due_date=due,
        )
        for index, due in sorted(wanted.items())
        if index not in existing
    ]
    if not fresh:
        return []

    # ignore_conflicts is the race guard, not the idempotency mechanism: the
    # `existing` check above already handles the ordinary repeat run. This is
    # what makes two simultaneous runs collide harmlessly at the database
    # (architecture.md §5) instead of raising.
    Turn.objects.bulk_create(fresh, ignore_conflicts=True)
    return list(chore.turns.filter(cycle_index__in=[t.cycle_index for t in fresh]))


def generate_for_household(
    household, *, today=None, horizon_weeks=DEFAULT_HORIZON_WEEKS
):
    """Generate for every active chore in one household. Returns the new turns."""
    created = []
    for chore in Chore.objects.for_household(household).active():
        created.extend(
            generate_for_chore(chore, today=today, horizon_weeks=horizon_weeks)
        )
    return created
