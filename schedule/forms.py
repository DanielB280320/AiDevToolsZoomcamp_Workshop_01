from django import forms
from django.db import models

from schedule.models import SETTLED_CHOICES, AwayPeriod, Turn, TurnStatus
from schedule.services.transitions import TransitionRefused, swap_turns


class AwayPeriodForm(forms.ModelForm):
    """Declare an absence, for yourself or — if you are an admin — for someone else.

    Who may be picked is decided here rather than in the view, because it is the
    same rule in both directions: the member field only offers people the actor
    is allowed to speak for. A non-admin gets a list of exactly one person, so
    there is nothing to tamper with in the POST.
    """

    class Meta:
        model = AwayPeriod
        fields = ["member", "start_date", "end_date", "reason"]
        labels = {
            "member": "Who is away",
            "start_date": "First day away",
            "end_date": "Last day away",
        }
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "reason": forms.TextInput(
                attrs={"placeholder": "Optional — holiday, work trip, …"}
            ),
        }

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor

        household_members = actor.household.members.filter(is_active=True)
        if actor.is_admin:
            self.fields["member"].queryset = household_members.order_by("display_name")
        else:
            # plan.md §8 lets a roommate declare their own absence. It does not
            # let them declare one for someone else -- that is an admin's job,
            # and quietly booking a flatmate off the rota would be a way to
            # dodge a turn.
            self.fields["member"].queryset = household_members.filter(pk=actor.pk)
            self.fields["member"].initial = actor
            self.fields["member"].disabled = True

        for name in ("start_date", "end_date"):
            self.fields[name].input_formats = ["%Y-%m-%d"]

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            raise forms.ValidationError(
                "The last day away cannot be before the first one."
            )
        return cleaned

    def save(self, commit=True):
        away = super().save(commit=False)
        # Recorded, not inferred: plan.md §8's open question is answered by
        # allowing both, which is only meaningful if the record says which.
        away.created_by = self.actor
        if commit:
            away.save()
        return away


class SwapForm(forms.Form):
    """Offer one of your turns in exchange for someone else's.

    Both sides are constrained to what is actually tradeable — your own pending
    turns, and other people's — so the choice is made from a list rather than
    validated after the fact.
    """

    mine = forms.ModelChoiceField(queryset=Turn.objects.none(), label="Your turn")
    theirs = forms.ModelChoiceField(queryset=Turn.objects.none(), label="Swap it for")

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        tradeable = (
            Turn.objects.for_household(actor.household)
            # Both sides of a trade, not just the row that happens to carry
            # the link: the partner has swapped_from set instead, and offering
            # it would show a choice the service is only going to refuse.
            .filter(
                status=TurnStatus.PENDING,
                swapped_with__isnull=True,
                swapped_from__isnull=True,
            )
            .select_related("chore", "assignee")
            .order_by("due_date")
        )
        self.fields["mine"].queryset = tradeable.filter(assignee=actor)
        self.fields["theirs"].queryset = tradeable.exclude(assignee=actor)

    def clean(self):
        cleaned = super().clean()
        mine, theirs = cleaned.get("mine"), cleaned.get("theirs")
        if mine and theirs:
            try:
                swap_turns(mine, theirs)
            except TransitionRefused as refusal:
                raise forms.ValidationError(str(refusal)) from refusal
        return cleaned


class HistoryFilterForm(forms.Form):
    """Narrow the history down. Every field optional; blank means "everything".

    A GET form, so a filtered view is a URL someone can paste into the group
    chat — which is exactly what happens when the disagreement is the reason
    anybody opened this screen.
    """

    member = forms.ModelChoiceField(
        queryset=None, required=False, empty_label="Everyone", label="Roommate"
    )
    chore = forms.ModelChoiceField(
        queryset=None, required=False, empty_label="All chores"
    )
    status = forms.ChoiceField(required=False, choices=[], label="Outcome")
    since = forms.DateField(
        required=False,
        label="From",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    until = forms.DateField(
        required=False,
        label="To",
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )

    def __init__(self, *args, household, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member"].queryset = household.members.order_by("display_name")
        self.fields["chore"].queryset = household.chores.order_by("name")
        self.fields["status"].choices = [("", "Any outcome"), *SETTLED_CHOICES]
        for name in ("since", "until"):
            self.fields[name].input_formats = ["%Y-%m-%d"]

    def clean(self):
        cleaned = super().clean()
        since, until = cleaned.get("since"), cleaned.get("until")
        if since and until and until < since:
            raise forms.ValidationError("The end date is before the start date.")
        return cleaned

    def narrow(self, turns):
        """Apply whatever the roommate actually filled in."""
        if not self.is_valid():
            return turns
        data = self.cleaned_data
        if data.get("member"):
            # Their turn *or* their work: someone who covered for a flatmate
            # should show up when you filter by their name.
            turns = turns.filter(
                models.Q(assignee=data["member"])
                | models.Q(completed_by=data["member"])
            )
        if data.get("chore"):
            turns = turns.filter(chore=data["chore"])
        if data.get("status"):
            turns = turns.filter(status=data["status"])
        if data.get("since"):
            turns = turns.filter(due_date__gte=data["since"])
        if data.get("until"):
            turns = turns.filter(due_date__lte=data["until"])
        return turns
