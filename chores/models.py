import datetime as dt

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.urls import reverse


class Cadence(models.TextChoices):
    DAY = "DAY", "days"
    WEEK = "WEEK", "weeks"
    MONTH = "MONTH", "months"


def add_months(date, months):
    """Step whole months, clamping to the end of a short month.

    31 January plus one month is 28 February, not 3 March. Rolling over would
    quietly drift a monthly chore forward through the year, and would put two
    turns in March for anything anchored on the 29th to 31st.
    """
    month_index = date.month - 1 + months
    year = date.year + month_index // 12
    month = month_index % 12 + 1
    last_day = (
        dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)
    ).day
    return dt.date(year, month, min(date.day, last_day))


class ChoreQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def for_household(self, household):
        return self.filter(household=household)


class Chore(models.Model):
    """One recurring job, with its own frequency.

    plan.md §2 notes that different chores may not share a cadence, so
    frequency belongs to the chore rather than to the household — which answers
    the spec's open question about whether cadence is uniform. The bins can run
    weekly while the oven runs monthly.
    """

    household = models.ForeignKey(
        "accounts.Household", on_delete=models.CASCADE, related_name="chores"
    )
    name = models.CharField(max_length=100)
    description = models.TextField(
        blank=True,
        help_text=(
            "What doing it properly involves. Optional, but it settles arguments."
        ),
    )

    cadence_unit = models.CharField(
        max_length=8, choices=Cadence.choices, default=Cadence.WEEK
    )
    cadence_interval = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(52)],
        help_text="Every N units. 2 with 'weeks' means every fortnight.",
    )

    anchor_date = models.DateField(
        help_text="The due date of the first turn. Everything else steps from here.",
    )

    grace_days = models.PositiveSmallIntegerField(
        default=1,
        validators=[MaxValueValidator(30)],
        help_text=(
            "Days after the due date before it counts as missed. A little slack "
            "keeps the record honest about people who did it that evening."
        ),
    )

    # Archived rather than deleted, so plan.md §4's history keeps pointing at a
    # real chore. A deleted chore would cascade its turns away and take the
    # record of who did what with it.
    is_active = models.BooleanField(
        default=True,
        verbose_name="in use",
        help_text="Uncheck to archive. Past turns are kept; no new ones are made.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    objects = ChoreQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "name"], name="unique_chore_name_per_household"
            ),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("chore_detail", args=[self.pk])

    @property
    def cadence_label(self):
        if self.cadence_interval == 1:
            return {"DAY": "Daily", "WEEK": "Weekly", "MONTH": "Monthly"}[
                self.cadence_unit
            ]
        unit = self.get_cadence_unit_display()
        return f"Every {self.cadence_interval} {unit}"

    def advance(self, date, cycles=1):
        """The due date ``cycles`` steps after ``date``."""
        steps = self.cadence_interval * cycles
        if self.cadence_unit == Cadence.DAY:
            return date + dt.timedelta(days=steps)
        if self.cadence_unit == Cadence.WEEK:
            return date + dt.timedelta(weeks=steps)
        return add_months(date, steps)

    @property
    def rotation(self):
        """The roommates in this chore's rotation, in their stored order."""
        return [slot.member for slot in self.rotation_slots.select_related("member")]

    @transaction.atomic
    def set_rotation(self, members):
        """Replace this chore's rotation with ``members``, in the order given.

        Positions are rewritten dense from zero on every save rather than
        patched in place, so there is no gap to reason about after someone is
        taken out of the middle of a rota. Rewriting is safe because a slot
        carries no history: plan.md §4's record lives on the turn rows, which
        snapshot their assignee at generation time and are never rewritten from
        the rotation (architecture.md §4).
        """
        self.rotation_slots.all().delete()
        RotationSlot.objects.bulk_create(
            [
                RotationSlot(chore=self, member=member, position=index)
                for index, member in enumerate(members)
            ]
        )

    def due_date_for_cycle(self, cycle_index):
        """Due date of cycle N, counted from the anchor.

        Computed from the anchor every time rather than by repeatedly adding to
        the previous result: for monthly chores the two differ, because clamping
        31 January to 28 February would otherwise pin every later month to the
        28th.
        """
        return self.advance(self.anchor_date, cycle_index)


class RotationSlot(models.Model):
    """One roommate's place in one chore's rotation.

    An explicit through model rather than reusing a household-wide member
    order: plan.md §2 wants the bins and the bathroom to be able to run through
    people differently, which a single shared order cannot express.

    ``position`` is stored, not derived. Deriving it from ``joined_on`` or from
    the display name would make the order an accident of when someone moved in
    or what they are called, and would silently reshuffle a rota when a new
    roommate arrives.
    """

    chore = models.ForeignKey(
        Chore, on_delete=models.CASCADE, related_name="rotation_slots"
    )
    member = models.ForeignKey(
        "accounts.Member", on_delete=models.CASCADE, related_name="rotation_slots"
    )
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(
                fields=["chore", "position"], name="unique_position_per_chore"
            ),
            models.UniqueConstraint(
                fields=["chore", "member"], name="unique_member_per_chore"
            ),
        ]

    def __str__(self):
        return f"{self.chore.name} #{self.position}: {self.member.display_name}"
