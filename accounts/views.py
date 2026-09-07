from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from accounts.forms import LoginForm, MemberForm, SetPinForm
from accounts.mixins import admin_required, household_of
from accounts.models import Member
from accounts.services import attempt_login


def _safe_redirect_target(request):
    """Honour ?next= only when it points back at this site."""
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(
        url=target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return reverse("dashboard")


@login_not_required
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(_safe_redirect_target(request))

    form = LoginForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        result = attempt_login(
            request,
            form.cleaned_data["display_name"],
            form.cleaned_data["pin"],
        )
        if result.ok:
            auth_login(request, result.member, backend="accounts.backends.PinBackend")
            # A fresh session id on sign-in; Django's login() cycles the key,
            # which is what stops a fixated session surviving the transition.
            return redirect(_safe_redirect_target(request))
        form.add_error(None, result.error)

    return render(
        request,
        "accounts/login.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


@never_cache
@require_http_methods(["POST"])
def logout_view(request):
    """POST only: a GET sign-out can be triggered by any image tag on any page."""
    auth_logout(request)
    messages.success(request, "You're signed out.")
    return redirect("login")


# --- Roommate list management (plan.md §1, §5, §7) -------------------------


def _household_members(request):
    """Always scoped to the signed-in roommate's household.

    Never ``Member.objects.get(pk=...)`` straight from a URL: filtering by
    household first is what stops a guessed id reaching another house.
    """
    return Member.objects.filter(household=household_of(request))


@admin_required
def member_list(request):
    members = _household_members(request).order_by("-is_active", "display_name")
    return render(
        request,
        "accounts/member_list.html",
        {
            "members": members,
            "active_count": sum(1 for m in members if m.is_active),
        },
    )


@admin_required
@require_http_methods(["GET", "POST"])
def member_add(request):
    form = MemberForm(request.POST or None, household=household_of(request))
    if request.method == "POST" and form.is_valid():
        member = form.save()
        messages.success(
            request,
            f"{member.display_name} can now sign in. Give them their PIN in person.",
        )
        return redirect("member_list")
    return render(request, "accounts/member_form.html", {"form": form})


@admin_required
@require_http_methods(["GET", "POST"])
def member_reset_pin(request, pk):
    """plan.md §5 chose no email, so PIN recovery cannot be self-service.

    An admin sets a new one instead — which is the spec's open question about
    forgotten PINs, answered.
    """
    member = get_object_or_404(_household_members(request), pk=pk)
    form = SetPinForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        member.set_pin(form.cleaned_data["pin"])
        member.save(update_fields=["password"])
        messages.success(request, f"{member.display_name}'s PIN has been reset.")
        return redirect("member_list")
    return render(
        request, "accounts/member_reset_pin.html", {"form": form, "member": member}
    )


@admin_required
@require_http_methods(["POST"])
def member_toggle_admin(request, pk):
    member = get_object_or_404(_household_members(request), pk=pk)

    if member.is_admin and not _other_admins(request, member).exists():
        # A household with no admin can never add a chore or reset a PIN again
        # without someone reaching the database directly.
        messages.error(
            request,
            "This is the only admin. Make someone else an admin first.",
        )
        return redirect("member_list")

    member.is_admin = not member.is_admin
    member.save(update_fields=["is_admin"])
    granted = "is now an admin" if member.is_admin else "is no longer an admin"
    messages.success(request, f"{member.display_name} {granted}.")
    return redirect("member_list")


@admin_required
@require_http_methods(["POST"])
def member_set_active(request, pk):
    """Soft-remove, never delete: plan.md §4's history has to outlive a move-out."""
    member = get_object_or_404(_household_members(request), pk=pk)
    activating = request.POST.get("active") == "1"

    if (
        not activating
        and member.is_admin
        and not _other_admins(request, member).exists()
    ):
        messages.error(
            request,
            "This is the only admin. Make someone else an admin first.",
        )
        return redirect("member_list")

    member.is_active = activating
    member.save(update_fields=["is_active"])
    if activating:
        messages.success(request, f"{member.display_name} is back on the rota.")
    else:
        messages.success(
            request,
            f"{member.display_name} has moved out. Their history is kept, and "
            "they will not be given new turns.",
        )
    return redirect("member_list")


def _other_admins(request, member):
    return (
        _household_members(request)
        .filter(is_admin=True, is_active=True)
        .exclude(pk=member.pk)
    )
