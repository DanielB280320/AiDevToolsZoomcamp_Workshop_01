# How work is organized

One task at a time, from `_docs/tasks.md`, in order. Ship it, commit it, move on.

## The loop

1. **Frame it.** Read the task in `tasks.md`. Write down the goal in one
   sentence and 3–6 acceptance criteria you can check by looking at the
   result. Put them in the issue (or in the commit message if there is no
   issue). This takes minutes, not a round trip.
2. **Build it.** Implement exactly those criteria. Write tests for the
   behaviour you added.
3. **Check it.** Re-read the criteria, verify each one against running code,
   run `pytest`. Fix what is broken.
4. **Commit, closed the issue and move to the next task.**

The main session does this itself. Do not launch a subagent per step.

## Criteria are frozen

Once step 1 is written down, the criteria for that task do not change. They
are the definition of done and the whole definition of done.

Anything you notice later that is not in them — a sharper edge case, a
neighbouring bug, a hardening idea — is **out of scope for this task**. Add it
to `_docs/followups.md` in one line and keep going. It is not a reason to
reopen, re-groom, or fail the task.

## Two rounds, then ship

If step 3 finds problems, you get at most **two** fix rounds. If something is
still failing after that, commit what passes, write the remainder into
`_docs/followups.md`, and move to the next task. A task that has been open
for three rounds is a scoping problem, not a quality problem.

## Done stays done

A task that landed is done. Do not revisit it because a later reading of the
spec suggests it could be stricter. The only reason to touch finished work is
a real, reproducible bug that blocks the task in front of you.

## When to bring in help

Default is no subagent. Launch one only when the task genuinely needs it:

- **A second pair of eyes on risky work** — authentication, permissions, or
  anything that writes history that must not be rewritten (tasks 11, 13, 20).
  Ask for a review against the frozen criteria only. Its output is a short
  list of criteria that are actually broken in running code.
- **A wide search** across many files where you only need the conclusion.

A missing test for a criterion that the code satisfies is a note, not a
failure. Roles, if you want them written out, are in `_docs/roles.md`.

## Scope discipline

- Build what the task asks for. Not the generalized version of it.
- Prefer the boring Django way over a custom mechanism.
- Don't add a model field, a migration or a new abstraction to close a
  hypothetical hole. If the hole is real, it is a follow-up task with its own
  criteria.
- Commit messages are a few lines: what changed and why. Not a report.
