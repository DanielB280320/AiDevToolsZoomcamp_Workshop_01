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
