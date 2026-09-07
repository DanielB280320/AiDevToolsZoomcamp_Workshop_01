"""Tests for the project skeleton and settings (issue #1).

``dev.py``, ``prod.py`` and ``test.py`` each pick their behaviour from
``DJANGO_SETTINGS_MODULE`` and from ``.env``/the environment, both of which
Django (and django-environ) only read once per process. That rules out
switching settings modules mid test-run in this file the normal Django-test
way, so these tests shell out to a fresh interpreter per case — which also
happens to be exactly how issue #1's acceptance criteria are phrased (shell
commands run against the real settings machinery).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


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
    """Criterion 3: DATABASE_URL=postgres://... flips settings.DATABASES
    to the postgresql backend, with zero source-file changes.

    This intentionally does not call ``django.setup()`` (unlike the exact
    command quoted in the issue): doing so imports ``django.contrib.auth``,
    which needs to import the ``psycopg`` driver just to *load* the
    postgresql backend module, before any connection is attempted. Installing
    a PostgreSQL driver is explicitly out of scope for this task (see issue
    #1's "Out of scope" section) — see the discrepancy noted in the issue
    comment. Reading ``settings.DATABASES`` without ``django.setup()`` is
    enough to prove the env-driven, code-free swap this criterion is about.
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


def test_no_secret_hardcoded_in_committed_settings():
    """Criterion 6: no real secret is hardcoded in a committed settings file.

    ``base.py`` and ``prod.py`` must read ``SECRET_KEY`` from the
    environment. ``dev.py``'s well-known, clearly-labelled
    "django-insecure-..." fallback (so the project runs with no ``.env`` at
    all) and ``test.py``'s "django-insecure-test-only" are not real secrets
    and are exempt.
    """
    for name in ("base.py", "prod.py"):
        contents = (BASE_DIR / "config" / "settings" / name).read_text()
        assert "django-insecure" not in contents
        assert 'env("SECRET_KEY")' in contents


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


def test_readme_documents_setup_steps_in_order():
    """Criterion 11: README covers, in order, venv -> install -> .env -> check."""
    readme = (BASE_DIR / "README.md").read_text()
    steps = [
        "venv",
        "pip install -r requirements.txt",
        "cp .env.example .env",
        "manage.py check",
    ]
    positions = [readme.index(step) for step in steps]
    assert positions == sorted(positions), "README setup steps are out of order"
