from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from accounts.models import Household, LoginAttempt, Member


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ["name", "timezone", "member_count", "created_at"]
    readonly_fields = ["created_at"]


@admin.register(Member)
class MemberAdmin(UserAdmin):
    """Operator-only (architecture.md §6).

    The roommate-facing screens for managing the member list are task 7; this is
    the escape hatch for whoever runs the deployment.
    """

    ordering = ["display_name"]
    list_display = ["display_name", "household", "is_admin", "is_active", "joined_on"]
    list_filter = ["is_admin", "is_active", "household"]
    search_fields = ["display_name"]

    fieldsets = [
        (None, {"fields": ["display_name", "password"]}),
        ("Household", {"fields": ["household", "joined_on"]}),
        (
            "Permissions",
            {
                "fields": [
                    "is_admin",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ]
            },
        ),
        ("Important dates", {"fields": ["last_login"]}),
    ]

    add_fieldsets = [
        (
            None,
            {
                "classes": ["wide"],
                "fields": ["display_name", "household", "password1", "password2"],
            },
        ),
    ]


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    """Read-only: the throttling record is evidence, not something to edit."""

    list_display = ["display_name", "ip_address", "succeeded", "attempted_at"]
    list_filter = ["succeeded", "attempted_at"]
    search_fields = ["display_name", "ip_address"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
