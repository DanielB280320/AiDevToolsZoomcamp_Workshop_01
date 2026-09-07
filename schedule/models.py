"""Turns — one dated occurrence of one chore, by one roommate.

architecture.md §4 rejects computing the assignee on read
(``members[cycle_index % len(members)]``): membership changes, and under that
scheme adding a sixth roommate silently rewrites who was responsible for every
chore in the past. plan.md §4 exists to make that record trustworthy, so a turn
is a stored row with its assignee written in at generation time. History becomes
immutable by construction; a membership change can only affect turns that have
not been generated yet.
"""

import datetime as dt

from django.db import models
from django.utils import timezone


class TurnStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    COMPLETED = "COMPLETED", "Completed"
    MISSED = "MISSED", "Missed"
    # plan.md §8: a planned absence is not a failure. Collapsing this into
    # MISSED would make the accountability log lie about someone who was never
    # due to do the chore in the first place.
    SKIPPED_AWAY = "SKIPPED_AWAY", "Skipped — away"
    SWAPPED = "SWAPPED", "Swapped"


#: The states nothing moves out of. MISSED is deliberately absent: a chore done
#: late still goes to COMPLETED (architecture.md §4), which is what lets the
#: history show it was eventually done rather than freezing the blame.
TERMINAL_STATUSES = frozenset(
    {TurnStatus.COMPLETED, TurnStatus.SKIPPED_AWAY, TurnStatus.SWAPPED}
)


class TurnQuerySet(models.QuerySet):
    def for_household(self, household):
        return self.filter(chore__household=household)

    def pending(self):
        return self.filter(status=TurnStatus.PENDING)

    def outstanding(self):
        """Still owed by someone — pending, or missed and not yet done."""
        return self.filter(status__in=[TurnStatus.PENDING, TurnStatus.MISSED])


class Turn(models.Model):
    chore = models.ForeignKey(
        "chores.Chore", on_delete=models.CASCADE, related_name="turns"
    )

    # Snapshotted when the turn is generated, from the rotation as it stood at
    # that moment. Never re-derived: that is the guarantee plan.md §4 rests on.
    assignee = models.ForeignKey(
        "accounts.Member",
        on_delete=models.PROTECT,
        related_name="turns",
        help_text="Who this turn fell to when it was generated.",
    )

    # Monotonic per chore, counted from the chore's anchor. This — not the due
    # date — is the identity of an occurrence, because a due date can be moved.
    cycle_index = models.PositiveIntegerField()

    period_start = models.DateField()
    due_date = models.DateField()

    status = models.CharField(
        max_length=16, choices=TurnStatus.choices, default=TurnStatus.PENDING
    )

    completed_at = models.DateTimeField(null=True, blank=True)
    # Recorded separately from ``assignee`` on purpose: when one roommate covers
    # for another, plan.md §4's log should say who actually did it *and* whose
    # turn it was. One field could not hold both.
    completed_by = models.ForeignKey(
        "accounts.Member",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="turns_completed",
        help_text="Who actually did it. Differs from the assignee when covering.",
    )

    # Set when a turn is completed after its due date and grace. Kept as a fact
    # of its own so a late completion is not indistinguishable from an on-time
    # one once the status moves to COMPLETED.
    was_late = models.BooleanField(default=False)

    swapped_with = models.OneToOneField(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="swapped_from",
        help_text="The turn this one was traded with (task 19).",
    )

    # The absence this turn was handed on from (task 18). Distinct from
    # swapped_with, which is a trade between two people who both keep a turn.
    replaces = models.OneToOneField(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replaced_by",
        help_text="The skipped turn this one took over from.",
    )

    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TurnQuerySet.as_manager()

    class Meta:
        ordering = ["due_date", "chore__name"]
        constraints = [
            # architecture.md §4/§5: the idempotency guard. Turn generation runs
            # on cron *and* lazily on dashboard load, so two runs racing must
            # collide harmlessly at the database rather than double-book a
            # cycle.
            # One *live* turn per chore per cycle. Skipped ones are excluded
            # because task 18 has to keep both halves of the story: the turn
            # that fell during someone's absence, and the replacement that
            # passed to the next roommate. Collapsing those into one row would
            # mean either losing the record of the absence or pretending the
            # chore was never reassigned.
            models.UniqueConstraint(
                fields=["chore", "cycle_index"],
                condition=~models.Q(status="SKIPPED_AWAY"),
                name="unique_live_turn_per_chore_cycle",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "due_date"]),
        ]

    def __str__(self):
        return f"{self.chore.name} · {self.due_date} · {self.assignee.display_name}"

    @property
    def is_terminal(self):
        return self.status in TERMINAL_STATUSES

    @property
    def swap_partner(self):
        """The turn this one was traded with, from whichever side holds the link.

        Only one row carries ``swapped_with``; asking either turn should still
        answer, or the trade would only be visible to whoever happened to
        initiate it.
        """
        if self.swapped_with_id:
            return self.swapped_with
        return getattr(self, "swapped_from", None)

    @property
    def was_covered(self):
        """True when someone other than the assignee did it."""
        return (
            self.completed_by_id is not None
            and self.completed_by_id != self.assignee_id
        )

    def deadline(self):
        """The last day this can be done before it counts as missed."""
        return self.due_date + dt.timedelta(days=self.chore.grace_days)


