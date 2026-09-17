# Proposal: skill-map-arckit-fit

## Why

Two separate defects in how the factory reasons about its own skill surface:

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

3. **`ai-workflow-data-seeding` is blind to `arckit_data_model`.** SEED_DATA
   (legacy subgraph) builds its seed prompt from `extract_data_models` +
   `extract_api_specs` only. When DISCOVER has ingested an ArcKit DATA
   artefact, the seeded entities/classification scheme is ignored — the LLM
   invents its own schema instead of seeding from the project's declared one.

## What

- **Task 1** — Fix `PHASE_SKILL_MAP.md`: correct DISCOVER, REFLECT, and SHIP
  rows; remove unwired `code-simplification` / `context-engineering` /
  `debugging-and-error-recovery` from "active/ready" framing; mark
  `writing-plans` and `git-workflow-and-versioning` as superseded. No code.
- **Task 2** — Feed `arckit_product_backlog` into PLAN's task-breakdown
  prompt (advisory block, capped by `bounds.context.arckit_advisory_max_chars`,
  byte-identical prompt when the key is absent — the established W3 advisory
  pattern).
- **Task 3** — Extend the SEED_DATA seed prompt to include
  `arckit_data_model` when set (same advisory pattern: block present only
  when the key is set and non-empty).

## Non-goals

- No new ArcKit ingestion types (BPCM/GAPA stay out of state — they don't
  improve the TDD loop).
- No new skills authored in this change (the `arckit-ingestion` skill idea
  is parked; tasks 2–3 use the existing advisory-block pattern instead).
- No routing / Decision-2 / loop-budget changes (SPEC §7).
- No change to the OpenHands BUILD prompt's existing ArcKit advisory sections
  (they stay as-is; this change only adds PLAN + SEED_DATA coverage).

## Impact

| Area | Change |
|------|--------|
| `skills/PHASE_SKILL_MAP.md` | Doc-only correction (Task 1) |
| `graph/nodes/plan.py` | +1 advisory block in context_parts (Task 2) |
| `graph/nodes/build_subgraph_legacy.py` | +1 advisory block in seed context (Task 3) |
| `tests/` | 2 new test files (Task 2, Task 3) |
| Risk | Low — both code tasks follow the byte-identical-when-absent advisory pattern already used for `arckit_nfr_constraints` in DEFINE/PLAN. No schema change, no new state key. |
