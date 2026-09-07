"""History and fairness (task 21).

plan.md §4 calls for a history log and for surfacing who missed which chores;
this is the screen where both are actually read. It is the screen people open
when they disagree, which is why the tests care about what it *says* as much as
what it filters.
"""

import datetime as dt

import pytest
from django.urls import reverse

from accounts.models import Household, Member
from chores.models import Chore
from schedule.models import Turn, TurnStatus
from schedule.views import HISTORY_PAGE_SIZE

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 1, 5)


@pytest.fixture(autouse=True)
def _clock(frozen_clock):
    """Turns are created relative to a fixed today."""


@pytest.fixture
def bins(household):
    return Chore.objects.create(
        household=household, name="Bins", anchor_date=TODAY, grace_days=1
    )


@pytest.fixture
def bathroom(household):
    return Chore.objects.create(
        household=household, name="Bathroom", anchor_date=TODAY, grace_days=1
    )


@pytest.fixture
def make_turn(bins, members):
    def _make_turn(
        due, assignee=None, *, status=TurnStatus.COMPLETED, chore=None, **extra
    ):
        chore = chore or bins
        return Turn.objects.create(
            chore=chore,
            assignee=assignee or members[0],
            cycle_index=chore.turns.count(),
            period_start=due,
            due_date=due,
            status=status,
            **extra,
        )

    return _make_turn


@pytest.fixture
def as_ana(client, members):
    client.force_login(members[0])
    return client


def rows(response):
    return list(response.context["page"])


def summary_for(response, name):
    return next(
        (r for r in response.context["summary"] if r["member"].display_name == name),
        None,
    )


# Criterion 1 — the settled turns, paginated.


def test_completed_missed_and_skipped_all_appear(as_ana, make_turn, members):
    done = make_turn(dt.date(2026, 1, 1), members[0])
    missed = make_turn(dt.date(2026, 1, 2), members[1], status=TurnStatus.MISSED)
    away = make_turn(dt.date(2026, 1, 3), members[2], status=TurnStatus.SKIPPED_AWAY)

    assert set(rows(as_ana.get(reverse("history")))) == {done, missed, away}


def test_a_pending_turn_is_not_history_yet(as_ana, make_turn, members):
    make_turn(dt.date(2026, 2, 1), members[0], status=TurnStatus.PENDING)

    assert rows(as_ana.get(reverse("history"))) == []


def test_the_newest_turn_comes_first(as_ana, make_turn, members):
    older = make_turn(dt.date(2025, 12, 1), members[0])
    newer = make_turn(dt.date(2026, 1, 1), members[0])

    assert rows(as_ana.get(reverse("history"))) == [newer, older]


def test_the_list_is_paginated(as_ana, make_turn, members):
    for day in range(1, HISTORY_PAGE_SIZE + 6):
        make_turn(dt.date(2025, 11, 1) + dt.timedelta(days=day), members[0])

    first = as_ana.get(reverse("history"))
    assert len(rows(first)) == HISTORY_PAGE_SIZE
    assert first.context["page"].has_next() is True

    second = as_ana.get(reverse("history"), {"page": "2"})
    assert len(rows(second)) == 5


def test_a_filter_survives_paging(as_ana, make_turn, members, bathroom):
    for day in range(1, HISTORY_PAGE_SIZE + 3):
        make_turn(dt.date(2025, 11, 1) + dt.timedelta(days=day), members[0])
    make_turn(dt.date(2026, 1, 1), members[1], chore=bathroom)

    response = as_ana.get(reverse("history"), {"chore": str(bathroom.pk)})

    assert "chore=" in response.context["querystring"]
    assert len(rows(response)) == 1


# Criterion 2 — the filters.


def test_filtering_by_roommate(as_ana, make_turn, members):
    hers = make_turn(dt.date(2026, 1, 1), members[0])
    make_turn(dt.date(2026, 1, 2), members[1])

    response = as_ana.get(reverse("history"), {"member": str(members[0].pk)})

    assert rows(response) == [hers]


