"""Settings shared by every environment.

Values that differ between a laptop and a server are read from the environment
(via a ``.env`` file in the project root) rather than branched on in code — see
``dev.py`` and ``prod.py`` for the per-environment overrides.
"""

from pathlib import Path

import environ

# config/settings/base.py -> config/settings -> config -> <project root>
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    SECRET_KEY=(str, ""),
    ALLOWED_HOSTS=(list, []),
    TIME_ZONE=(str, "UTC"),
)
environ.Env.read_env(BASE_DIR / ".env")

# Required in production; dev.py falls back to an insecure value so the project
# is runnable straight after a clone.
SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")


# --- Applications ---------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

LOCAL_APPS = [
    "accounts",
]

INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# --- Database -------------------------------------------------------------
#
# plan.md §9: one shared, persistent source of truth for every roommate — server
# side, never per-device browser storage.
#
# SQLite is the default so the project runs with no setup. PostgreSQL needs no
# code change, only a different DATABASE_URL:
#
#     DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/DBNAME
#
# Nothing in the app depends on a SQLite-only feature: architecture.md §5 relies
# on ``select_for_update`` and ``UniqueConstraint``, both of which behave
# correctly on PostgreSQL (and are what make the concurrency guarantees real —
# SQLite serialises writes rather than taking true row locks, so PostgreSQL is
# the right target for a real household).

DATABASES = {
    "default": env.db_url(
        "DATABASE_URL",
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
    )
}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=0)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Authentication -------------------------------------------------------
#
# plan.md §5: roommates sign in with a display name and a PIN, so the user model
# is ours from the first migration — see accounts.models.Member.

AUTH_USER_MODEL = "accounts.Member"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "login"


# --- Internationalisation -------------------------------------------------
#
# The timezone is explicit and configurable because every due date, grace period
# and overdue check in the scheduling engine is evaluated against "today" in the
# household's local time. Leaving it at a default would silently shift due dates
# for any household not on UTC.

LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE")
USE_I18N = True
USE_TZ = True


# --- Static files ---------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
