"""Settings for the test suite.

Separate from dev so tests never depend on debug tooling and never touch a
developer's working database.
"""

from .base import *

DEBUG = False
SECRET_KEY = "django-insecure-test-only"
ALLOWED_HOSTS = ["testserver", "localhost"]

# Every fixture creates members, and each one hashes a PIN. PBKDF2 is
# deliberately slow, which is right in production and pure overhead here. The
# security property under test — that a PIN is hashed and never stored in
# plaintext — holds under either hasher.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
