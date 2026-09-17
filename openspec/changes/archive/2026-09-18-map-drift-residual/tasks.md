# Tasks: map-drift-residual

## 1. Correct ✅/📦 status labels in `PHASE_SKILL_MAP.md`

**Files:**
- Modify: `skills/PHASE_SKILL_MAP.md` (doc-only)

Steps:
1. DISCOVER section: add an `interview-me` ✅ row — it is called live at
   `graph/nodes/discover.py:224` (generic interview path: not auto-approve,
   not ArcKit-auto-populated, no prior interview notes). Purpose: "Structured
   user interview to extract requirements".
2. PLAN section: change `planning-and-task-breakdown` from 📦 to ✅ — it is
   called live at `graph/nodes/plan.py:107`.
3. PLAN section: change `code-simplification` from ✅ to 📦 — no node calls
   `skills.get("code-simplification")`; it is downloaded/ready-to-wire only.
4. DEFINE section: change `source-driven-development` from 📦 to ✅ — it is
   called live at `graph/nodes/define.py:283` (one of the two parallel LLM
   calls alongside `api-and-interface-design`).
5. Leave `context-engineering` (BUILD row) and `debugging-and-error-recovery`
   (SEED_DATA + VERIFY rows) as 📦 — correctly unwired.
6. Update Coverage Summary counts: active-in-graph 15 → 17
   (`interview-me` + `planning-and-task-breakdown` + `source-driven-development`
   now ✅; `code-simplification` drops from active); ready-to-wire 5 → 3.

## 2. Fix the stale Wiring Priority section

**Files:**
- Modify: `skills/PHASE_SKILL_MAP.md` (doc-only)

Steps:
1. Remove the `planning-and-task-breakdown` → PLAN entry (HIGH) — already wired
   (`plan.py:107`).
2. Remove the `source-driven-development` → DEFINE entry (MED) — already wired
   (`define.py:283`).
3. Keep / re-prioritize the remaining genuinely-unwired 📦 skills:
   `documentation-and-adrs` → PLAN, `context-engineering` → BUILD,
   `ci-cd-and-automation` → SHIP, `browser-testing-with-devtools` → VERIFY.
4. Keep `code-simplification` → PLAN as a 📦 wiring candidate (now that its
   status is correctly 📦).

## 3. Close-out gate

- Full gate per AGENTS.md (7 hang files `--ignore`, 5 out-of-scope baseline
  failures `--deselect`) → 0 new failures vs baseline.
- `ruff check .` clean.
- No commit expected (doc-only change already committed with the map edits).
