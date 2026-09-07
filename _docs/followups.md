# Follow-ups

Things noticed while building something else. One line each. Not blockers —
these are picked up deliberately, after the backlog in `_docs/tasks.md` is
through, or promoted to a real task when one of them starts to matter.

- Task 4 hardening: `Member.pin_is_validated` + `save()` guard (migration
  `0004`) was added over four QA rounds to stop an operator superuser being
  attached to a household. It works and the suite is green, but it is heavier
  than the task asked for — revisit whether the column is worth keeping, or
  whether an admin-form validator would do.
- `config/tests/test_settings.py` (440 lines, 19 tests) shells out to a fresh
  interpreter per case to test Django settings. Green, but it is the slowest
  and least load-bearing part of the suite.
- Task 8 (chores with per-chore cadence) landed as a scaffold in `be7d680`.
  Confirm it meets its criteria before counting it done.
