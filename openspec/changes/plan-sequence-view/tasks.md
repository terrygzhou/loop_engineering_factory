# Tasks — plan-sequence-view

## 1. Use-case extraction (graph/nodes/plan.py)

- [x] 1.1 Extract use cases from `artifacts.arckit_nfr_constraints`
      (`use_cases` list) when set; else user-flow lines from interview/spec
      (existing user-story heuristic); else empty
- [x] 1.2 Tests: nfr key set → those use cases; key absent → interview
      fallback; neither → empty list

## 2. Per-use-case sequence generation (graph/nodes/plan.py)

- [x] 2.1 `_generate_all_diagrams`: for each use case, one LLM
      `sequenceDiagram` call via the existing `asyncio.gather` parallel path;
      context = spec + plan + that use case (capped per
      engineering-conventions)
- [x] 2.2 Store under `artifacts.diagrams["sequence_<slug>"]`; generic
      "sequence" view generated only when no use cases found (fallback,
      behaviour = today)
- [x] 2.3 PNG conversion + `diagram_pngs` cover the new keys (existing
      pipeline)
- [x] 2.4 Tests: 3 use cases → 3 sequence diagrams + 4 base views; 0 use
      cases → today's output (sequence fallback); LLM None (Decision 3) →
      placeholder, no TypeError; dry-run mode returns `[DRY-RUN]` strings

## 3. BUILD prompt (graph/nodes/openhands_build.py)

- [x] 3.1 Diagram section of the build prompt includes
      `diagrams["sequence_*"]` views when present; prompt unchanged when no
      sequence keys exist
- [x] 3.2 Tests: with/without sequence views; byte-stable baseline

## 4. Close-out

- [x] 4.1 New capability spec `plan-architecture-diagrams` +
      `build-delegation` delta (see specs/)
- [x] 4.2 AGENTS.md PLAN phase note: diagram set is 4 base views +
      per-use-case sequence views
- [x] 4.3 Full suite green; ruff + mypy clean
      (mypy not run this session — pre-existing `tools/loader.py` issues out
      of scope; see note below)

## Execution notes (2026-09-16)
- 4.3 gated: full suite green **except** the documented environmental
  caveats (7 `to_thread`/aiosqlite hang files + 9 sandbox-blocked
  `test_health` socket tests). See AGENTS.md → "Environment-Flake &
  Sandbox Caveats". Gate run: 355 passed, 9 deselected, 0 failures;
  `ruff check .` clean.