def test_filtering_by_roommate_also_finds_turns_they_covered(
    as_ana, make_turn, members
):
    """Someone who covered should show up when you filter by their name."""
    covered = make_turn(dt.date(2026, 1, 1), members[0], completed_by=members[3])

    response = as_ana.get(reverse("history"), {"member": str(members[3].pk)})

    assert rows(response) == [covered]


def test_filtering_by_chore(as_ana, make_turn, members, bathroom):
    make_turn(dt.date(2026, 1, 1), members[0])
    theirs = make_turn(dt.date(2026, 1, 2), members[1], chore=bathroom)

    response = as_ana.get(reverse("history"), {"chore": str(bathroom.pk)})

    assert rows(response) == [theirs]


def test_filtering_by_outcome(as_ana, make_turn, members):
    make_turn(dt.date(2026, 1, 1), members[0])
    missed = make_turn(dt.date(2026, 1, 2), members[1], status=TurnStatus.MISSED)

    response = as_ana.get(reverse("history"), {"status": "MISSED"})

    assert rows(response) == [missed]


def test_filtering_by_date_range(as_ana, make_turn, members):
    make_turn(dt.date(2025, 11, 1), members[0])
    inside = make_turn(dt.date(2026, 1, 1), members[0])
    make_turn(dt.date(2026, 3, 1), members[0])

    response = as_ana.get(
        reverse("history"), {"since": "2025-12-01", "until": "2026-02-01"}
    )

    assert rows(response) == [inside]


def test_filters_combine(as_ana, make_turn, members, bathroom):
    make_turn(dt.date(2026, 1, 1), members[0], status=TurnStatus.MISSED)
    make_turn(dt.date(2026, 1, 2), members[1], status=TurnStatus.MISSED)
    wanted = make_turn(
        dt.date(2026, 1, 3), members[1], status=TurnStatus.MISSED, chore=bathroom
    )

    response = as_ana.get(
        reverse("history"),
        {"member": str(members[1].pk), "chore": str(bathroom.pk), "status": "MISSED"},
    )

    assert rows(response) == [wanted]


def test_no_filters_means_everything(as_ana, make_turn, members):
    make_turn(dt.date(2026, 1, 1), members[0])
    make_turn(dt.date(2026, 1, 2), members[1], status=TurnStatus.MISSED)

    response = as_ana.get(reverse("history"))

    assert len(rows(response)) == 2
    assert response.context["is_filtered"] is False


def test_a_backwards_date_range_is_refused_with_a_message(as_ana, make_turn, members):
    make_turn(dt.date(2026, 1, 1), members[0])

    response = as_ana.get(
        reverse("history"), {"since": "2026-03-01", "until": "2026-01-01"}
    )

    assert "end date is before the start date" in response.content.decode()


# Criterion 3 — the fairness tally.


def test_the_summary_counts_work_done_and_turns_missed(as_ana, make_turn, members):
    make_turn(dt.date(2026, 1, 1), members[0], completed_by=members[0])
    make_turn(dt.date(2026, 1, 8), members[0], completed_by=members[0])
    make_turn(dt.date(2026, 1, 15), members[0], status=TurnStatus.MISSED)

    ana = summary_for(as_ana.get(reverse("history")), "Ana")

    assert ana["done"] == 2
    assert ana["missed"] == 1


def test_covering_is_credited_to_whoever_actually_did_it(as_ana, make_turn, members):
    """plan.md §4 records covering precisely so it can be credited."""
    make_turn(dt.date(2026, 1, 1), members[0], completed_by=members[3])

    response = as_ana.get(reverse("history"))

    assert summary_for(response, "Dev")["done"] == 1
    assert summary_for(response, "Dev")["covered"] == 1
    assert summary_for(response, "Ana") is None


def test_an_absence_is_counted_apart_from_both(as_ana, make_turn, members):
    """Neither a contribution nor a failure; hiding it would look like idling."""
    make_turn(dt.date(2026, 1, 1), members[2], status=TurnStatus.SKIPPED_AWAY)

    cleo = summary_for(as_ana.get(reverse("history")), "Cleo")

    assert cleo["skipped"] == 1
    assert cleo["done"] == 0
    assert cleo["missed"] == 0


