"""Swapping turns (task 19).

plan.md §8 asks for swapping alongside skipping, and §4's accountability goal
means the trade should be recorded rather than silently rewriting who was
assigned — a rota that looks odd should have an explanation on it.

Both turns stay PENDING; only the assignee moves. architecture.md §4's prose
and tasks.md §19 both say so, though its state diagram shows a SWAPPED state
instead; noted in _docs/followups.md.
"""

import datetime as dt

import pytest
from django.urls import reverse

from accounts.models import Household, Member
from chores.models import Chore
from schedule.models import Turn, TurnStatus
from schedule.services.transitions import TransitionRefused, swap_turns

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 1, 5)


@pytest.fixture(autouse=True)
def _clock(frozen_clock):
    """Pin the clock; the form lists turns relative to now."""


@pytest.fixture
def bins(household, members):
    chore = Chore.objects.create(
        household=household, name="Bins", anchor_date=TODAY, grace_days=1
    )
    chore.set_rotation(members[:3])
    return chore


@pytest.fixture
def make_turn(bins, members):
    def _make_turn(due, assignee, *, chore=None, status=TurnStatus.PENDING):
        chore = chore or bins
        return Turn.objects.create(
            chore=chore,
            assignee=assignee,
            cycle_index=chore.turns.count(),
            period_start=due,
            due_date=due,
            status=status,
        )

    return _make_turn


@pytest.fixture
def pair(make_turn, members):
    """Ana's turn on the 12th, Ben's on the 19th."""
    return (
        make_turn(dt.date(2026, 1, 12), members[0]),
        make_turn(dt.date(2026, 1, 19), members[1]),
    )


@pytest.fixture
def as_ana(client, members):
    client.force_login(members[0])
    return client


# Criteria 1 and 2 — the assignees move, and nothing else does.


def test_swapping_exchanges_the_two_assignees(pair, members):
    mine, theirs = pair

    swap_turns(mine, theirs)

    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.assignee == members[1]
    assert theirs.assignee == members[0]


def test_both_turns_stay_pending(pair):
    mine, theirs = pair

    swap_turns(mine, theirs)

    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.status == TurnStatus.PENDING
    assert theirs.status == TurnStatus.PENDING


def test_only_the_assignee_moves(pair):
    """The chore, the dates and the cycle stay where they were."""
    mine, theirs = pair
    before = [(t.chore_id, t.cycle_index, t.due_date, t.period_start) for t in pair]

    swap_turns(mine, theirs)

    mine.refresh_from_db()
    theirs.refresh_from_db()
    after = [
        (t.chore_id, t.cycle_index, t.due_date, t.period_start) for t in (mine, theirs)
    ]
    assert after == before


def test_no_extra_rows_are_created(pair):
    swap_turns(*pair)
    assert Turn.objects.count() == 2


def test_turns_on_two_different_chores_can_be_traded(
    household, make_turn, members, bins
):
    other = Chore.objects.create(
        household=household, name="Bathroom", anchor_date=TODAY
    )
    mine = make_turn(dt.date(2026, 1, 12), members[0])
    theirs = make_turn(dt.date(2026, 1, 19), members[1], chore=other)

    swap_turns(mine, theirs)

    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.assignee == members[1]
    assert mine.chore == bins
    assert theirs.assignee == members[0]
    assert theirs.chore == other


# Criterion 3 — the trade is visible from either side.


def test_the_pair_is_linked(pair):
    mine, theirs = pair

    swap_turns(mine, theirs)

    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.swapped_with == theirs
    assert theirs.swapped_from == mine


def test_either_side_can_name_its_partner(pair):
    """Only one row carries the link; both must still be able to answer."""
    mine, theirs = pair

    swap_turns(mine, theirs)

    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.swap_partner == theirs
    assert theirs.swap_partner == mine


def test_an_untraded_turn_has_no_partner(pair):
    assert pair[0].swap_partner is None


def test_the_trade_is_listed_on_the_swaps_page(as_ana, pair, members):
    swap_turns(*pair)

    body = as_ana.get(reverse("swap_list")).content.decode()

    assert "traded with" in body
    assert "Ana" in body
    assert "Ben" in body


# Criterion 4 — what is refused.


def test_a_turn_cannot_be_swapped_with_itself(pair):
    mine, _ = pair
    with pytest.raises(TransitionRefused, match="with itself"):
        swap_turns(mine, mine)


@pytest.mark.parametrize(
    "status",
    [TurnStatus.COMPLETED, TurnStatus.MISSED, TurnStatus.SKIPPED_AWAY],
)
def test_a_settled_turn_cannot_be_swapped(make_turn, members, pair, status):
    mine, _ = pair
    settled = make_turn(dt.date(2026, 1, 26), members[2], status=status)

    with pytest.raises(TransitionRefused):
        swap_turns(mine, settled)

    mine.refresh_from_db()
    assert mine.assignee == members[0]


def test_a_turn_already_traded_cannot_be_traded_again(make_turn, members, pair):
    mine, theirs = pair
    swap_turns(mine, theirs)
    third = make_turn(dt.date(2026, 1, 26), members[2])

    mine.refresh_from_db()
    with pytest.raises(TransitionRefused, match="already been swapped"):
        swap_turns(mine, third)


def test_the_other_side_of_a_trade_also_refuses_a_second_one(make_turn, members, pair):
    """The link lives on one row; the refusal must not depend on which."""
    mine, theirs = pair
    swap_turns(mine, theirs)
    third = make_turn(dt.date(2026, 1, 26), members[2])

    theirs.refresh_from_db()
    with pytest.raises(TransitionRefused, match="already been swapped"):
        swap_turns(theirs, third)


