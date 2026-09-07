# Chore Manager for Roommates — Project Specification

**Purpose of this document:** This spec captures every scoping decision made during discovery, along with the reasoning behind it, so it can be used as the foundation for spec-driven development. Each section states the decision, the alternatives considered, and any constraints that shaped it.

---

## 1. Target Users

**Decision:** Roommates (non-family), 5+ people, defined via a custom list.

- Alternatives considered: solo/personal household, family with kids, generic "any household" tool.
- Roommates were chosen specifically because the tool needs to support **fairness and accountability among peers** rather than parent-managed assignment. This shapes later decisions (fixed rotation, login system, admin roles).
- The household size is **variable and custom**, not fixed at a number like 3 or 4 — the system must support adding/removing roommates from a list rather than hardcoding a count.

---

## 2. Chore Assignment Mechanic

**Decision:** Fixed rotation. Chores cycle through the roommate list in a set order.

- Alternatives considered:
  - *Points/bidding system* — rejected as too complex for the target scope; requires negotiation logic and point-value tuning.
  - *Random assignment* — rejected for unpredictability; roommates can't plan ahead.
  - *Manual assignment by one person* — rejected because it puts the burden (and social friction) on a single roommate rather than distributing chores automatically.
- Fixed rotation was chosen for **simplicity and predictability**: every roommate knows in advance when their turn is coming, and no one has to negotiate or manually reassign week to week.
- **Implication for design:** each chore needs its own rotation order and cadence (e.g., weekly, biweekly), since different chores may not share the same roommate order or frequency.

---

## 3. Platform / Form Factor

**Decision:** Web app, accessible via browser on any device.

- Alternatives considered: native mobile app (iOS/Android), chatbot (Slack/Discord/WhatsApp), shared doc/spreadsheet.
- Web app was chosen for **maximum accessibility with lowest friction** — no app store installs, works on any roommate's device (phone, laptop, shared household tablet).
- **Constraint this introduces:** as a browser-based tool without a dedicated backend server, it cannot natively send push notifications or real emails. This directly shaped the reminders decision (Section 6).

---

## 4. Accountability & Tracking

**Decision:** Full tracking — mark chores complete, maintain a history log, and surface who missed which chores.

- Alternatives considered:
  - *Schedule-only, no tracking* — rejected; roommates specifically wanted to know who did/didn't do their chore, not just what's assigned.
  - *Reminders only, no logging* — rejected for the same reason; without history, disputes ("I did do it last week") can't be resolved.
- Full tracking was chosen because **accountability is the core value proposition** for a roommate (non-family) context — trust and fairness depend on a visible, shared record.
- **Implication for design:** the data model needs a persistent completion log per chore, per roommate, per cycle (timestamp, completed/missed status), not just a "current assignee" field.

---

## 5. Access & Authentication

**Decision:** Simple login per roommate — name + PIN (no email/password, no shared open link).

- Alternatives considered:
  - *No login, shared link everyone edits* — rejected; with full tracking and accountability as a goal, the system needs to know **who** is marking a chore complete, or the log becomes meaningless.
  - *Full accounts (email/password)* — rejected as overkill for a small trusted household group; adds friction (signup flow, password resets, verification) without meaningful benefit over a lightweight PIN.
- Name + PIN strikes a balance: **lightweight enough for daily use, but attributable enough for accountability and role permissions** (see Section 7).

---

## 6. Reminders

**Decision:** In-app reminders only — due/overdue chores are clearly flagged when a roommate opens the app.

- Alternatives considered:
  - *Email reminders* — initially preferred, but ruled out once the platform constraint was clarified: a client-side web app with no backend server **cannot actually send real emails**. There's no server-side process to trigger and deliver them.
  - *Simulated email preview* (fake email-style text shown in-app, not actually sent) — considered as a compromise, but rejected in favor of a cleaner, fully-functional in-app-only approach.
- In-app reminders were chosen because they are **the only option that fully works within the web-app/no-backend constraint**, while still achieving the underlying goal: making it obvious and unavoidable when a chore is due or overdue.
- **Note for future iterations:** if real email/push reminders become a requirement later, this will require adding a backend service (e.g., a scheduled job + email API), which is a separate infrastructure decision outside this spec's current scope.

---

## 7. Chore List Management & Permissions

**Decision:** Role-based editing — only certain roommates ("admins") can add, edit, or remove chores from the list. Other roommates can view the list and mark their own assignments complete, but cannot modify the chore list itself.

- Alternatives considered:
  - *Anyone can add/edit/remove chores* — rejected; with 5+ roommates, an open-edit model risks chore-list churn, accidental deletions, or one person unilaterally changing everyone's workload.
  - *Fixed list, no editing at all* — rejected as too rigid; households' chore needs change over time (new chores, discontinued ones).
- Role-based permissions were chosen to **balance flexibility with stability** — the list can evolve, but changes go through designated roommates rather than being a free-for-all.
- **Implication for design:** the data model needs a role/permission flag per roommate (e.g., `isAdmin: true/false`), and the UI needs to conditionally show/hide chore-editing controls based on that flag.

---

## 8. Away / Absence Handling

**Decision:** Support skipping or swapping a roommate's turn when they're away (e.g., on vacation).

- Alternatives considered:
  - *No special handling — rotation continues, they catch up later* — rejected; this creates unfairness (missed chores pile up or get silently skipped without anyone else covering) and complicates the accountability log (was it a "miss" or a planned absence?).
- Explicit away/skip/swap handling was chosen because **fixed rotation is only fair if it accounts for real-life absences** — otherwise the accountability tracking (Section 4) would unfairly flag someone as having missed a chore they were never actually supposed to do.
- **Implication for design:** the system needs a distinct status beyond "completed" / "missed" — something like "skipped (away)" — plus a mechanism to either reassign that turn to the next person in rotation or leave it vacant for that cycle, and a way for a roommate to mark themselves away in advance.

---

## 9. Data Persistence

**Decision:** Data is stored persistently and shared across all roommates using the app (not local to a single device/browser).

- This follows directly from the multi-user, accountability-driven nature of the tool: chore assignments, completion history, and roommate roles must be **the same shared source of truth** for everyone, regardless of which device or browser they log in from.

---

## Summary Table

| Area | Decision |
|---|---|
| Users | Roommates, 5+, custom list |
| Assignment mechanic | Fixed rotation |
| Platform | Web app (browser, any device) |
| Tracking | Full (completion + history + missed chores) |
| Login | Name + PIN per roommate |
| Reminders | In-app only (due/overdue flags) |
| Chore list editing | Admin-only roommates |
| Away handling | Skip/swap turns supported |
| Data storage | Persistent, shared across all users |

---

## Open Questions for Next Steps (Not Yet Scoped)

These weren't covered in discovery and should be addressed before/during build:

- Chore cadence: are all chores weekly, or does cadence vary per chore (daily/weekly/biweekly/monthly)?
- Initial chore list: what are the actual chores to seed the system with?
- Admin assignment: how is the first admin designated, and can admin status be transferred?
- PIN recovery: what happens if a roommate forgets their PIN?
- Away workflow: does the away roommate mark themselves away, or does an admin do it on their behalf?
- Notification visibility: should overdue chores be visible to *all* roommates (peer pressure/transparency) or only to the assigned person?
