# Chore Manager — Backlog

Every task below traces to a decision in [`plan.md`](./plan.md); the section it serves is named in its description. [`architecture.md`](./architecture.md) covers the *how* where a task needs it, but each task states enough to be picked up cold.

**Ordering:** tasks 1–3 must land in that order — the roommate model has to exist before the first database migration, or replacing it later means rebuilding the migration history. After task 5, most tasks can be worked in parallel.

---

## 1. Project skeleton and shared persistent storage
Goal: A runnable Django project backed by a single shared database.
Description: Set up the project package with environment-aware settings reading secrets and the database URL from a `.env` file, and confirm it starts against SQLite with a documented path to PostgreSQL. `plan.md` §9 requires one shared source of truth rather than per-device storage, so this is server-side database state from the start — nothing in browser storage. Set the timezone explicitly, since due dates and overdue checks depend on it.

## 2. Household and roommate list
Goal: Roommates are a custom, variable-length list rather than a fixed number.
Description: Model the household and its members, with each member carrying a display name, an admin flag, an active flag and a join date. `plan.md` §1 calls for 5+ roommates defined by a custom list, so nothing may hardcode a household size. Deactivating a departed roommate must be a soft flag rather than a delete, because §4's history has to survive their leaving. This is the first migration — the member model is the app's user model and must be settled before it runs.

## 3. Test setup and household fixtures
Goal: Tests run green against a realistic five-roommate household.
Description: Configure the test runner and add fixtures producing a household with five members, one of them an admin, plus a time-freezing helper for the date-driven logic in later tasks. `plan.md` §1's "5+ roommates" is the shape every later feature is tested against, so the fixture reflects it. Include one smoke test proving the fixtures save.

## 4. Name-and-PIN sign-in
Goal: A roommate identifies themself with a name and a PIN.
Description: Implement authentication by display name plus PIN, storing the PIN hashed and never in plaintext, and enforce a six-digit minimum. `plan.md` §5 chose this over full email accounts for low friction and over an open shared link because §4's tracking is meaningless if the system cannot tell who acted. Cover correct PIN, wrong PIN, unknown name and deactivated member with tests; the browser screens are task 6.

## 5. Sign-in throttling
Goal: Repeated wrong-PIN guesses lock an account temporarily.
Description: Record sign-in attempts and block further tries after five failures within fifteen minutes, keeping failure messages generic so the form does not reveal which names exist. `plan.md` §5's PIN choice trades security for convenience, and a short numeric PIN is guessable quickly against an endpoint that allows unlimited attempts. This is the mitigation that makes the §5 decision safe enough for a household tool.

## 6. Sign-in and sign-out screens on any device
Goal: Roommates can sign in from a phone, laptop or shared tablet.
Description: Build the sign-in form on top of task 4, plus sign-out, and require authentication everywhere except the sign-in page. Add the shared page layout and responsive styling the rest of the app extends. `plan.md` §3 chose a browser app precisely so no roommate has to install anything, which makes small-screen layout a requirement rather than a polish item.

## 7. Admin management of the roommate list
Goal: An admin can add a roommate, deactivate one, and reset a forgotten PIN.
Description: Build admin-only screens to list members, add one with a starting PIN, grant or revoke admin status, and deactivate someone who has moved out. `plan.md` §1 requires the roommate list to change over time, and §5's no-email decision means PIN recovery cannot be self-service — an admin resets it instead. This answers the spec's open question about forgotten PINs.

## 8. Chore definitions with per-chore cadence
Goal: The household's chores exist, each with its own frequency.
Description: Model a chore with a name, description, repeat frequency (for example every week, every two weeks, every month), a start date and an active flag, and build screens to create and edit them. `plan.md` §2 notes that different chores may not share a cadence, so frequency belongs to each chore rather than to the household — this answers the spec's open question about whether cadence is uniform. Archive chores instead of deleting them so past records stay intact.

## 9. Admin-only editing of the chore list
Goal: Everyone can see the chore list; only admins can change it.
Description: Gate chore creation, editing and archiving behind the admin flag while leaving the list viewable by all roommates, and add reusable permission guards the rest of the app uses. `plan.md` §7 rejected open editing because with 5+ roommates it risks accidental deletions or one person unilaterally changing everyone's workload. Test that a non-admin is refused, rather than merely having the buttons hidden.

## 10. Per-chore rotation order
Goal: Each chore cycles through the roommates in its own set order.
Description: Let an admin arrange the roommates into an ordered rotation for a single chore, stored per chore rather than household-wide. `plan.md` §2 is explicit that each chore needs its own rotation order, so the bins rota and the bathroom rota can run through people differently. The ordering must be explicit and reorderable, not derived from join date or alphabetical name.

## 11. The turn record
Goal: A single occurrence of a chore by one roommate is a stored record.
Description: Model a turn holding its chore, the assigned roommate, the cycle it belongs to, its due date, its status, and who completed it and when. `plan.md` §4 requires a completion log per chore, per roommate, per cycle, which means occurrences must be stored rows rather than something calculated on the fly at display time. Include a uniqueness rule per chore and cycle so the same turn can never be created twice.

