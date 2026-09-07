# Roles

`_docs/process.md` is the default: the main session frames, builds and checks
one task itself. These roles exist for the cases where splitting the work
actually helps — a risky task, or a second opinion you asked for on purpose.
They are not a pipeline every task has to pass through.

## Framing a task

Turn a backlog line into something buildable, in a few minutes:

- One sentence on what is true when this is done.
- 3–6 acceptance criteria, each checkable by looking at the result.
- Anything deliberately left out, one line each, in `_docs/followups.md`.

Enough for someone to build it cold. Not a specification. If you are writing
the tenth criterion, you are designing, not framing — cut back to the ones the
task in `tasks.md` actually asks for.

## Building a task

- Implement the criteria as written. Don't add to them.
- Test the behaviour you built, not the framework.
- Stay in the files the task needs. Touching a fifth unrelated file is a
  signal the scope drifted.
- Commit when it works.

If a criterion is genuinely wrong or impossible, say so and fix the criterion
once — then keep building. Don't stop and escalate.

## Reviewing a task

Only for the risky tasks named in `process.md`, or when explicitly asked.

- Check each frozen criterion against running code. Run the suite.
- Report only criteria that are **broken in running code**.
- A missing test for behaviour that works is a note, not a failure.
- Anything outside the criteria goes to `_docs/followups.md`, not into a
  verdict.
- Do not add criteria. Do not fix code.

Output is short: which criteria fail, what you did, what happened, and the
test result. If nothing is broken, say so in one line.
