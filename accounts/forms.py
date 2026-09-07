from django import forms

from accounts.validators import PIN_MAX_LENGTH, PIN_MIN_LENGTH, validate_pin


class PinField(forms.CharField):
    """A PIN input that behaves like one on a phone.

    inputmode="numeric" brings up the number pad; autocomplete tells a password
    manager this is a one-time-ish secret rather than something to fill from a
    saved address.
    """

    def __init__(self, label="PIN", **kwargs):
        kwargs.setdefault("min_length", PIN_MIN_LENGTH)
        kwargs.setdefault("max_length", PIN_MAX_LENGTH)
        kwargs.setdefault(
            "widget",
            forms.PasswordInput(
                attrs={
                    "inputmode": "numeric",
                    "pattern": "[0-9]*",
                    "autocomplete": "current-password",
                    "placeholder": "••••••",
                }
            ),
        )
        super().__init__(label=label, **kwargs)


class LoginForm(forms.Form):
    """Name and PIN (plan.md §5).

    The name is a free-text field rather than a dropdown of roommates: a picker
    would publish the household's member list to anyone who loads the page.
    """

    display_name = forms.CharField(
        label="Your name",
        max_length=50,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "username",
                "autocapitalize": "words",
                "autofocus": True,
                "placeholder": "e.g. Ana",
            }
        ),
    )
    pin = PinField()

    def clean_display_name(self):
        return self.cleaned_data["display_name"].strip()

    def clean_pin(self):
        # Only shape is checked here. Whether the PIN is *right* is the
        # backend's business, and must not be distinguishable from a wrong name.
        return self.cleaned_data["pin"].strip()


class SetPinForm(forms.Form):
    """Used by task 7's admin PIN reset and task 22's bootstrap."""

    pin = PinField(label="New PIN", validators=[validate_pin])
    pin_confirm = PinField(
        label="Confirm new PIN",
        widget=forms.PasswordInput(
            attrs={"inputmode": "numeric", "autocomplete": "new-password"}
        ),
    )

    def clean(self):
        cleaned = super().clean()
        pin, confirm = cleaned.get("pin"), cleaned.get("pin_confirm")
        if pin and confirm and pin != confirm:
            self.add_error("pin_confirm", "The two PINs don't match.")
        return cleaned
