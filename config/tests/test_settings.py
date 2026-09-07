"""Tests for the project skeleton and settings (issue #1).

``dev.py``, ``prod.py`` and ``test.py`` each pick their behaviour from
``DJANGO_SETTINGS_MODULE`` and from ``.env``/the environment, both of which
Django (and django-environ) only read once per process. That rules out
switching settings modules mid test-run in this file the normal Django-test
way, so these tests shell out to a fresh interpreter per case — which also
happens to be exactly how issue #1's acceptance criteria are phrased (shell
commands run against the real settings machinery).
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[2]
PYTHON = sys.executable

# The repository README is the course homework brief; this app's own setup and
# deployment documentation lives here.
PROJECT_DOC = BASE_DIR / "Household_Chores_Manager" / "description.md"


def run(args, *, env_overrides=None, unset=()):
    """Run ``args`` in a subprocess from the project root with a minimal env.

    Only ``PATH`` (needed to find shared libraries/tools) and any explicitly
    given ``env_overrides`` are set, so a developer's own shell environment
    (a stray ``SECRET_KEY``, an ``ALLOWED_HOSTS``, ...) can never leak into a
    test and mask a real failure.
    """
    env = {"PATH": os.environ.get("PATH", "")}
    env.update(env_overrides or {})
    for key in unset:
        env.pop(key, None)
    return subprocess.run(
        args,
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture
def no_env_file():
    """Guarantee ``BASE_DIR/.env`` is absent for the duration of a test.

    A contributor running the suite locally may have their own ``.env`` for
    day-to-day work; criterion 1 is specifically about the no-``.env`` case,
    so that file (if any) is moved aside and restored afterwards rather than
    assumed absent.
    """
    env_path = BASE_DIR / ".env"
    backup = BASE_DIR / ".env.test-backup"
    moved = False
    if env_path.exists():
        env_path.rename(backup)
        moved = True
    try:
        yield
    finally:
        if moved:
            backup.rename(env_path)


def test_dev_check_with_no_env_file_exits_zero(no_env_file):
    """Criterion 1: fresh clone, no .env, `manage.py check` (dev) is clean."""
    result = run(
        [PYTHON, "manage.py", "check"],
        env_overrides={"DJANGO_SETTINGS_MODULE": "config.settings.dev"},
    )
    assert result.returncode == 0, result.stderr
    assert "System check identified no issues" in result.stdout


def test_dev_check_database_default_uses_sqlite(no_env_file):
    """Criterion 2: DATABASE_URL unset -> `check --database default` is clean
    against the SQLite file, no PostgreSQL server needed."""
    result = run(
        [PYTHON, "manage.py", "check", "--database", "default"],
        env_overrides={"DJANGO_SETTINGS_MODULE": "config.settings.dev"},
    )
    assert result.returncode == 0, result.stderr

    inspect = run(
        [
            PYTHON,
            "-c",
            "from django.conf import settings; "
            "print(settings.DATABASES['default']['ENGINE']); "
            "print(settings.DATABASES['default']['NAME'])",
        ],
        env_overrides={"DJANGO_SETTINGS_MODULE": "config.settings.dev"},
    )
    engine, name = inspect.stdout.strip().splitlines()
    assert engine == "django.db.backends.sqlite3"
    assert name.endswith("db.sqlite3")


def test_database_url_postgres_changes_engine():
    """Criterion 3: DATABASE_URL=postgres://... resolves to the postgresql
    backend via django-environ, with zero source-file changes, checked
    *without* calling ``django.setup()`` or otherwise initializing Django
    (``django.setup()`` would import ``django.contrib.auth``, which needs the
    ``psycopg`` driver just to *load* the postgresql backend module — a
    driver this task deliberately does not install; see the issue's "Out of
    scope" section).

    Reading ``settings.DATABASES`` triggers only the settings module import
    (which calls ``env.db_url(...)``, exactly what ``base.py`` does), not
    Django's app registry, so this needs no driver installed.
    """
    result = run(
        [
            PYTHON,
            "-c",
            "from django.conf import settings; "
            "print(settings.DATABASES['default']['ENGINE'])",
        ],
        env_overrides={
            "DJANGO_SETTINGS_MODULE": "config.settings.dev",
            "DATABASE_URL": "postgres://user:pass@host:5432/chores",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "django.db.backends.postgresql"


def test_database_url_postgres_via_environ_directly_no_django():
    """Criterion 3's own literal example: django-environ's URL parser alone,
    with no Django import at all -- proves the driver genuinely isn't needed
    to resolve the ENGINE."""
    result = run(
        [
            PYTHON,
            "-c",
            "import environ; e = environ.Env(); "
            "print(e.db_url('DATABASE_URL', default='sqlite:///db.sqlite3')['ENGINE'])",
        ],
        env_overrides={"DATABASE_URL": "postgres://user:pass@host:5432/chores"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "django.db.backends.postgresql"


def test_env_example_documents_sqlite_default_and_postgres_url():
    """Criterion 4."""
    contents = (BASE_DIR / ".env.example").read_text()
    assert "DATABASE_URL" in contents
    assert "postgres://" in contents
    assert "SQLite" in contents or "sqlite" in contents


@pytest.mark.parametrize(
    "extra_env, should_fail",
    [
        ({}, True),
        ({"SECRET_KEY": "a-real-secret"}, True),  # ALLOWED_HOSTS still missing
        ({"ALLOWED_HOSTS": "chores.example.com"}, True),  # SECRET_KEY still missing
        ({"SECRET_KEY": "a-real-secret", "ALLOWED_HOSTS": "chores.example.com"}, False),
    ],
)
def test_prod_check_fails_fast_without_secret_key_or_allowed_hosts(
    no_env_file, extra_env, should_fail
):
    """Criterion 5: prod settings raise ImproperlyConfigured (non-zero exit)
    unless both SECRET_KEY and ALLOWED_HOSTS are supplied, and exit 0 once
    both are."""
    env = {"DJANGO_SETTINGS_MODULE": "config.settings.prod", **extra_env}
    result = run([PYTHON, "manage.py", "check"], env_overrides=env)
    if should_fail:
        assert result.returncode != 0
        assert "ImproperlyConfigured" in result.stderr
    else:
        assert result.returncode == 0, result.stderr


def test_no_secret_hardcoded_in_base_or_prod_settings():
    """Criterion 6: base.py and prod.py must read SECRET_KEY from the
    environment only -- no hardcoded value, placeholder or otherwise."""
    for name in ("base.py", "prod.py"):
        contents = (BASE_DIR / "config" / "settings" / name).read_text()
        assert "django-insecure" not in contents
        assert 'env("SECRET_KEY")' in contents


def test_prod_secret_key_has_no_fallback():
    """Criterion 6: prod.py must have *no* fallback -- it fails rather than
    ever starting with a placeholder SECRET_KEY, even if one happened to be
    baked into dev.py/test.py by mistake."""
    contents = (BASE_DIR / "config" / "settings" / "prod.py").read_text()
    assert "django-insecure" not in contents
    # No `if not SECRET_KEY: SECRET_KEY = ...`-style fallback anywhere.
    assert "SECRET_KEY =" not in contents.replace('SECRET_KEY = env("SECRET_KEY")', "")

    result = run(
        [PYTHON, "manage.py", "check"],
        env_overrides={
            "DJANGO_SETTINGS_MODULE": "config.settings.prod",
            "ALLOWED_HOSTS": "chores.example.com",
        },
    )
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert "SECRET_KEY" in result.stderr


@pytest.mark.parametrize(
    "settings_module", ["config.settings.dev", "config.settings.test"]
)
def test_dev_and_test_secret_key_placeholder_is_fallback_only(
    no_env_file, settings_module
):
    """Criterion 6: dev.py/test.py may hardcode an obviously-fake
    `django-insecure-` placeholder SECRET_KEY, but *only* as a fallback used
    when the environment variable is unset -- an explicit SECRET_KEY always
    wins."""
    script = (
        "import django; django.setup(); "
        "from django.conf import settings; print(settings.SECRET_KEY)"
    )

    unset = run(
        [PYTHON, "-c", script],
        env_overrides={"DJANGO_SETTINGS_MODULE": settings_module},
    )
    assert unset.returncode == 0, unset.stderr
    assert unset.stdout.strip().startswith("django-insecure-")

    explicit = run(
        [PYTHON, "-c", script],
        env_overrides={
            "DJANGO_SETTINGS_MODULE": settings_module,
            "SECRET_KEY": "an-explicit-secret-key-value",
        },
    )
    assert explicit.returncode == 0, explicit.stderr
    assert explicit.stdout.strip() == "an-explicit-secret-key-value"


def test_env_is_gitignored():
    gitignore = (BASE_DIR / ".gitignore").read_text().splitlines()
    assert ".env" in [line.strip() for line in gitignore]


def test_env_never_committed():
    result = subprocess.run(
        ["git", "log", "--all", "--full-history", "--", ".env"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""


def test_time_zone_defaults_to_utc(no_env_file):
    """Criterion 7: TIME_ZONE read from .env, default UTC."""
    result = run(
        [
            PYTHON,
            "-c",
            "import django; django.setup(); "
            "from django.utils import timezone; print(timezone.get_current_timezone())",
        ],
        env_overrides={"DJANGO_SETTINGS_MODULE": "config.settings.dev"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "UTC"


def test_time_zone_changes_when_env_var_set(no_env_file):
    result = run(
        [
            PYTHON,
            "-c",
            "import django; django.setup(); "
            "from django.utils import timezone; print(timezone.get_current_timezone())",
        ],
        env_overrides={
            "DJANGO_SETTINGS_MODULE": "config.settings.dev",
            "TIME_ZONE": "America/Chicago",
        },
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "America/Chicago"


@pytest.mark.parametrize(
    "settings_module, extra_env",
    [
        ("config.settings.dev", {}),
        ("config.settings.test", {}),
        (
            "config.settings.prod",
            {"SECRET_KEY": "a-real-secret", "ALLOWED_HOSTS": "chores.example.com"},
        ),
    ],
)
def test_use_tz_is_true_in_every_settings_module(
    no_env_file, settings_module, extra_env
):
    result = run(
        [
            PYTHON,
            "-c",
            "import django; django.setup(); "
            "from django.conf import settings; print(settings.USE_TZ)",
        ],
        env_overrides={"DJANGO_SETTINGS_MODULE": settings_module, **extra_env},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_no_client_side_storage_of_chore_or_roommate_state():
    """Criterion 8: plan.md §9 -- one shared, server-side source of truth."""
    hits = []
    for directory in ("static", "templates"):
        root = BASE_DIR / directory
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(errors="ignore")
            except (UnicodeDecodeError, OSError):
                continue
            if "localStorage" in text or "sessionStorage" in text:
                hits.append(str(path))
    assert hits == []


def test_runserver_starts_with_no_traceback():
    """Criterion 10: `manage.py runserver` starts cleanly."""
    proc = subprocess.Popen(
        [PYTHON, "-u", "manage.py", "runserver", "--noreload"],
        cwd=BASE_DIR,
        env={
            "PATH": os.environ.get("PATH", ""),
            "DJANGO_SETTINGS_MODULE": "config.settings.dev",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        output_lines = []
        for _ in range(200):  # bounded read loop, not a fixed sleep
            line = proc.stdout.readline()
            if not line:
                break
            output_lines.append(line)
            if "Starting development server at http://127.0.0.1:8000/" in line:
                break
        else:
            pytest.fail(
                "server did not report startup in time:\n" + "".join(output_lines)
            )
        output = "".join(output_lines)
        assert "Traceback" not in output
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_auth_user_model_is_accounts_member(no_env_file):
    """Criterion 9: AUTH_USER_MODEL is set to the custom Member model."""
    result = run(
        [
            PYTHON,
            "-c",
            "import django; django.setup(); "
            "from django.conf import settings; print(settings.AUTH_USER_MODEL)",
        ],
        env_overrides={"DJANGO_SETTINGS_MODULE": "config.settings.dev"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "accounts.Member"


def test_accounts_first_migration_creates_member_and_household():
    """Criterion 9: accounts/migrations/0001_initial.py -- not a later
    migration -- is what creates Member and Household. There must be no
    earlier migration for a stock auth.User that a later one had to swap out
    or rename around: 0001 is the very first migration file in the app, and
    it is the one carrying these CreateModel operations, with
    ``initial = True``.
    """
    migrations_dir = BASE_DIR / "accounts" / "migrations"
    numbered = sorted(
        p.name for p in migrations_dir.glob("0*.py") if p.name != "__init__.py"
    )
    assert numbered, "no numbered migrations found under accounts/migrations"
    assert numbered[0] == "0001_initial.py", (
        f"expected 0001_initial.py first, found {numbered[0]}"
    )

    spec = importlib.util.spec_from_file_location(
        "accounts_migrations_0001_initial", migrations_dir / "0001_initial.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    migration = module.Migration
    assert migration.initial is True

    created_model_names = {
        op.name for op in migration.operations if type(op).__name__ == "CreateModel"
    }
    assert created_model_names >= {"Member", "Household"}

    # No stock-auth swap trail: nothing in this migration -- or any later
    # accounts migration -- ever creates, renames, or alters a model named
    # "User" (the stock model AUTH_USER_MODEL would have pointed at before
    # the swap).
    for path in migrations_dir.glob("0*.py"):
        if path.name == "__init__.py":
            continue
        contents = path.read_text()
        assert 'name="User"' not in contents
        assert "name='User'" not in contents


def test_docs_document_setup_steps_in_order():
    """Criterion 11: the docs cover, in order, venv -> install -> .env -> check."""
    docs = PROJECT_DOC.read_text()
    steps = [
        "venv",
        "pip install -r requirements.txt",
        "cp .env.example .env",
        "manage.py check",
    ]
    positions = [docs.index(step) for step in steps]
    assert positions == sorted(positions), "setup steps are out of order"


class TestTheSuiteForcesItsOwnSettings:
    """A developer's shell must not be able to change what the suite runs under.

    pytest-django's precedence is command line > environment > ini, so the
    ``DJANGO_SETTINGS_MODULE`` ini key alone loses to an exported variable —
    which silently ran the whole suite under dev settings: debug toolbar
    loaded, PBKDF2 rather than the fast test hasher, different ALLOWED_HOSTS.
    The dangerous half is not the slowness; it is that a green local run would
    stop meaning what CI means by it.
    """

    def test_a_hostile_environment_variable_does_not_win(self):
        result = run(
            [PYTHON, "-m", "pytest", "accounts/tests/test_models.py", "--collect-only"],
            env_overrides={"DJANGO_SETTINGS_MODULE": "config.settings.dev"},
        )

        assert "settings: config.settings.test" in result.stdout, result.stdout
        assert "config.settings.dev" not in result.stdout

    def test_the_settings_come_from_the_option_not_the_ini_key(self):
        result = run(
            [PYTHON, "-m", "pytest", "accounts/tests/test_models.py", "--collect-only"]
        )

        assert "settings: config.settings.test (from option)" in result.stdout

    def test_the_suite_actually_runs_green_under_a_hostile_environment(self):
        result = run(
            [PYTHON, "-m", "pytest", "accounts/tests/test_models.py", "-q"],
            env_overrides={"DJANGO_SETTINGS_MODULE": "config.settings.dev"},
        )

        assert result.returncode == 0, result.stdout + result.stderr
