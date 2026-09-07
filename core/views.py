from django.shortcuts import render


def dashboard(request):
    """Placeholder landing page.

    Task 16 replaces this with the real due/overdue surface. It exists now only
    so sign-in has somewhere to land and so the layout can be seen.
    """
    return render(request, "core/dashboard.html")