class AwayPeriodQuerySet(models.QuerySet):
    def for_household(self, household):
        return self.filter(member__household=household)

    def covering(self, date):
        return self.filter(start_date__lte=date, end_date__gte=date)


class AwayPeriod(models.Model):
    """Dates a roommate will not be here.

    plan.md §8 requires away handling, and leaves open who gets to mark someone
    away. Answered by allowing both: a roommate declares their own, and an admin
    can enter one on their behalf for the person who is already on a plane.
    ``created_by`` records which of the two it was, so "I never said I was away"
    has an answer.

    Recording only. Its effect on the schedule is task 18.
    """

    member = models.ForeignKey(
        "accounts.Member", on_delete=models.CASCADE, related_name="away_periods"
    )
    start_date = models.DateField()
    end_date = models.DateField(help_text="Inclusive — the last day you are away.")
    reason = models.CharField(max_length=200, blank=True)

    # Nullable so a first-run seed or a management command can create one
    # without inventing an actor.
    created_by = models.ForeignKey(
        "accounts.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="away_periods_declared",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AwayPeriodQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="away_period_ends_after_it_starts",
            ),
        ]

    def __str__(self):
        return f"{self.member.display_name} away {self.start_date} to {self.end_date}"

    def covers(self, date):
        """Is ``date`` inside this absence? Both ends inclusive."""
        return self.start_date <= date <= self.end_date

    @property
    def declared_on_their_behalf(self):
        return self.created_by_id is not None and self.created_by_id != self.member_id


class LogVerb(models.TextChoices):
    COMPLETED = "COMPLETED", "marked done"
    MISSED = "MISSED", "flagged missed"
    SKIPPED_AWAY = "SKIPPED_AWAY", "skipped for an absence"
    REASSIGNED = "REASSIGNED", "handed on"
    SWAPPED = "SWAPPED", "swapped"


class ActivityLog(models.Model):
    """An append-only record of every state change.

    plan.md §4 justifies tracking by the need to settle disputes, and a turn's
    current status alone cannot say who changed it, when, or from what — which
    is exactly what a disagreement turns on. "It says missed but I did it on
    Sunday" is unanswerable from the turn row; it is answerable from here.

    Append-only is enforced in ``save``/``delete`` rather than left to
    convention: a log that can be quietly edited is worth less than no log,
    because it looks authoritative while being wrong.
    """

    class Immutable(Exception):
        """Raised on any attempt to change or remove an entry."""

    household = models.ForeignKey(
        "accounts.Household", on_delete=models.CASCADE, related_name="activity"
    )
    # Null when the system acted rather than a person — overdue marking and
    # absence skipping have no author, and inventing one would be a lie.
    actor = models.ForeignKey(
        "accounts.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity",
    )
    verb = models.CharField(max_length=16, choices=LogVerb.choices)
    turn = models.ForeignKey(
        Turn, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity"
    )
    chore = models.ForeignKey(
        "chores.Chore",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity",
    )
    at = models.DateTimeField(default=timezone.now)
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-at", "-id"]
        indexes = [models.Index(fields=["household", "-at"])]

    def __str__(self):
        who = self.actor.display_name if self.actor else "the system"
        return f"{who} {self.get_verb_display()} {self.chore or self.turn}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise self.Immutable(
                "Activity log entries are append-only and cannot be changed."
            )
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise self.Immutable(
            "Activity log entries are append-only and cannot be deleted."
        )

    @classmethod
    def record(cls, verb, turn, actor=None, **detail):
        """Write one entry for something that just happened to ``turn``."""
        return cls.objects.create(
            household_id=turn.chore.household_id,
            actor=actor,
            verb=verb,
            turn=turn,
            chore=turn.chore,
            detail=detail,
        )