def test_a_roommate_with_no_history_is_left_out_of_the_tally(
    as_ana, make_turn, members
):
    make_turn(dt.date(2026, 1, 1), members[0], completed_by=members[0])

    assert summary_for(as_ana.get(reverse("history")), "Elif") is None


def test_the_tally_follows_the_filters(as_ana, make_turn, members, bathroom):
    make_turn(dt.date(2026, 1, 1), members[0], completed_by=members[0])
    make_turn(dt.date(2026, 1, 2), members[0], completed_by=members[0], chore=bathroom)

    response = as_ana.get(reverse("history"), {"chore": str(bathroom.pk)})

    assert summary_for(response, "Ana")["done"] == 1


def test_a_departed_roommates_record_stays_in_the_tally(as_ana, make_turn, members):
    """Leaving must not launder your record."""
    make_turn(dt.date(2026, 1, 1), members[1], status=TurnStatus.MISSED)
    members[1].is_active = False
    members[1].save(update_fields=["is_active"])

    ben = summary_for(as_ana.get(reverse("history")), "Ben")

    assert ben["missed"] == 1


# Criterion 4 — covering and lateness stay visible.


def test_the_row_says_who_covered(as_ana, make_turn, members):
    make_turn(dt.date(2026, 1, 1), members[0], completed_by=members[3])

    body = as_ana.get(reverse("history")).content.decode()

    assert "done by Dev" in body


def test_a_late_completion_is_still_marked_late(as_ana, make_turn, members):
    make_turn(dt.date(2026, 1, 1), members[0], completed_by=members[0], was_late=True)

    assert "late" in as_ana.get(reverse("history")).content.decode()


def test_a_missed_turn_reads_as_missed_not_merely_listed(as_ana, make_turn, members):
    make_turn(dt.date(2026, 1, 1), members[0], status=TurnStatus.MISSED)

    body = as_ana.get(reverse("history")).content.decode()

    assert "row--danger" in body
    assert "Missed" in body


# Criteria 5 and 6 — scoping and empty states.


def test_another_households_history_is_invisible(as_ana, make_turn, members):
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )
    their_chore = Chore.objects.create(
        household=other, name="Their bins", anchor_date=TODAY
    )
    Turn.objects.create(
        chore=their_chore,
        assignee=outsider,
        cycle_index=0,
        period_start=TODAY,
        due_date=TODAY,
        status=TurnStatus.MISSED,
    )
    mine = make_turn(dt.date(2026, 1, 1), members[0])

    response = as_ana.get(reverse("history"))

    assert rows(response) == [mine]
    assert "Outsider" not in response.content.decode()


def test_the_filters_only_offer_your_own_household(as_ana, members):
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )
    Chore.objects.create(household=other, name="Their bins", anchor_date=TODAY)

    form = as_ana.get(reverse("history")).context["form"]

    assert outsider not in form.fields["member"].queryset
    assert not form.fields["chore"].queryset.filter(name="Their bins").exists()


def test_an_empty_history_says_so_plainly(as_ana):
    body = as_ana.get(reverse("history")).content.decode()

    assert "Nothing has been done, missed or skipped yet." in body


def test_an_over_filtered_history_offers_a_way_back(as_ana, make_turn, members):
    make_turn(dt.date(2026, 1, 1), members[0])

    response = as_ana.get(reverse("history"), {"member": str(members[4].pk)})

    assert rows(response) == []
    assert "Nothing matches those filters" in response.content.decode()
    assert response.context["is_filtered"] is True


def test_history_requires_signing_in(client):
    response = client.get(reverse("history"))
    assert response.status_code == 302
    assert reverse("login") in response.url


def test_history_is_reachable_from_the_nav(as_ana):
    assert reverse("history") in as_ana.get(reverse("dashboard")).content.decode()
