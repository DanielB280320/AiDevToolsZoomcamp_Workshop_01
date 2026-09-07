# Chore Manager

A Django app that runs a fixed chore rotation for a household of roommates,
with sign-in by display name + PIN and one shared, server-side source of
truth for who owes what. See [`_docs/plan.md`](_docs/plan.md) for the product
spec and [`_docs/architecture.md`](_docs/architecture.md) for the technical
design.

## Getting started

1. **Create and activate a virtualenv:**

   ```bash
   python -m venv .venv
   source .venv/bin/activate      # Windows: .venv\Scripts\activate
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Create your local environment file:**

   ```bash
   cp .env.example .env
   ```

   The defaults in `.env.example` are enough to run locally: leaving
   `DATABASE_URL` unset uses a SQLite file (`db.sqlite3` in the project
   root), and `SECRET_KEY` falls back to an insecure dev-only value. Nothing
   in `.env` needs to be filled in to get started; it only needs to exist.

4. **Check the project is configured correctly:**

   ```bash
   python manage.py check
   ```

   This should exit with no errors or warnings.

5. **Run the development server:**

   ```bash
   python manage.py runserver
   ```

   Visit http://127.0.0.1:8000/.

## Configuration

Settings live under `config/settings/` and are environment-aware:

- `config/settings/dev.py` — local development. Runnable with no `.env` at
  all; `DEBUG = True`.
- `config/settings/prod.py` — production. Fails fast (`ImproperlyConfigured`)
  if `SECRET_KEY` or `ALLOWED_HOSTS` is not set in the environment.
- `config/settings/test.py` — used by the test suite (`pytest.ini`); an
  in-memory SQLite database and a fast password hasher.

All settings are read from environment variables via
[`django-environ`](https://django-environ.readthedocs.io/), sourced from a
`.env` file in the project root. `.env` is git-ignored and must never be
committed — copy `.env.example` to `.env` and edit it locally instead.

Key variables (see `.env.example` for the full, commented list):

| Variable | Purpose | Default |
|---|---|---|
| `SECRET_KEY` | Django's signing key | insecure dev-only value in `dev.py`; required in production |
| `ALLOWED_HOSTS` | Comma-separated allowed hostnames | `[]`; required in production |
| `DATABASE_URL` | Database connection URL | unset → SQLite (`db.sqlite3`) |
| `TIME_ZONE` | IANA timezone every due date is evaluated in | `UTC` |

To point the app at PostgreSQL instead of SQLite, set `DATABASE_URL` in
`.env` (e.g. `postgres://user:password@localhost:5432/chores`) — no source
change is required.

## Running tests

```bash
pytest
```

## Linting

```bash
ruff check .
ruff format --check .
```


## Deployment

`plan.md` §3 chose a browser app so any roommate can reach it from any device,
which only holds once it is hosted rather than run on somebody's laptop.

### 1. Configure

Everything comes from the environment (see `.env.example`). `config.settings.prod`
raises at import if `SECRET_KEY` or `ALLOWED_HOSTS` is missing — the process
refuses to start rather than serving with no signing key.

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | yes | `python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"` |
| `ALLOWED_HOSTS` | yes | Comma-separated hostnames |
| `DATABASE_URL` | no | Omit for SQLite. PostgreSQL needs no code change |
| `TIME_ZONE` | no | IANA name. Every due date and overdue check is evaluated here |
| `CSRF_TRUSTED_ORIGINS` | no | Needed behind a proxy that terminates TLS |
| `SECURE_SSL_REDIRECT` | no | Defaults to true |
| `SECURE_HSTS_SECONDS` | no | Defaults to one year |
| `WEB_CONCURRENCY`, `BIND` | no | Gunicorn workers and bind address |
| `FORWARDED_ALLOW_IPS` | no | Proxy IPs whose `X-Forwarded-Proto` is trusted |

`wsgi.py` and `asgi.py` already default to `config.settings.prod`; only
`manage.py` defaults to dev.

### 2. Release and run

```bash
export DJANGO_SETTINGS_MODULE=config.settings.prod
python manage.py check --deploy          # must report no issues
python manage.py migrate --noinput
python manage.py collectstatic --noinput
gunicorn config.wsgi --config gunicorn.conf.py
```

Static files are served by WhiteNoise from the app process — `architecture.md`
§1 chose that over a separate nginx, since a household-scale app does not need
a second process to hand out a stylesheet.

The `Procfile` runs the same two release steps on platforms that use one.

### 3. Create the first household

There is no public signup (`plan.md` §5), so the first admin is made from
outside the app:

```bash
python manage.py setup_household --household "Flat 3B" --admin Ana --pin 918273 \
    --seed seed.json      # optional; copy seed.example.json
```

It refuses to run if a household already exists.

### 4. The two scheduled jobs

```cron
# Materialise upcoming turns (rolling 8-week horizon).
17 3 * * *  cd /srv/chores && DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py generate_turns

# Flag turns nobody did in time.
23 3 * * *  cd /srv/chores && DJANGO_SETTINGS_MODULE=config.settings.prod .venv/bin/python manage.py mark_overdue
```

Both are idempotent, so a double run, a retry or an overlap changes nothing.

**Neither is load-bearing for correctness.** `architecture.md` §4 has the same
work run lazily whenever a roommate opens the app, so a household that never
sets up cron still sees the truth — the jobs only keep the horizon warm and the
overdue list current for someone who has not visited yet. Set them up anyway;
just do not treat a missed cron as data loss.
