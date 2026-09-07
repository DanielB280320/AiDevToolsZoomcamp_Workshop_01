from django import forms

from schedule.models import AwayPeriod


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
