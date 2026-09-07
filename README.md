# Homework 1: AI-Native Developer Workflow

In this homework, we'll build an application with AI — but instead of us handing you a finished spec, you'll turn a vague idea into one yourself, then implement it in Django.

You can use any coding agent you want: Claude Code, Codex CLI, Gemini CLI, Cursor, Aider, GitHub Copilot, etc. Pick **one** and stick with it for the whole homework — with chat-based tools you'd need to copy code back and forth, so we recommend an agent that can edit files and run commands directly in your homework repository.

You will only need Python to get started (we also recommend that you use `uv`). You don't need to know Python or Django for doing this homework.

## Homework Idea

For this homework, we start with a very vague idea:

> A tool for managing shared household chores

We don't specify anything else, and most of you will finish with different homework solutions.

In this homework, we want to turn this vague description into a clear specification.

---

## Question 1: Select your coding agent

You can use any coding agent you want. Which one did you choose?  

**Answer: `Claude Code (Opus 5)`** — used for the whole project: spec, backlog, all 23
tasks, tests and commits. Prompt log: [`others/prompts_track.md`](others/prompts_track.md).

---

## Question 2: Turn the idea into a spec

Open a chat assistant and brainstorm with a prompt like:

```text
I want to build a tool for managing shared household chores.

Help me set the scope for this homework precisely. I want to brainstorm with you
and understand how the tool should work. Give me options.

Ask me one question at a time and keep your output short.
```

Answer its questions, then ask it to save everything to a markdown file. 

What are the 2-4 features your spec settled on?

Spec: [`_docs/plan.md`](_docs/plan.md). It settled on **four** features:

**Answer:**

1. **Fixed per-chore rotation and cadence** (§2) — each chore has its own roommate
   order and frequency; turns are generated eight weeks ahead.
2. **Name + PIN sign-in with admin roles** (§5, §7) — no email or signup; only admins
   edit chores and roommates.
3. **Completion tracking and history** (§4) — every turn is a stored row with a status
   and who actually did it, so disputes are settled from the record.
4. **Away handling and swaps** (§8) — a turn during a declared absence is *skipped*,
   not *missed*, and passes to the next person.

## GitHub Repository

Create an empty GitHub repository, clone it locally. Create two files there:

- `.gitignore`
- `README.md`
- `_docs/plan.md` with the plan

Commit and push.

---

## Question 3: Django project

For this homework we'll use Django. 

Ask your agent to install Django and create a project and an app for it. At some point, you will need to include the app you created in the project.

What's the file you need to edit for that?

- `settings.py`
- `manage.py`
- `urls.py`
- `wsgi.py`

For this and next questions you can ask your coding assistant to select the correct option.

**Answer: `settings.py`** — the app is added to `INSTALLED_APPS`. Here settings are a
package, so it is [`config/settings/base.py`](config/settings/base.py):

```python
LOCAL_APPS = ["accounts", "chores", "schedule", "core"]
INSTALLED_APPS = DJANGO_APPS + LOCAL_APPS
```

---

## Question 4: Backlog

Then give your agent the `plan.md` and ask it to propose a small backlog of tasks for building this in Django. Write the result to `backlog.md`.

What's task 1 in the backlog your agent came up with?

Backlog: [`_docs/tasks.md`](_docs/tasks.md), 23 ordered tasks.

**Answer: `Task 1 — "Project skeleton and shared persistent storage`:** a runnable Django project
with `dev`/`prod`/`test` settings reading `SECRET_KEY` and `DATABASE_URL` from `.env`, on
SQLite with a documented path to PostgreSQL, and an explicit timezone. It is first
because `plan.md` §9 requires one shared server-side database.

---

## Question 5: First version

Implement the first few tasks. Just open your agent and say:

```
Implement task #1 from backlog.md
```

Run the server. Which command do you use to start the Django development server?

- `uv run python manage.py runserver`
- `uv run django-admin startserver`
- `python manage.py start`
- `uv run python app.py runserver`

**Answer: `uv run python manage.py runserver`** — the dev server is a `manage.py`
subcommand. Here the venv is activated first, so it is `python manage.py runserver`
(settings default to `config.settings.dev`).

---

## Question 6: Tests

After implementing a few items from the backlog, let's make sure the code is covered with tests. 

- Tell the agent we want to cover the code with tests
- Ask it which scenarios we should cover
- Make sure they make sense
- Let it implement them and run them

What's the command you use for running tests in the terminal?

- `pytest`
- `uv run python manage.py test`
- `python -m django run_tests`
- `django-admin test`

**Answer: `pytest`** — pytest + `pytest-django`, configured in [`pytest.ini`](pytest.ini)
(forces `--ds=config.settings.test`), fixtures in [`conftest.py`](conftest.py).

Scenarios covered: sign-in (wrong PIN, unknown name, deactivated member, lockout),
admin-only views actually refusing non-admins, household scoping, schedule generation
(rotation wrap-around, month-end dates, idempotent re-runs), turn transitions with an
`ActivityLog` row each, and a canary test that history survives membership changes.
