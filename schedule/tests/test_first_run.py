"""First-run setup (task 22).

plan.md §5 has no public signup and §7 requires an admin to exist before chores
can be added, which leaves the first admin with nowhere to come from inside the
app. This command is that outside — the spec's open question on how the first
admin is designated.
"""

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import Household, Member
from chores.models import Cadence, Chore
from schedule.models import Turn
from schedule.services.generation import generate_for_household

pytestmark = pytest.mark.django_db

PIN = "918273"


@pytest.fixture
def seed_file(tmp_path):
    def _seed_file(data):
        path = tmp_path / "seed.json"
        path.write_text(json.dumps(data))
        return path

    return _seed_file


@pytest.fixture
def full_seed(seed_file):
    return seed_file(
        {
            "starting_pin": "000000",
            "roommates": ["Ben", "Cleo"],
            "chores": [
                {
                    "name": "Bins",
                    "description": "Kerb by 7am.",
                    "cadence_unit": "WEEK",
                    "cadence_interval": 1,
                    "anchor_date": "2026-01-06",
                    "grace_days": 1,
                    "rotation": ["Ana", "Ben", "Cleo"],
                },
                {
                    "name": "Oven",
                    "cadence_unit": "MONTH",
                    "anchor_date": "2026-01-31",
                    "rotation": ["Cleo", "Ana"],
                },
            ],
        }
    )


def setup(**overrides):
    options = {"household": "Flat 3B", "admin": "Ana", "pin": PIN}
    options.update(overrides)
    return call_command("setup_household", **options)


# Criteria 1 and 3 — one command, against an empty database.


def test_it_runs_against_an_empty_database(db):
    assert not Household.objects.exists()
    assert not Member.objects.exists()

    setup()

    household = Household.objects.get()
    assert household.name == "Flat 3B"
    assert Member.objects.count() == 1


def test_the_first_admin_is_an_admin_and_can_sign_in(db):
    setup()

    admin = Member.objects.get()
    assert admin.display_name == "Ana"
    assert admin.is_admin is True
    assert admin.is_active is True
    assert admin.check_pin(PIN) is True


def test_the_timezone_can_be_set(db):
    setup(timezone="Europe/Madrid")
    assert Household.objects.get().timezone == "Europe/Madrid"


def test_it_reports_what_it_did(db, capsys):
    setup()

    out = capsys.readouterr().out
    assert "Flat 3B" in out
    assert "Ana" in out
    assert "Ready." in out


# Criterion 5 — the PIN is validated and never echoed.


def test_the_pin_is_stored_hashed_never_in_plaintext(db):
    """Asserts the PIN is unrecoverable, not which hasher ran.

    The test settings swap in MD5 for speed, so pinning an algorithm here would
    only be testing config. What matters is that the stored value is a Django
    hash and the plaintext is not in it.
    """
    setup()

    admin = Member.objects.get()
    algorithm, _, remainder = admin.password.partition("$")
    assert PIN not in admin.password
    assert algorithm and remainder, "not a Django hasher-stack value"
    assert admin.check_pin(PIN) is True


def test_the_pin_is_never_printed_back(db, capsys):
    setup()
    assert PIN not in capsys.readouterr().out


def test_a_short_pin_is_refused(db):
    with pytest.raises(CommandError):
        setup(pin="123")


def test_a_non_numeric_pin_is_refused(db):
    with pytest.raises(CommandError):
        setup(pin="letmein")


def test_a_refused_pin_leaves_nothing_behind(db):
    """The household must not survive its own admin being rejected."""
    with pytest.raises(CommandError):
        setup(pin="123")

    assert not Household.objects.exists()
    assert not Member.objects.exists()


# Criterion 4 — it refuses to clobber an existing household.


def test_running_it_twice_is_refused(db):
    setup()

    with pytest.raises(CommandError, match="already exists"):
        setup(household="Flat 9", admin="Ben")

    assert Household.objects.count() == 1


def test_the_refusal_changes_nothing(db):
    setup()
    before = (Household.objects.count(), Member.objects.count())

    with pytest.raises(CommandError):
        setup(household="Flat 9", admin="Ben")

    assert (Household.objects.count(), Member.objects.count()) == before


