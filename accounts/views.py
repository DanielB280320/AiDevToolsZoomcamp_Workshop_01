from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from accounts.forms import LoginForm
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
