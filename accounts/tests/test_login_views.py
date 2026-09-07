"""plan.md §3: a roommate signs in from a phone, laptop or shared tablet."""

import pytest
from django.urls import reverse
from django.utils.html import escape

from accounts.models import LoginAttempt
from accounts.services import GENERIC_FAILURE, LOCKED_OUT
from conftest import DEFAULT_PIN

pytestmark = pytest.mark.django_db


@pytest.fixture
def login_url():
    return reverse("login")


class TestSignIn:
    def test_page_is_reachable_without_signing_in(self, client, login_url):
        response = client.get(login_url)
        assert response.status_code == 200

    def test_correct_credentials_sign_in_and_land_on_the_dashboard(
        self, roommate, client, login_url
    ):
        response = client.post(
            login_url, {"display_name": "Ana", "pin": DEFAULT_PIN}, follow=True
        )
        assert response.status_code == 200
        assert response.context["user"].is_authenticated
        assert response.request["PATH_INFO"] == reverse("dashboard")

    def test_wrong_pin_stays_on_the_form_with_a_generic_message(
        self, roommate, client, login_url
    ):
        response = client.post(login_url, {"display_name": "Ana", "pin": "000000"})
        assert response.status_code == 200
        assert not response.context["user"].is_authenticated
        assert escape(GENERIC_FAILURE) in response.content.decode()

    def test_unknown_name_reads_the_same_as_a_wrong_pin(
        self, members, client, login_url
    ):
        response = client.post(login_url, {"display_name": "Ghost", "pin": "000000"})
        assert escape(GENERIC_FAILURE) in response.content.decode()

    def test_short_pin_is_rejected_before_it_reaches_the_backend(
        self, roommate, client, login_url
    ):
        client.post(login_url, {"display_name": "Ana", "pin": "12"})
        assert LoginAttempt.objects.count() == 0

    def test_lockout_is_reported_on_the_form(self, roommate, client, login_url):
        for _ in range(5):
            client.post(login_url, {"display_name": "Ana", "pin": "000000"})
        response = client.post(login_url, {"display_name": "Ana", "pin": DEFAULT_PIN})
        assert escape(LOCKED_OUT) in response.content.decode()

    def test_already_signed_in_is_sent_onward(self, roommate, client, login_url):
        client.force_login(roommate)
        response = client.get(login_url)
        assert response.status_code == 302
        assert response.url == reverse("dashboard")


class TestNextRedirect:
    def test_honours_a_local_next(self, roommate, client, login_url):
        response = client.post(
            login_url,
            {"display_name": "Ana", "pin": DEFAULT_PIN, "next": "/?welcome=1"},
        )
        assert response.url == "/?welcome=1"

    def test_ignores_an_offsite_next(self, roommate, client, login_url):
        """An open redirect on a sign-in form is a phishing primitive."""
        response = client.post(
            login_url,
            {
                "display_name": "Ana",
                "pin": DEFAULT_PIN,
                "next": "https://evil.example.com/harvest",
            },
        )
        assert response.url == reverse("dashboard")


class TestSignOut:
    def test_post_signs_out(self, roommate, client):
        client.force_login(roommate)
        response = client.post(reverse("logout"), follow=True)
        assert not response.context["user"].is_authenticated

    def test_get_is_refused(self, roommate, client):
        """A GET sign-out can be fired by any image tag on any page."""
        client.force_login(roommate)
        response = client.get(reverse("logout"))
        assert response.status_code == 405


class TestEverythingElseIsPrivate:
    def test_dashboard_requires_sign_in(self, client):
        response = client.get(reverse("dashboard"))
        assert response.status_code == 302
        assert reverse("login") in response.url

    def test_dashboard_is_reachable_once_signed_in(self, roommate, client):
        client.force_login(roommate)
        assert client.get(reverse("dashboard")).status_code == 200

    def test_the_next_parameter_survives_the_bounce(self, roommate, client):
        response = client.get(reverse("dashboard") + "?filter=mine")
        client.force_login(roommate)
        assert "next=" in response.url


class TestResponsiveShell:
    def test_pages_declare_a_mobile_viewport(self, roommate, client):
        """plan.md §3 chose a browser app so nobody installs anything; that
        promise only holds if it is usable on the phone in their hand."""
        client.force_login(roommate)
        body = client.get(reverse("dashboard")).content.decode()
        assert 'name="viewport"' in body
        assert "width=device-width" in body

    def test_signed_out_pages_have_no_sign_out_control(self, client, login_url):
        assert "Sign out" not in client.get(login_url).content.decode()
