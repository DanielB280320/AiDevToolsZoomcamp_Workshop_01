"""Production settings.

Deliberately fails loudly rather than falling back to an insecure default: a
missing SECRET_KEY or ALLOWED_HOSTS raises at import time, before the process
starts serving.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *
from .base import env

DEBUG = False

# base.py gives these empty defaults so dev is runnable without a .env. In
# production an empty value is a misconfiguration, not a default, so it is
# checked here rather than allowed to start a process with no signing key.
SECRET_KEY = env("SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "SECRET_KEY must be set in production. Generate one with: "
        'python -c "from django.core.management.utils import '
        'get_random_secret_key as k; print(k())"'
    )

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS must be set in production, as a comma-separated list of "
        "the hostnames this app is served on."
    )

# WhiteNoise serves static files from the app process; architecture.md §1 chose
# it over a separate nginx for a household-scale deployment.
MIDDLEWARE = list(MIDDLEWARE)
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# --- Transport and cookie security ---------------------------------------
#
# The session cookie is the whole of a roommate's authenticated identity
# (plan.md §5), so it must never travel in clear text.

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}
