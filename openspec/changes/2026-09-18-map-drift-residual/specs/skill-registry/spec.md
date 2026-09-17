# Spec Delta: skill-registry

## MODIFIED: `PHASE_SKILL_MAP.md` status labels match live graph calls

The `skills/PHASE_SKILL_MAP.md` document's ✅/📦 status labels MUST match
exactly the skills that the active graph nodes call via `skills.get("<name>")`
— a skill marked ✅ MUST have at least one `skills.get("<name>")` call in
`graph/nodes/*.py`; a skill with no such call MUST be marked 📦.

### Scenarios

**Status labels match code**
- DISCOVER row lists `interview-me` (✅) — called at
  `graph/nodes/discover.py:224` (generic interview path).
- PLAN row lists `planning-and-task-breakdown` (✅) — called at
  `graph/nodes/plan.py:107`.
- DEFINE row lists `source-driven-development` (✅) — called at
  `graph/nodes/define.py:283`.
- PLAN row lists `code-simplification` (📦) — no `skills.get` call in
  `graph/`; downloaded and ready to wire only.
- BUILD row `context-engineering` and VERIFY/SEED rows
  `debugging-and-error-recovery` remain 📦 — no `skills.get` call in `graph/`.

**Coverage counts match the labels**
- Coverage Summary "Active in graph" count equals the number of ✅-labeled
  skills that have a live `skills.get` call in `graph/nodes/*.py`.
- "Ready to wire" count equals the number of 📦-labeled skills.

## MODIFIED: Wiring Priority lists only unwired skills

The Wiring Priority section MUST NOT list a skill as a wiring candidate if the
skill is already wired (has a live `skills.get` call in `graph/nodes/*.py`).

### Scenarios

**No already-wired skill appears as a wiring candidate**
- `planning-and-task-breakdown` (wired at `plan.py:107`) and
  `source-driven-development` (wired at `define.py:283`) do NOT appear in the
  Wiring Priority list.
- The remaining genuinely-unwired 📦 skills (`documentation-and-adrs`,
  `context-engineering`, `ci-cd-and-automation`, `browser-testing-with-devtools`,
  `code-simplification`) remain valid wiring candidates.
