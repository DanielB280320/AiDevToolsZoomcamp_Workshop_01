# Chore Manager for Roommates

A Django web app for a 5+ person shared household: chores rotate through
roommates on a fixed per-chore order and cadence, everyone signs in with a name
and PIN, completions and misses are logged, and absences are skipped rather than
counted as failures.

## Status

**Tasks 1–14 are done and committed. Next task: 15.**

Do not re-implement, re-groom or re-verify tasks 1–14. They shipped, the suite
is green, and re-opening them is what stalled this project once already. If a
finished task turns out to have a real bug that blocks the task in front of
you, fix that bug narrowly and move on.

Read `_docs/process.md` before starting a task. The short version: frame it in
a few minutes, build it, check it, commit it, next. One session does all of it
— no per-task subagent pipeline.

## Commands

- `uv pip install -r requirements.txt` — install dependencies into `.venv/`
- `source .venv/bin/activate` — activate the venv (assumed below)
- `pytest` — the whole suite
- `pytest accounts/tests/test_models.py` — one test file
- `ruff check .` / `ruff format .` — lint and format
- `python manage.py runserver` — dev server (settings default to `config.settings.dev`)
- `python manage.py migrate` — apply migrations
- `python manage.py generate_turns [--weeks N]` — materialise upcoming turns
- `python manage.py check --deploy` — production check (needs
  `DJANGO_SETTINGS_MODULE=config.settings.prod`, `SECRET_KEY`, `ALLOWED_HOSTS`)

## Layout

- `config/settings/` — `base.py` is shared; `dev.py`/`prod.py` override.
  `manage.py` defaults to dev, `wsgi.py`/`asgi.py` to prod. Config comes from
  the environment via `.env` (see `.env.example`), never from a branch in code.
- `accounts/` — `Household` and `Member`. `Member` is `AUTH_USER_MODEL`.
- `chores/` — chore definitions, and each chore's own rotation order.
- `core/` — the dashboard.
- `conftest.py` — shared fixtures: `household`, `members` (five, one admin),
  `admin_member`, `roommate`, `make_member`, `frozen_clock`. Tests live in
  `<app>/tests/`.
- `schedule/` — `Turn` (11), `services/generation.py` (12) and
  `services/transitions.py` (14). Miss, skip and swap land in 15, 18, 19.

## Docs

- `_docs/process.md` — how work is organized. Read this first.
- `_docs/plan.md` — the product spec, and why each decision was made.
- `_docs/architecture.md` — the Django design.
- `_docs/tasks.md` — the ordered backlog, 23 tasks.
- `_docs/roles.md` — optional split of the work, for risky tasks only.
- `_docs/followups.md` — things noticed but deliberately not done now.
- `others/prompts_track.md` — append-only prompt log; don't rewrite entries.

## How to build here

Scope first: build what the task asks for, not the generalized version. Prefer
the boring Django way. Don't add a field, a migration or an abstraction to close
a hypothetical hole — write it in `_docs/followups.md` instead.

Design rules that are load-bearing (these are cheap to follow while building,
and expensive to retrofit):

- Never store or log a PIN in plaintext. PINs go through Django's hasher stack,
  six digits minimum. `Member.password` holds the hash; use `set_pin`/`check_pin`.
- `prod.py` fails at import on missing config rather than falling back to
  something insecure. Dev-only fallbacks belong in `dev.py`.
- Turns are materialized rows, never computed on read. A membership change must
  not rewrite who was responsible in the past. `schedule/tests/
  test_history_survives_membership_changes.py` is the canary for this — if a
  change makes it fail, the change is wrong, not the test.
- `SKIPPED_AWAY` is its own terminal status, not a flavour of `MISSED`.
- Scope every queryset through `request.user.household`. Never trust a PK from
  the URL without filtering by household first.
- Turn generation and overdue marking are idempotent — they run on cron *and*
  lazily on dashboard load.
- Deactivate, don't delete: departed roommates and retired chores are
  soft-flagged so history survives.
- Dependencies are pinned in `requirements.txt`. Ask before adding one.
- `_docs/plan.md` decisions were made deliberately. If a change contradicts one,
  raise it rather than quietly overriding it.