## 12. Generating the upcoming schedule
Goal: Future turns appear automatically from each chore's rotation and cadence.
Description: Create turns for a rolling window ahead (default eight weeks) by walking each active chore's rotation in order and stepping due dates by its cadence, writing the assigned roommate onto each turn as it is created. `plan.md` §2 chose fixed rotation for predictability — every roommate should be able to see their turns coming well in advance. Make re-running safe and harmless, and test month-end dates and rotation wrap-around.

## 13. Proving history survives roommate changes
Goal: Adding or removing a roommate never rewrites who was responsible in the past.
Description: Write a test that generates turns, completes some, then adds a new roommate and deactivates another, asserting no past turn changed hands and only future unfilled turns differ. `plan.md` §1 allows the roommate list to change and §4 depends on the record being trustworthy, and those two only coexist if history is fixed once written. This is a standalone task because it is the guarantee most easily broken by a later change.

## 14. Marking a chore complete
Goal: A roommate can mark a chore done and it is attributed to them.
Description: Add the action that moves a turn to completed, stamped with the time and the person who did it, recorded separately from whoever was assigned so that covering for someone is captured accurately. `plan.md` §4 makes attribution the whole point — the log is what settles "I did do it last week". Handle two roommates tapping complete at the same moment so the second is a harmless no-op rather than a duplicate entry.

## 15. Flagging missed chores
Goal: A chore not done by its due date is recorded as missed.
Description: Move overdue turns to a missed status once the due date and any grace period have passed, running both as a scheduled command and automatically whenever a roommate opens the app. `plan.md` §4 names surfacing who missed which chores as a core requirement, and §6 keeps reminders inside the app, so the state must be correct at the moment someone looks. Running it twice must change nothing the second time.

## 16. Home screen with due and overdue chores
Goal: Opening the app makes it obvious what you owe and what is late.
Description: Build the landing screen showing the signed-in roommate's upcoming turns, everything overdue across the household, and what is due soon, refreshing missed status on load. `plan.md` §6 chose in-app reminders as the only notification channel, which puts the entire reminder burden on this screen — due and overdue states must be impossible to miss. Show overdue items to every roommate rather than only the assignee, answering the spec's open question on visibility: shared visibility is what gives the reminder weight in a peer household.

## 17. Declaring an absence
Goal: A roommate can record dates they will be away.
Description: Let a roommate enter a start date, end date and optional reason for an absence, and let an admin enter one on their behalf, recording which of the two did it. `plan.md` §8 requires away handling, and its open question about who marks someone away is answered here by allowing both. This task covers recording the absence only; its effect on the schedule is task 18.

## 18. Skipping a turn for an absence
Goal: A chore falling during an absence is skipped, not counted against anyone.
Description: When a turn's due date falls inside the assigned roommate's declared absence, mark it skipped-for-absence and pass it to the next roommate in that chore's rotation. `plan.md` §8 is explicit that a planned absence must be distinguishable from a genuine miss, so skipped must be its own status rather than a variety of missed — otherwise §4's record would blame someone for a chore they were never due to do. Passing it on rather than leaving it undone answers the spec's open question, since the household should not go without a clean bathroom because one person is on holiday. Test that an absent roommate is never marked missed.

## 19. Swapping turns
Goal: Two roommates can trade turns and the trade stays visible.
Description: Let a roommate propose swapping one of their upcoming turns with another roommate's, exchanging the assignments together as one change and linking the two turns so the trade is traceable. `plan.md` §8 asks for swapping alongside skipping, and §4's accountability goal means a swap should be recorded rather than silently rewriting who was assigned. Both turns stay pending; only the assignment moves.

## 20. Change log for dispute resolution
Goal: Every change to a chore's state is recorded and never edited.
Description: Record an append-only entry for each completion, miss, skip and swap, capturing who acted, when, on what, and what changed. `plan.md` §4 justifies tracking by the need to settle disputes, and a turn's current status alone cannot say who changed it or when — which is exactly what a disagreement turns on. Entries are written by the actions themselves so nothing can change state without leaving a trace.

## 21. History and fairness view
Goal: Roommates can look up who did what, and see how the load has fallen.
Description: Build a paginated history screen over completed, missed and skipped turns with filters by roommate, chore, status and date range, plus a per-roommate summary of completed against missed. `plan.md` §4 calls for a history log and for surfacing who missed which chores, and this is the screen where both are actually read. Favour clarity over density — this is the screen people open when they disagree.

## 22. First-run setup
Goal: A fresh installation can be brought up with one command.
Description: Provide a setup command that creates the household, its first admin with a chosen PIN, and optionally an initial set of chores with rotations from an editable seed file. `plan.md` §5 has no public signup and §7 requires an admin to exist before chores can be added, so the first admin has to be created outside the app — this answers the spec's open question on how the first admin is designated. Verify it runs against an empty database.

## 23. Deployment
Goal: The app runs somewhere all the roommates can reach it.
Description: Complete production configuration with allowed hosts, secure cookies, static file serving and a production web server, and document the environment variables and the two scheduled jobs that generate upcoming turns and flag missed ones. `plan.md` §3 chose a browser app so any roommate can reach it from any device, which only holds once it is hosted rather than run locally. Confirm it boots with debug mode off.
