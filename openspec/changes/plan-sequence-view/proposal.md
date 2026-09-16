# Change: PLAN emits a UML sequence view from use cases

## Why

Neither ArcKit plugin produces sequence/interaction views (verified 2026-09-16
against `arckit-togaf-adm`/`arckit-oaa` templates and generated test trees: TECH
and DATA diagrams are PlantUML ArchiMate + Mermaid only; no
`sequenceDiagram` exists anywhere). Detailed solution design with UML
sequences is therefore a **factory-native (Lane B) output**: PLAN's diagram
generator (`architecture-diagram-generator` skill, 4-view set: component,
sequence, data flow, deployment) is the natural home — seeded by explicit use
cases when available instead of free-form.

The current 4-view set is generated from spec/plan/tasks/doubt context only.
When a use-case list exists (OAA-ADM-lite `vision.yaml` `use_cases`,
ingested as `arckit_nfr_constraints` by `arckit-build-context`, or the
interview), the sequence view should be generated **per use case** so the
result is targeted interaction detail, not a generic flow.

## What changes

- **PLAN** (`graph/nodes/plan.py`): `_generate_all_diagrams` gains a
  use-case-driven sequence step:
  - use cases are extracted from `artifacts.arckit_nfr_constraints`
    (`use_cases` field) when set, else from the interview/spec user-flow
    section; each use case gets one `sequenceDiagram` (Mermaid, rendered via
    the existing PNG pipeline)
  - the generic "sequence" view remains the fallback when no use cases are
    found (behaviour identical to today)
  - diagram context capping per engineering-conventions applies (one LLM call
    per use case, batched via the existing `asyncio.gather` path)
- **BUILD** (`graph/nodes/openhands_build.py`): the build prompt's diagram
  section gains the per-use-case sequence views (they live in
  `artifacts.diagrams` alongside the 4 base views; emitted only when
  present, consistent with the `arckit-build-context` advisory-context rule).
- No change to the 4 base views, to diagram PNG conversion, or to
  ARCH_REVIEW routing (sequence views are part of the reviewed `diagrams`
  payload content, not a new gate).

## Non-goals

- No PlantUML dependency; Mermaid `sequenceDiagram` only (renders in the
  factory's HTML output without new tooling).
- No change to LLM diagram-call budget policy beyond the existing parallel
  fan-out (call count = use cases + 4 base views; capped by
  `bounds.context` diagram caps).
- No ingestion work (use cases come from `arckit_nfr_constraints` — owned
  by `arckit-build-context` — or from the interview, both pre-existing).

## Impact

- New capability spec: `plan-architecture-diagrams` (ADDED requirement).
- `build-delegation` delta: build prompt diagram section includes sequence
  views.
- Code: `graph/nodes/plan.py`, `graph/nodes/openhands_build.py`,
  `tests/test_plan_diagrams.py` (new).
- Wave order: after `arckit-build-context` (needs `arckit_nfr_constraints`).
  The interview/spec fallback works standalone, so the change is
  implementable before the ingestion change lands.
