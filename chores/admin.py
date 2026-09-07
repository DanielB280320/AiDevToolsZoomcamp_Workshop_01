from django.contrib import admin

from chores.models import Chore


@admin.register(Chore)
class ChoreAdmin(admin.ModelAdmin):
    list_display = ["name", "household", "cadence_label", "anchor_date", "is_active"]
    list_filter = ["is_active", "cadence_unit", "household"]
    search_fields = ["name"]