def test_two_turns_belonging_to_the_same_person_are_refused(make_turn, members):
    one = make_turn(dt.date(2026, 1, 12), members[0])
    two = make_turn(dt.date(2026, 1, 19), members[0])

    with pytest.raises(TransitionRefused, match="same person"):
        swap_turns(one, two)


def test_turns_from_different_households_are_refused(make_turn, members):
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )
    their_chore = Chore.objects.create(
        household=other, name="Their bins", anchor_date=TODAY
    )
    theirs = Turn.objects.create(
        chore=their_chore,
        assignee=outsider,
        cycle_index=0,
        period_start=dt.date(2026, 1, 19),
        due_date=dt.date(2026, 1, 19),
    )
    mine = make_turn(dt.date(2026, 1, 12), members[0])

    with pytest.raises(TransitionRefused, match="different households"):
        swap_turns(mine, theirs)

    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.assignee == members[0]
    assert theirs.assignee == outsider


def test_a_refused_swap_leaves_both_turns_completely_alone(make_turn, members, pair):
    mine, _ = pair
    done = make_turn(dt.date(2026, 1, 26), members[2], status=TurnStatus.COMPLETED)
    before = (mine.assignee_id, done.assignee_id, done.status)

    with pytest.raises(TransitionRefused):
        swap_turns(mine, done)

    mine.refresh_from_db()
    done.refresh_from_db()
    assert (mine.assignee_id, done.assignee_id, done.status) == before
    assert mine.swap_partner is None


# Criterion 5 — the screen.


def test_a_roommate_swaps_one_of_their_turns_from_the_screen(as_ana, pair, members):
    mine, theirs = pair

    response = as_ana.post(
        reverse("swap_list"),
        {"mine": str(mine.pk), "theirs": str(theirs.pk)},
        follow=True,
    )

    assert response.status_code == 200
    mine.refresh_from_db()
    theirs.refresh_from_db()
    assert mine.assignee == members[1]
    assert theirs.assignee == members[0]
    assert "Swapped." in response.content.decode()


def test_the_form_offers_only_your_own_turns_on_your_side(as_ana, pair, members):
    mine, theirs = pair

    form = as_ana.get(reverse("swap_list")).context["form"]

    assert list(form.fields["mine"].queryset) == [mine]
    assert list(form.fields["theirs"].queryset) == [theirs]


def test_the_form_does_not_offer_settled_or_already_traded_turns(
    as_ana, make_turn, members, pair
):
    make_turn(dt.date(2026, 1, 26), members[2], status=TurnStatus.COMPLETED)
    swap_turns(*pair)

    form = as_ana.get(reverse("swap_list")).context["form"]

    assert list(form.fields["mine"].queryset) == []
    assert list(form.fields["theirs"].queryset) == []


def test_a_refusal_comes_back_as_a_form_error_not_a_crash(
    as_ana, make_turn, members, pair
):
    mine, theirs = pair
    swap_turns(mine, theirs)

    response = as_ana.post(
        reverse("swap_list"), {"mine": str(mine.pk), "theirs": str(theirs.pk)}
    )

    assert response.status_code == 200
    assert response.context["form"].errors


def test_another_households_turn_cannot_be_named_in_the_form(as_ana, pair):
    other = Household.objects.create(name="Flat 9", timezone="Europe/Madrid")
    outsider = Member.objects.create_user(
        display_name="Outsider", password="918273", household=other
    )
    their_chore = Chore.objects.create(
        household=other, name="Their bins", anchor_date=TODAY
    )
    theirs = Turn.objects.create(
        chore=their_chore,
        assignee=outsider,
        cycle_index=0,
        period_start=dt.date(2026, 1, 19),
        due_date=dt.date(2026, 1, 19),
    )
    mine, _ = pair

    response = as_ana.post(
        reverse("swap_list"), {"mine": str(mine.pk), "theirs": str(theirs.pk)}
    )

    assert response.status_code == 200
    theirs.refresh_from_db()
    assert theirs.assignee == outsider


def test_the_swaps_page_requires_signing_in(client):
    response = client.get(reverse("swap_list"))
    assert response.status_code == 302
    assert reverse("login") in response.url


def test_the_swaps_page_is_reachable_from_the_nav(as_ana):
    body = as_ana.get(reverse("dashboard")).content.decode()
    assert reverse("swap_list") in body


# Criterion 6 — the trade does not disturb history.


def test_swapping_never_touches_a_completed_turns_attribution(make_turn, members, pair):
    done = make_turn(dt.date(2026, 1, 1), members[2], status=TurnStatus.COMPLETED)
    done.completed_by = members[2]
    done.completed_at = dt.datetime(2026, 1, 1, 9, 0, tzinfo=dt.UTC)
    done.save()

    swap_turns(*pair)

    done.refresh_from_db()
    assert done.completed_by == members[2]
    assert done.status == TurnStatus.COMPLETED


def test_a_swapped_turn_can_still_be_completed_by_its_new_owner(pair, members):
    from schedule.services.transitions import complete_turn

    mine, _ = pair
    swap_turns(*pair)
    mine.refresh_from_db()

    done, changed = complete_turn(mine, members[1])

    assert changed is True
    assert done.assignee == members[1]
    assert done.completed_by == members[1]
    assert done.swap_partner is not None
