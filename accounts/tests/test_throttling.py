"""architecture.md §6: five failures in fifteen minutes pauses sign-in.

Without this, plan.md §5's six-digit PIN is a million guesses against an
endpoint that answers as fast as it can — hours, not centuries.
"""

import datetime as dt

import pytest
from django.test import RequestFactory

from accounts.models import LoginAttempt, purge_old_login_attempts
from accounts.services import GENERIC_FAILURE, LOCKED_OUT, attempt_login, client_ip
from conftest import DEFAULT_PIN

pytestmark = pytest.mark.django_db


@pytest.fixture
def request_from():
    factory = RequestFactory()

    def _request(ip="198.51.100.7"):
        req = factory.post("/login/")
        req.META["REMOTE_ADDR"] = ip
        return req

    return _request


def fail_n_times(request, name, n):
    for _ in range(n):
        attempt_login(request, name, "000000")


class TestLockout:
    def test_four_failures_do_not_lock(self, roommate, request_from):
        req = request_from()
        fail_n_times(req, "Ana", 4)
        assert attempt_login(req, "Ana", DEFAULT_PIN).ok

    def test_fifth_failure_locks(self, roommate, request_from):
        req = request_from()
        fail_n_times(req, "Ana", 5)
        result = attempt_login(req, "Ana", DEFAULT_PIN)
        assert not result.ok
        assert result.locked_out
        assert result.error == LOCKED_OUT

    def test_correct_pin_is_refused_while_locked(self, roommate, request_from):
        req = request_from()
        fail_n_times(req, "Ana", 5)
        assert not attempt_login(req, "Ana", DEFAULT_PIN).ok

    def test_lockout_lifts_after_the_window(self, roommate, request_from, frozen_clock):
        req = request_from()
        fail_n_times(req, "Ana", 5)
        assert not attempt_login(req, "Ana", DEFAULT_PIN).ok

        frozen_clock.tick(LoginAttempt.WINDOW + dt.timedelta(seconds=1))
        assert attempt_login(req, "Ana", DEFAULT_PIN).ok

    def test_a_success_clears_the_failure_count(self, roommate, request_from):
        req = request_from()
        fail_n_times(req, "Ana", 4)
        assert attempt_login(req, "Ana", DEFAULT_PIN).ok

        # Four more should be survivable again, not one-from-lockout.
        fail_n_times(req, "Ana", 4)
        assert attempt_login(req, "Ana", DEFAULT_PIN).ok


class TestScoping:
    """The lockout must punish the guesser, not the household."""

    def test_one_roommate_lockout_does_not_lock_another(self, members, request_from):
        req = request_from()
        fail_n_times(req, "Ana", 5)
        assert attempt_login(req, "Ben", DEFAULT_PIN).ok

    def test_lockout_is_per_ip(self, roommate, request_from):
        fail_n_times(request_from("198.51.100.7"), "Ana", 5)
        assert attempt_login(request_from("203.0.113.9"), "Ana", DEFAULT_PIN).ok


class TestNoEnumeration:
    """architecture.md §6: generic failure messages.

    If a wrong PIN, an unknown name and a deactivated member read differently,
    the form becomes a directory of who lives here.
    """

    def test_wrong_pin_and_unknown_name_read_identically(self, roommate, request_from):
        wrong_pin = attempt_login(request_from(), "Ana", "000000")
        unknown = attempt_login(request_from("203.0.113.9"), "Nobody", "000000")
        assert wrong_pin.error == unknown.error == GENERIC_FAILURE

    def test_deactivated_member_reads_identically(self, members, request_from):
        departed = members[-1]
        departed.is_active = False
        departed.save()
        result = attempt_login(request_from(), departed.display_name, DEFAULT_PIN)
        assert result.error == GENERIC_FAILURE

    def test_unknown_names_are_throttled_too(self, members, request_from):
        """Throttling only real names would make the lockout itself an oracle."""
        req = request_from()
        fail_n_times(req, "Nobody", 5)
        assert LoginAttempt.is_locked_out("Nobody", "198.51.100.7")


class TestClientIp:
    def test_prefers_forwarded_for(self):
        req = RequestFactory().post("/login/")
        req.META["REMOTE_ADDR"] = "10.0.0.1"
        req.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.9, 10.0.0.1"
        assert client_ip(req) == "203.0.113.9"

    def test_falls_back_to_remote_addr(self, request_from):
        assert client_ip(request_from("192.0.2.4")) == "192.0.2.4"

    def test_handles_no_request(self):
        assert client_ip(None) is None


def test_locked_until_reports_when_it_lifts(roommate, request_from, frozen_clock):
    req = request_from()
    assert LoginAttempt.locked_until("Ana", "198.51.100.7") is None
    fail_n_times(req, "Ana", 5)
    lifts = LoginAttempt.locked_until("Ana", "198.51.100.7")
    assert lifts is not None


def test_purge_drops_only_old_attempts(roommate, request_from, frozen_clock):
    req = request_from()
    fail_n_times(req, "Ana", 3)
    frozen_clock.tick(LoginAttempt.WINDOW * 5)
    fail_n_times(req, "Ana", 2)

    assert purge_old_login_attempts() == 3
    assert LoginAttempt.objects.count() == 2
