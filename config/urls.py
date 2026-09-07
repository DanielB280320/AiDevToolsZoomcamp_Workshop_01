from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Operator escape hatch only (architecture.md §6). The roommate-facing chore
    # screens are separate and land in later tasks.
    path("admin/", admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]
