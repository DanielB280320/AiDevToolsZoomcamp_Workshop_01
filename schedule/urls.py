from django.urls import path

from schedule import views

urlpatterns = [
    path("turns/<int:pk>/done/", views.turn_complete, name="turn_complete"),
    path("away/", views.away_list, name="away_list"),
    path("away/<int:pk>/cancel/", views.away_delete, name="away_delete"),
]
