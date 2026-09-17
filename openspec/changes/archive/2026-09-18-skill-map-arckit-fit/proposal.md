# Proposal: skill-map-arckit-fit

## Why

Three defects in how the factory reasons about its own skill surface and
ArcKit artifact consumption:

1. **`PHASE_SKILL_MAP.md` has drifted from the code.** DISCOVER's actual
   skills (`fabric-prompts`, `coding-principles`) are absent from the map;
   REFLECT lists skills that are never called (`using-agent-skills`,
   `deprecation-and-migration` — the node only calls `git-workflow`); SHIP's
   row names `git-workflow-and-versioning` while the code calls `git-workflow`.
   The map is the document an engineer opens to ask "which skill governs this
   phase?" — it currently answers wrong.

2. **ArcKit's Tier-2 `arckit_product_backlog` never reaches PLAN.** It is
   written to state by DISCOVER and surfaced as an advisory block in the BUILD
   prompt, but PLAN — the phase that produces the task breakdown — builds its
   context from spec + interview + rejection feedback only. The backlog is
   the most TDD-actionable ArcKit artifact (ordered, sized work items) and the
   task breakdown is exactly where it should constrain and inform planning.
   Loop-factory's delivery model (Superpowers TDD: plan → build → verify)
   makes PLAN the natural landing point, not BUILD.
   The advisory block that carries it is ad-hoc per-node logic; it should be
   consolidated into a shared helper so future consumers don't each re-implement
   the same pattern.

3. **Dead `spec_text` parameter in `build_executor_state`.** Review finding I-1:
   P0-A1 removed `spec_text` from `WorkflowState` (nodes read
   `artifacts["spec_refined"]` instead), but the parameter still exists on
   `build_executor_state` / `run_interactive` and is passed through but never
   read. Removing it is a dead-parameter cleanup, not a behavior change.

## What

- **Task 1** — Fix `PHASE_SKILL_MAP.md`: correct DISCOVER, REFLECT, and SHIP
  rows; remove unwired `code-simplification` / `context-engineering` /
  `debugging-and-error-recovery` from "active/ready" framing; mark
  `writing-plans` and `git-workflow-and-versioning` as superseded. No code.
- **Task 2** — Consolidate the ArcKit advisory-block logic into a shared
  `tools/arckit_context.py::arckit_advisory_block(artifacts, max_chars=4000)
  -> str` helper; refactor `define.py::_arckit_advisory_context` to call it;
  feed `arckit_product_backlog` into PLAN's `context_parts` via the helper
  (byte-identical prompt when no ArcKit advisory keys are set).
- **Task 3** — Remove the dead `spec_text` parameter from `build_executor_state`
  and `run_interactive` in `graph/executor.py` (review finding I-1). No
  behavior change.
- **Task 4** — Close-out gate.

## Non-goals

- No new ArcKit ingestion types (BPCM/GAPA stay out of state — they don't
  improve the TDD loop).
- No new skills authored in this change (the `arckit-ingestion` skill idea
  is parked; task 2 uses the consolidated advisory-block helper).
- No routing / Decision-2 / loop-budget changes (SPEC §7).
- No change to the OpenHands BUILD prompt's existing ArcKit advisory sections
  (they stay as-is; this change only adds PLAN consumption via the shared
  helper).
- SEED_DATA already consumes `arckit_data_model` deterministically (active
  seed node, not the legacy subgraph) — no change needed there.

## Impact

| Area | Change |
|------|--------|
| `skills/PHASE_SKILL_MAP.md` | Doc-only correction (Task 1) |
| `tools/arckit_context.py` | New shared helper (Task 2) |
| `graph/nodes/define.py` | Refactored to call shared helper (Task 2) |
| `graph/nodes/plan.py` | +1 advisory block in context_parts via shared helper (Task 2) |
| `graph/executor.py` | Dead `spec_text` param removed (Task 3) |
| `tests/` | 2 new test files (Task 2, Task 3) |
| Risk | Low — Task 2 follows the byte-identical-when-absent advisory pattern already used for `arckit_nfr_constraints` in DEFINE/PLAN; Task 3 is a no-op cleanup. No schema change, no new state key. |