def test_it_points_you_at_the_app_instead(db):
    setup()

    with pytest.raises(CommandError, match="through the app"):
        setup()


# Criteria 2 and 6 — the seed file.


def test_seeding_creates_the_chores_with_their_own_cadences(db, full_seed):
    setup(seed=full_seed)

    bins = Chore.objects.get(name="Bins")
    oven = Chore.objects.get(name="Oven")
    assert bins.cadence_unit == Cadence.WEEK
    assert bins.cadence_interval == 1
    assert bins.grace_days == 1
    assert oven.cadence_unit == Cadence.MONTH
    assert str(oven.anchor_date) == "2026-01-31"


def test_seeding_creates_the_other_roommates(db, full_seed):
    setup(seed=full_seed)

    assert set(Member.objects.values_list("display_name", flat=True)) == {
        "Ana",
        "Ben",
        "Cleo",
    }
    assert Member.objects.filter(is_admin=True).count() == 1


def test_seeded_roommates_get_the_starting_pin(db, full_seed):
    setup(seed=full_seed)

    assert Member.objects.get(display_name="Ben").check_pin("000000") is True


def test_seeding_sets_each_chores_own_rotation(db, full_seed):
    setup(seed=full_seed)

    bins = Chore.objects.get(name="Bins")
    oven = Chore.objects.get(name="Oven")
    assert [m.display_name for m in bins.rotation] == ["Ana", "Ben", "Cleo"]
    assert [m.display_name for m in oven.rotation] == ["Cleo", "Ana"]


def test_the_seeded_household_actually_generates_turns(db, full_seed):
    """The real end-to-end check: a fresh install produces a working rota."""
    setup(seed=full_seed)

    generate_for_household(Household.objects.get(), horizon_weeks=4)

    assert Turn.objects.exists()
    assert Turn.objects.filter(chore__name="Bins").exists()


def test_a_chore_without_a_rotation_is_still_created(db, seed_file):
    path = seed_file({"chores": [{"name": "Windows", "anchor_date": "2026-01-06"}]})
    setup(seed=path)

    assert Chore.objects.get(name="Windows").rotation == []


def test_a_typo_in_a_rotation_is_an_error_not_a_shorter_rota(db, seed_file):
    """A rota missing someone is exactly the unfairness this app settles."""
    path = seed_file(
        {
            "roommates": ["Ben"],
            "chores": [
                {
                    "name": "Bins",
                    "anchor_date": "2026-01-06",
                    "rotation": ["Ana", "Bne"],
                }
            ],
        }
    )

    with pytest.raises(CommandError, match="Bne"):
        setup(seed=path)


def test_a_bad_seed_leaves_no_half_built_household(db, seed_file):
    path = seed_file(
        {
            "chores": [
                {"name": "Bins", "anchor_date": "2026-01-06", "rotation": ["Nope"]}
            ]
        }
    )

    with pytest.raises(CommandError):
        setup(seed=path)

    assert not Household.objects.exists()
    assert not Chore.objects.exists()


def test_a_missing_seed_file_is_reported_clearly(db, tmp_path):
    with pytest.raises(CommandError, match="No seed file"):
        setup(seed=tmp_path / "nope.json")

    assert not Household.objects.exists()


def test_malformed_json_is_reported_clearly(db, tmp_path):
    path = tmp_path / "seed.json"
    path.write_text("{not json")

    with pytest.raises(CommandError, match="not valid JSON"):
        setup(seed=path)


def test_a_seed_without_chores_is_reported_clearly(db, seed_file):
    with pytest.raises(CommandError, match="chores"):
        setup(seed=seed_file({"roommates": ["Ben"]}))


def test_the_shipped_example_seed_is_usable_as_is(db):
    """The documented example must actually work, or it is worse than none."""
    setup(seed="seed.example.json")

    assert Chore.objects.count() == 3
    assert Member.objects.count() == 5
    assert [m.display_name for m in Chore.objects.get(name="Bins").rotation] == [
        "Ana",
        "Ben",
        "Cleo",
        "Dev",
        "Elif",
    ]
