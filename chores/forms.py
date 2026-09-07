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


class RotationForm(forms.Form):
    """Set a chore's rotation by giving each roommate a position.

    One numeric box per roommate, blank meaning "not in this rota". Positions
    are the order the admin types, not the numbers themselves: 10/20/30 is a
    valid way to say first/second/third, and is normalised to 0/1/2 on save.
    That keeps reordering possible without JavaScript — plan.md §3 chose a
    browser app so nobody has to install anything, and a drag handle that needs
    a working pointer is a poor fit for the shared tablet in the kitchen.
    """

    def __init__(self, *args, chore, **kwargs):
        super().__init__(*args, **kwargs)
        self.chore = chore
        # Only this household's active roommates. A departed one keeps their
        # past turns (plan.md §1) but has no place in a future rota.
        self.candidates = list(
            chore.household.members.filter(is_active=True).order_by("display_name")
        )
        current = {slot.member_id: slot.position for slot in chore.rotation_slots.all()}
        for member in self.candidates:
            self.fields[self.field_name(member)] = forms.IntegerField(
                required=False,
                min_value=0,
                label=member.display_name,
                initial=current.get(member.pk),
                widget=forms.NumberInput(attrs={"class": "pos", "placeholder": "—"}),
            )

    @staticmethod
    def field_name(member):
        return f"position_{member.pk}"

    def rows(self):
        """(member, bound field) pairs, for the template."""
        return [(m, self[self.field_name(m)]) for m in self.candidates]

    def clean(self):
        cleaned = super().clean()
        placed = [
            (cleaned.get(self.field_name(m)), m)
            for m in self.candidates
            if cleaned.get(self.field_name(m)) is not None
        ]
        seen = {}
        for position, member in placed:
            if position in seen:
                raise forms.ValidationError(
                    f"{seen[position].display_name} and {member.display_name} "
                    f"are both at position {position}. Give everyone a different one."
                )
            seen[position] = member
        self.ordered_members = [
            member for _, member in sorted(placed, key=lambda p: p[0])
        ]
        return cleaned

    def save(self):
        self.chore.set_rotation(self.ordered_members)
        return self.ordered_members
