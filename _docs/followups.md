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
- `ChoreForm.__init__` falls back to `self.instance.household_id` (an int) when
  no household is passed, then assigns it to the `household` FK. Both views
  always pass the household, so the path is unreachable today — but it would
  raise if a future caller relied on the fallback.
- pytest hands out one `client` per test, so two `as_<name>` fixtures both built
  on it are the same session. Caught in task 14's concurrency test, where it
  would have turned "two people racing" into "one person tapping twice". No
  other test currently takes two such fixtures, but it is an easy trap to
  re-enter — a second session needs its own `Client()`.
- Two things that hid work from the suite, both now fixed but worth knowing:
  `pytest.ini`'s `testpaths` did not list `core`, so `core/tests/` was never
  collected; and a `git add -A` swept a leftover QA scratch file
  (`test_zzqa_round4_probe.py`) into the repo. Prefer naming paths on `git add`,
  and check `testpaths` when adding tests to a new app.
- `architecture.md` §4 contradicts itself on swaps: its state diagram (line 157)
  shows `PENDING --> SWAPPED : two members trade turns`, while its prose (line
  173) says "Both turns stay `PENDING`; only the assignee moves." `tasks.md` §19
  agrees with the prose, so task 19 followed the two that agree and left the
  `SWAPPED` status defined but unused. Worth reconciling the diagram, or finding
  a use for the status.
