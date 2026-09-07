from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.mixins import admin_required, household_of
from chores.forms import ChoreForm, RotationForm
from chores.models import Chore


def _household_chores(request):
    """architecture.md §6.3: scope first, never trust a PK from the URL."""
    return Chore.objects.for_household(household_of(request))


def chore_list(request):
    """Viewable by every roommate.

    plan.md §7 restricts *editing*, not seeing: a rota nobody but an admin can
    read would defeat the point of a shared list.
    """
    chores = _household_chores(request).order_by("-is_active", "name")
    return render(
        request,
        "chores/chore_list.html",
        {
            "chores": [c for c in chores if c.is_active],
            "archived": [c for c in chores if not c.is_active],
            "can_edit": request.user.is_admin,
        },
    )


def chore_detail(request, pk):
    chore = get_object_or_404(_household_chores(request), pk=pk)
    return render(
        request,
        "chores/chore_detail.html",
        {"chore": chore, "can_edit": request.user.is_admin},
    )


@admin_required
@require_http_methods(["GET", "POST"])
def chore_create(request):
    form = ChoreForm(request.POST or None, household=household_of(request))
    if request.method == "POST" and form.is_valid():
        chore = form.save()
        messages.success(request, f"“{chore.name}” added.")
        return redirect("chore_detail", pk=chore.pk)
    return render(request, "chores/chore_form.html", {"form": form, "chore": None})


@admin_required
@require_http_methods(["GET", "POST"])
def chore_edit(request, pk):
    chore = get_object_or_404(_household_chores(request), pk=pk)
    form = ChoreForm(
        request.POST or None, instance=chore, household=household_of(request)
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"“{chore.name}” updated.")
        return redirect("chore_detail", pk=chore.pk)
    return render(request, "chores/chore_form.html", {"form": form, "chore": chore})


@admin_required
@require_http_methods(["POST"])
def chore_set_active(request, pk):
    """Archive rather than delete, so past turns keep pointing at a real chore."""
    chore = get_object_or_404(_household_chores(request), pk=pk)
    chore.is_active = request.POST.get("active") == "1"
    chore.save(update_fields=["is_active"])
    if chore.is_active:
        messages.success(request, f"“{chore.name}” is back in the rota.")
    else:
        messages.success(
            request,
            f"“{chore.name}” archived. Past turns are kept; no new ones will be made.",
        )
    return redirect("chore_list")


def chore_rotation(request, pk):
    """Who does this chore, and in what order.

    Readable by every roommate — plan.md §7 restricts changing the rota, not
    seeing your place in it. The POST branch is admin-only.
    """
    chore = get_object_or_404(_household_chores(request), pk=pk)
    can_edit = request.user.is_admin

    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied(
                "Only a household admin can change a rotation. Ask one of them."
            )
        form = RotationForm(request.POST, chore=chore)
        if form.is_valid():
            order = form.save()
            messages.success(
                request,
                f"Rotation for “{chore.name}” saved — {len(order)} in the rota."
                if order
                else f"“{chore.name}” now has nobody in its rotation.",
            )
            return redirect("chore_rotation", pk=chore.pk)
    else:
        form = RotationForm(chore=chore)

    return render(
        request,
        "chores/chore_rotation.html",
        {
            "chore": chore,
            "form": form,
            "can_edit": can_edit,
            "rotation": chore.rotation,
        },
    )
