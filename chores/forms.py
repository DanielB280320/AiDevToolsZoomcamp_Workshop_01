from django import forms

from chores.models import Chore


class ChoreForm(forms.ModelForm):
    class Meta:
        model = Chore
        fields = [
            "name",
            "description",
            "cadence_unit",
            "cadence_interval",
            "anchor_date",
            "grace_days",
        ]
        labels = {
            "anchor_date": "First due date",
            "cadence_interval": "Repeat every",
            "cadence_unit": "Unit",
            "grace_days": "Grace period (days)",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "anchor_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, household=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household or getattr(self.instance, "household_id", None)
        self.fields["anchor_date"].input_formats = ["%Y-%m-%d"]

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        household = self.household
        clash = Chore.objects.filter(household=household, name__iexact=name)
        if self.instance.pk:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("There's already a chore with that name.")
        return name

    def save(self, commit=True):
        chore = super().save(commit=False)
        if not chore.household_id:
            chore.household = self.household
        if commit:
            chore.save()
        return chore
