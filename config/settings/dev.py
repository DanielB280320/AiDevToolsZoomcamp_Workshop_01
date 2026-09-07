"""Local development settings.

Chosen by ``manage.py`` unless DJANGO_SETTINGS_MODULE says otherwise.
"""

from .base import *
from .base import INSTALLED_APPS, MIDDLEWARE, SECRET_KEY

DEBUG = True

# Runnable straight after a clone, with no .env present. Any real deployment
# reads SECRET_KEY from the environment — prod.py refuses to start without it.
if not SECRET_KEY:
    SECRET_KEY = "django-insecure-dev-only-do-not-use-this-anywhere-real"

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]

INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware", *MIDDLEWARE]
INTERNAL_IPS = ["127.0.0.1"]

# Nothing is emailed yet (plan.md §6 keeps reminders in-app), but console output
# beats a silent failure if something does try.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
