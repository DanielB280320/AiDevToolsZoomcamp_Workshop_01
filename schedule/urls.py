from django.urls import path

from schedule import views

urlpatterns = [
    path("turns/<int:pk>/done/", views.turn_complete, name="turn_complete"),
]
