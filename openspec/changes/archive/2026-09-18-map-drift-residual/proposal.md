# Proposal: map-drift-residual

## Why

`skills/PHASE_SKILL_MAP.md` was corrected for DISCOVER/REFLECT/SHIP drift in
`424c180` (skill-map-arckit-fit), but a verification pass against the live code
found 3 remaining discrepancies where the map's ✅/📦 status labels do not
match what the graph nodes actually call:

1. **`code-simplification`** — the map marks it ✅ in PLAN, but no node calls
   `skills.get("code-simplification")` anywhere in `graph/`. It is downloaded
   and ready to wire, not active.
2. **`planning-and-task-breakdown`** — the map marks it 📦 (ready to wire) in
   PLAN, but it is called live at `graph/nodes/plan.py:107`. It is already
   active; the status is wrong.
3. **`source-driven-development`** — the map marks it 📦 in DEFINE, but it is
   called live at `graph/nodes/define.py:283`. It is already active; the
   status is wrong.

Additionally, the DISCOVER row omits `interview-me`, which is called live at
`graph/nodes/discover.py:224` (the generic interview path when not
auto-approve / not-ArcKit / no prior interview notes). And the Wiring Priority
section lists `planning-and-task-breakdown` → PLAN and
`source-driven-development` → DEFINE as items to wire, even though both are
already wired (calls exist in `plan.py:107` and `define.py:283`).

The map is the document an engineer opens to ask "which skills govern this
phase, and which are ready to wire next?" — it currently answers wrong on
these four rows and on the priority list.

This is a **doc-only** correction. No code changes: the `interview-me`,
`planning-and-task-breakdown`, and `source-driven-development` lookups are
intended, live code paths. The fix is to make the map reflect the code, not to
remove or add calls in the nodes.

## What

- **Task 1** — Correct the ✅/📦 status labels in `skills/PHASE_SKILL_MAP.md`:
  - DISCOVER row: add `interview-me` ✅ (live call at `discover.py:224`).
  - PLAN row: `planning-and-task-breakdown` 📦 → ✅ (live at `plan.py:107`).
  - PLAN row: `code-simplification` ✅ → 📦 (no caller in `graph/`).
  - DEFINE row: `source-driven-development` 📦 → ✅ (live at `define.py:283`).
  - Leave `context-engineering` (BUILD) and `debugging-and-error-recovery`
    (VERIFY/SEED) as 📦 — they are correctly not wired.
  - Update the Coverage Summary counts to match (active 15 → 17, ready-to-wire
    5 → 3).
- **Task 2** — Fix the stale Wiring Priority section:
  - Remove the "wire `planning-and-task-breakdown` → PLAN" and "wire
    `source-driven-development` → DEFINE" entries (both already wired).
  - Re-prioritize the remaining genuinely-unwired 📦 skills:
    `documentation-and-adrs` (PLAN), `context-engineering` (BUILD),
    `ci-cd-and-automation` (SHIP), `browser-testing-with-devtools` (VERIFY).
- **Task 3** — Close-out gate (verification only).

## Non-goals

- No code changes: the live `skills.get(...)` calls in `discover.py`,
  `plan.py`, and `define.py` are left untouched.
- No new skills authored or downloaded.
- No routing / Decision-2 / loop-budget change.
- `context-engineering` and `debugging-and-error-recovery` remain 📦 (correctly
  unwired); this change does not wire them up.

## Impact

| Area | Change |
|------|--------|
| `skills/PHASE_SKILL_MAP.md` | Doc-only status + priority corrections (Tasks 1–2) |
| Risk | None — no code, no schema, no state, no routing changes |
