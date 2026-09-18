# Final review — `2026-09-18-map-drift-residual` (SDD, 2026-09-18)

Scope: OpenSpec change `openspec/changes/2026-09-18-map-drift-residual`
(3 doc-only tasks: ✅/📦 status-label corrections in
`skills/PHASE_SKILL_MAP.md`, stale Wiring-Priority cleanup, close-out gate).
Executed via SDD workflow on main (no worktree) per user direction. Doc-only —
no `.py` files touched.

Commits (all on main, post change-add `9d5aef4`):
- `29b21a6` — Task 1: correct ✅/📦 status labels
- `b4f819f` — Task 2: fix stale Wiring Priority
- `0e5c452` — Critical fix from final review (performance-optimization mislabel)
- Task 3 (gate): verification-only, no commit (zero tracked changes)

Workflow: 8 agents (3 implementers, 3 task reviewers, 1 final whole-branch
reviewer, 1 gate runner). All per-task reviews returned `pass` with zero fix
rounds; the final whole-branch review found 1 Critical + 1 Important that the
per-task passes missed.

## Findings

0 Critical remaining (1 found & fixed). 0 Important remaining (1 found &
fixed). 3 Minor (out of scope, noted for future passes).

### Critical (found in final review, fixed in `0e5c452`)
- **`performance-optimization` ✅-labeled in SHIP with zero live calls.**
  `grep -rn 'performance-optimization' graph/ main.py tools/ --include='*.py'`
  returns nothing; `ship.py` calls only `observability-and-instrumentation`
  (L43), `shipping-and-launch` (L72), `production-deployment` (L101),
  `git-workflow` (L158). The ✅ row dates from the `c85ee6b` era and was
  **inherited from `424c180`** (the skill-map-arckit-fit drift fix corrected
  DISCOVER/REFLECT/SHIP rows but left this one). Violated the spec rule
  "a skill with no `skills.get` call MUST be marked 📦". Fixed: flipped to
  📦, recomputed Coverage Summary, added to Wiring Priority (LOW → SHIP).

### Important (resolved by the same commit)
- **Coverage Summary was internally inconsistent.** "Active in graph: 17" and
  "Ready to wire: 3" did not reconcile with either the label set (17 ✅ / 6 📦
  before the fix) or the live-code truth. Root cause: Task 1's prescribed
  arithmetic ("15 → 17, 5 → 3") was computed from an already-wrong baseline
  (the inherited `performance-optimization` ✅). After the label flip,
  reconciled to a single rule: **Active = 16** (✅-labeled skills with a live
  call), **Ready to wire = 7** (unique 📦-labeled skills).

### Minor (out of scope, not blocking)
- **M-1: `ai-workflow-data-seeding`** (called live at
  `build_subgraph_legacy.py:633`, legacy-fallback-only) has no row in the
  SEED_DATA section — a pre-existing gap of the same drift class. Follow-up
  candidate.
- **M-2: `pre-commit-review` → VERIFY (HIGH) retained in Wiring Priority**
  even though it is already wired (`verify.py:221`,
  `build_subgraph_legacy.py:1226`). It is a 🔧 local-custom skill, not a
  downloaded agent-skill, so it does not violate the "already-wired
  agent-skills must not appear" rule — but it is still an already-wired skill
  listed as a wiring candidate. Recommend dropping in a follow-up.
- **M-3: Stale accounting.** "Total agent-skills: 24" / "Downloaded 24/24" /
  "Local custom: 7" are inherited from before this change and do not match the
  current `skills/` directory (34 SKILL.md dirs; `code-simplification` is
  locally authored). Root cause of the "Ready to wire: 3" miscount. Follow-up
  candidate (recompute from a scripted label + `skills.get` scan).

## Gate

`.venv/bin/python3 -m pytest tests/ -q` (7 hang files `--ignore`, 5
baseline out-of-scope failures `--deselect`):
**448 passed / 5 deselected / 0 new failures.**

`ruff check .` → `All checks passed!` (clean).

Doc-only change — no code, schema, state, or routing impact; the gate
confirms no regressions.

## Spec conformance

**`specs/skill-registry/spec.md`:**

- **"Status labels match live graph calls" — PASS** (after `0e5c452`):
  - `interview-me` ✅ — called at `discover.py:224` ✓
  - `planning-and-task-breakdown` ✅ — called at `plan.py:107` ✓
  - `source-driven-development` ✅ — called at `define.py:283` ✓
  - `code-simplification` 📦 — 0 `skills.get` callers ✓
  - `performance-optimization` 📦 — 0 `skills.get` callers ✓ (was ✅, fixed)
  - `context-engineering` / `debugging-and-error-recovery` 📦 — 0 callers ✓
  - All 16 ✅-labeled skills confirmed to have live calls; all 7 📦-labeled
    skills confirmed to have none.
- **"Coverage counts match the labels" — PASS** (after `0e5c452`):
  Active-in-graph = 16 = number of ✅-labeled skills with a live
  `skills.get` call; Ready-to-wire = 7 = number of unique 📦-labeled skills.
- **"Wiring Priority lists only unwired skills" — PASS:**
  The two already-wired agent-skill entries (`planning-and-task-breakdown`,
  `source-driven-development`) are removed. Remaining named candidates
  (`documentation-and-adrs`, `context-engineering`, `ci-cd-and-automation`,
  `browser-testing-with-devtools`, `code-simplification`,
  `performance-optimization`) all verified to have zero `skills.get` callers.
  The `pre-commit-review` retention is a documented, spec-permitted exception
  (🔧 local-custom, not an agent-skill) — see M-2.

## Lessons

- Per-task reviewers each verified their diff against the task spec and
  passed it — but the task's *prescribed* counts were computed from a doc
  that was already wrong (inherited from `424c180`). The close-out gate
  verified "the doc reflects every Task-1/Task-2 spec requirement" but did
  not re-derive the Coverage counts from the label set — a mechanical check
  that would have caught both the Critical and the Important. The final
  whole-branch review, which re-grepped every ✅ label against the live code,
  caught it. **Lesson: for doc/status changes, the final review MUST re-derive
  every count from the source of truth (the code), not trust the task's
  prescribed arithmetic.**

## Verdict

**Pass (after `0e5c452`).** All spec-delta scenarios met. 0 Critical, 0
Important, 3 Minor (out of scope, pre-existing or accepted). Safe to archive.
