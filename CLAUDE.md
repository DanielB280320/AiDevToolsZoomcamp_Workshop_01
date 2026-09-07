# Chore Manager for Roommates

A Django web app for a 5+ person shared household: chores rotate through
roommates on a fixed per-chore order and cadence, everyone signs in with a name
and PIN, completions and misses are logged, and absences are skipped rather than
counted as failures.

**Status:** tasks 1-2 done — the project skeleton, layered settings and the
`Household`/`Member` models exist and the first migration has been applied.
Task 3 (test setup and fixtures) is next; there is no test suite yet, so the
`pytest` commands below have nothing to run until it lands.

Commands

- `uv pip install -r requirements.txt` - install dependencies into `.venv/`
- `source .venv/bin/activate` - activate the venv (all commands below assume it)
- `pytest` - the whole suite
- `pytest tests/test_home.py` - one test file
- `ruff check .` / `ruff format .` - lint and format
- `python manage.py runserver` - dev server (settings default to `config.settings.dev`)
- `python manage.py migrate` - apply migrations
- `python manage.py check --deploy` - production config check (needs
  `DJANGO_SETTINGS_MODULE=config.settings.prod`, `SECRET_KEY` and `ALLOWED_HOSTS`)

Layout

- `config/settings/` - `base.py` holds everything shared; `dev.py` and `prod.py`
  override. `manage.py` defaults to dev, `wsgi.py`/`asgi.py` default to prod.
  Config comes from the environment via `.env` (see `.env.example`), never from
  a branch in code.
- `accounts/` - `Household` and `Member`. `Member` is `AUTH_USER_MODEL`.
- Later apps (`chores`, `schedule`, `core`) are laid out in `architecture.md` §2
  and do not exist yet.

Docs

- `_docs/process.md` - how work is organized
- `_docs/plan.md` - the product spec. Every scoping decision, with the
  alternatives rejected and why. The source of truth for *what* to build.
- `_docs/architecture.md` - the Django design: app layout, data model, the
  scheduling engine, auth. The source of truth for *how*.
- `_docs/tasks.md` - the ordered backlog, 23 tasks, each tracing back to a
  `plan.md` section.
- `others/prompts_track.md` - a running log of the prompts used on this project.
  Append to it when the user asks to track a prompt; do not rewrite past entries.

Rules

- Dependencies are pinned in `requirements.txt`. Do not add one without asking.
- Read `_docs/plan.md` before changing behaviour. Decisions there were made
  deliberately with alternatives considered — if a change contradicts one, raise
  it rather than quietly overriding it.
- Tasks 1-3 in `_docs/tasks.md` must land in that order. `Member` is the custom
  `AUTH_USER_MODEL` and must exist before the first `makemigrations`;
  retrofitting it later means rebuilding migration history.
- Never store or log a PIN in plaintext. PINs go through Django's hasher stack,
  minimum six digits. `Member.password` holds the hashed PIN; use `set_pin` /
  `check_pin`.
- `prod.py` must fail at import on missing config rather than starting with an
  insecure fallback. Dev-only fallbacks belong in `dev.py`.
- Turns are materialized rows, never computed on read. A membership change must
  not rewrite who was responsible in the past — that is the guarantee the whole
  accountability feature rests on.
- `SKIPPED_AWAY` is its own terminal status, not a flavour of `MISSED`. A planned
  absence must never be recorded as a failure.
- Scope every queryset through `request.user.household`. Never trust a PK from
  the URL without filtering by household first.
- Turn generation and overdue marking must be idempotent — they run on cron *and*
  lazily on dashboard load, so a second run must change nothing.
- Deactivate, don't delete: departed roommates and retired chores are soft-flagged
  so history survives.
