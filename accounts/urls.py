from django.urls import path

from accounts import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("roommates/", views.member_list, name="member_list"),
    path("roommates/add/", views.member_add, name="member_add"),
    path("roommates/<int:pk>/pin/", views.member_reset_pin, name="member_reset_pin"),
    path(
        "roommates/<int:pk>/admin/",
        views.member_toggle_admin,
        name="member_toggle_admin",
    ),
    path(
        "roommates/<int:pk>/active/",
        views.member_set_active,
        name="member_set_active",
    ),
]
