"""Deployment readiness (task 23).

plan.md §3 chose a browser app so any roommate can reach it from any device,
which only holds once it is hosted rather than run on somebody's laptop.

These shell out to a fresh interpreter, following the pattern already
established in test_settings.py: django-environ and Django each read the
environment once per process, so a settings module cannot be swapped mid-run.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[2]
PYTHON = sys.executable

PROD_ENV = {
    "DJANGO_SETTINGS_MODULE": "config.settings.prod",
    # 50+ characters with real variety: Django's own security.W009 check
    # rejects anything shorter or repetitive, and this suite asserts the deploy
    # check is clean -- so a weak key here would fail for the right reason in
    # the wrong place.
    "SECRET_KEY": "kQ7v-Zx2Lp9fR4tB6nH8sW1jY3mC5dG0aU2eI7oT4xN9zV6bM8",
    "ALLOWED_HOSTS": "chores.example.com",
}


def run(args, *, env_overrides=None, drop=()):
    env = {"PATH": os.environ.get("PATH", "")}
    env.update(PROD_ENV)
    env.update(env_overrides or {})
    for key in drop:
        env.pop(key, None)
    return subprocess.run(
        args, cwd=BASE_DIR, env=env, capture_output=True, text=True, check=False
    )


# Criterion 1 — the deploy check is clean.


def test_check_deploy_reports_no_issues():
    result = run([PYTHON, "manage.py", "check", "--deploy"])

    assert result.returncode == 0, result.stderr
    assert "no issues" in result.stdout
    assert "WARNINGS" not in result.stdout


def test_debug_is_off_in_production():
    result = run(
        [
            PYTHON,
            "-c",
            "import django;django.setup();"
            "from django.conf import settings;print(settings.DEBUG)",
        ]
    )
    assert result.stdout.strip() == "False"


# Criterion 4 — missing config fails at import, not at the first request.


@pytest.mark.parametrize("missing", ["SECRET_KEY", "ALLOWED_HOSTS"])
def test_a_missing_required_setting_refuses_to_start(missing):
    """Serving with no signing key would be worse than not serving."""
    result = run(
        [PYTHON, "manage.py", "check"], env_overrides={missing: ""}, drop=[missing]
    )

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert missing in result.stderr


def test_the_error_says_how_to_fix_it():
    result = run(
        [PYTHON, "manage.py", "check"],
        env_overrides={"SECRET_KEY": ""},
        drop=["SECRET_KEY"],
    )
    assert "get_random_secret_key" in result.stderr


# Criteria 2 and 3 — static files and the server entry point.


def test_the_secure_cookie_and_transport_settings_are_on():
    result = run(
        [
            PYTHON,
            "-c",
            "import django;django.setup();from django.conf import settings as s;"
            "print(s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE,"
            "s.SESSION_COOKIE_HTTPONLY, s.SECURE_CONTENT_TYPE_NOSNIFF,"
            "s.X_FRAME_OPTIONS)",
        ]
    )
    assert result.stdout.split() == ["True", "True", "True", "True", "DENY"]


def test_whitenoise_serves_static_files():
    result = run(
        [
            PYTHON,
            "-c",
            "import django;django.setup();from django.conf import settings as s;"
            "print('whitenoise.middleware.WhiteNoiseMiddleware' in s.MIDDLEWARE);"
            "print(s.STORAGES['staticfiles']['BACKEND'])",
        ]
    )
    lines = result.stdout.split()
    assert lines[0] == "True"
    assert "whitenoise" in lines[1]


def test_whitenoise_sits_directly_after_the_security_middleware():
    """Order matters: it must not be behind anything that can short-circuit."""
    result = run(
        [
            PYTHON,
            "-c",
            "import django;django.setup();from django.conf import settings as s;"
            "m=list(s.MIDDLEWARE);"
            "print(m.index('whitenoise.middleware.WhiteNoiseMiddleware') - "
            "m.index('django.middleware.security.SecurityMiddleware'))",
        ]
    )
    assert result.stdout.strip() == "1"


def test_collectstatic_runs(tmp_path):
    result = run(
        [PYTHON, "manage.py", "collectstatic", "--noinput", "--clear"],
        env_overrides={"STATIC_ROOT": str(tmp_path / "static")},
    )
    assert result.returncode == 0, result.stderr


def test_the_wsgi_entry_point_loads_under_production_settings():
    result = run(
        [PYTHON, "-c", "from config.wsgi import application;print(bool(application))"]
    )
    assert result.stdout.strip() == "True", result.stderr


def test_wsgi_defaults_to_production_without_being_told():
    """Only manage.py defaults to dev; the served entry points must not."""
    result = run(
        [
            PYTHON,
            "-c",
            "import config.wsgi;import os;print(os.environ['DJANGO_SETTINGS_MODULE'])",
        ],
        drop=["DJANGO_SETTINGS_MODULE"],
    )
    assert result.stdout.strip() == "config.settings.prod"


def test_the_gunicorn_config_is_importable_and_binds():
    result = run(
        [
            PYTHON,
            "-c",
            "import runpy;c=runpy.run_path('gunicorn.conf.py');"
            "print(c['bind'], c['worker_class'], c['workers'] > 0)",
        ]
    )
    assert result.stdout.split() == ["0.0.0.0:8000", "sync", "True"]


def test_the_procfile_names_the_web_and_release_commands():
    procfile = (BASE_DIR / "Procfile").read_text()

    assert "gunicorn config.wsgi" in procfile
    assert "migrate" in procfile
    assert "collectstatic" in procfile


# Criterion 5 — the scheduled jobs are documented and both exist.


@pytest.mark.parametrize("command", ["generate_turns", "mark_overdue"])
def test_each_scheduled_job_runs_under_production_settings(command, tmp_path):
    """Both jobs run clean against a migrated but empty production database.

    Empty is the case that matters: cron starts firing the moment the app is
    deployed, which is before anybody has created a chore.
    """
    database = {"DATABASE_URL": f"sqlite:///{tmp_path / 'jobs.sqlite3'}"}
    migrate = run([PYTHON, "manage.py", "migrate", "--noinput"], env_overrides=database)
    assert migrate.returncode == 0, migrate.stderr

    result = run([PYTHON, "manage.py", command], env_overrides=database)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("command", ["generate_turns", "mark_overdue"])
def test_the_readme_documents_each_scheduled_job(command):
    readme = (BASE_DIR / "README.md").read_text()

    assert command in readme, f"{command} is not documented"


def test_the_readme_documents_the_required_environment_variables():
    readme = (BASE_DIR / "README.md").read_text()

    for variable in ("SECRET_KEY", "ALLOWED_HOSTS", "DATABASE_URL", "TIME_ZONE"):
        assert variable in readme, f"{variable} is not documented"


# Criterion 6 — it actually serves a request with DEBUG off.


def test_it_serves_a_real_request_with_debug_off(tmp_path):
    """The end-to-end check: migrate, seed, sign in, get the home screen."""
    script = """
import django
django.setup()
from django.core.management import call_command
from django.test import Client

call_command("migrate", verbosity=0)
call_command(
    "setup_household", household="Flat 3B", admin="Ana", pin="918273", verbosity=0
)
from accounts.models import Member

client = Client()
client.force_login(Member.objects.get())
response = client.get("/", HTTP_HOST="chores.example.com", secure=True)
print(response.status_code)
"""
    result = run(
        [PYTHON, "-c", script],
        env_overrides={
            "DATABASE_URL": f"sqlite:///{tmp_path / 'boot.sqlite3'}",
            "SECURE_SSL_REDIRECT": "false",
        },
    )
    assert result.stdout.strip().endswith("200"), result.stderr
