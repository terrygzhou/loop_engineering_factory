# Change: WorkflowState schema contract — kill drift structurally

## Why

`findings.md` §A (state review) shows the state schema has drifted:

- **A1 — ~half the schema is dead.** `WorkflowState` declares 41
  top-level keys; an AST audit of the active node set
  (discover/define/plan/review/openhands_build/seed_data/verify/ship/reflect
  + runner) shows only ~15 keys are ever returned by a node. Dead
  candidates: `tasks`, `tasks_text`, `backlog`, `solution_md`, `plan`,
  `status`, `retry_count`, `spec_text`, `spec_refined`,
  `project_context`, `interview_notes`, `diagrams`, `diagram_pngs`,
  `feedback_context`, `human_approval_required` (values actually live
  under `artifacts.*`). The S-001/S-003 dedup was started and
  abandoned.
- **A4 — misplaced counter logic.** (Overlaps with
  `2026-09-18-counter-footgun-fixes` task 1.3: the pure
  `increment_loop` helper and `_maybe_increment_loop` deletion land in
  that change; this change consumes them and owns the contract test
  that makes them stick.)
- **A5 — gate signal parsed in the router.** The VERIFY branch in
  `graph/edges.py` does `json.loads(state...["test_results"])` inline;
  the parse belongs in one helper computed once, next to
  `tools/acceptance.py`.

## What changes

- **A1:** `graph/state.py` drops the dead top-level keys (the A1 list
  above) and keeps the 8 input-only keys (`skip_discover`,
  `improve_mode`, `force_hil`, `auto_approve_override`,
  `arckit_artifacts`, `trace_id`, `cycle_id`, `config_version`) plus the
  15 node-returned keys. Runner/bridge initial-state seeding is updated
  to the same trimmed schema (no initial value for a key the schema
  doesn't declare).
- **Contract test (the structural guard):** `tests/test_state_contract.py`
  AST-scans every active node in `graph/nodes/*` + `graph/runner.py`
  for top-level state keys they return, and asserts every `WorkflowState`
  key is either (a) returned by some active node, or (b) on the
  explicit `INPUT_ONLY_KEYS` allowlist in `graph/state.py`. Any new
  top-level key not on either list fails the test. This kills drift
  by construction — a future node that returns a new top-level key must
  either add it to the schema (PR-visible) or the test fails.
- **A5:** extract the `test_results` JSON parse into
  `tools/acceptance.py:count_pytest_fail(artifacts) -> int`
  (returns 0 on absent/invalid JSON, matching the router's current
  try/except behavior); the `route_phase` VERIFY branch calls it.
- **A4 (follow-on, depends on counter-footgun-fixes task 1.3):** extend
  `tests/test_w2_wayforward.py` with the `increment_loop` pure-helper
  tests (increment / halt-at-2 / reset-on-success) now that
  `_maybe_increment_loop` is gone.

## Non-goals

- **P1 typed artifacts + blob offload** (findings §A2/A3) is NOT part of
  this change — it's a separate, larger change (typed `Artifacts`
  pydantic model, disk offload, checkpoint size budget) and is not
  converted here. `artifacts` stays an untyped
  `Annotated[Dict[str, Any], _dict_merge]` until that work.
- No phase/routing change: `route_phase` semantics, `_forward_paths`,
  the VERIFY gate (Decision 2), and the loop budget (max 2) are
  untouched — only where the gate signal is *parsed* moves.
- No change to the OpenHands API surface, build_report.json schema,
  ChromaDB collection names, or compose ports.

## Impact

- Code: `graph/state.py` (schema trim + `INPUT_ONLY_KEYS`),
  `graph/runner.py` / `frontend/backend/workflow_bridge.py` (initial
  state seeding), `tools/acceptance.py` (new `count_pytest_fail`),
  `graph/edges.py` (VERIFY branch calls it; `_maybe_increment_loop`
  deleted + `increment_loop` added by the companion change),
  `tests/test_state_contract.py` (new), `tests/test_w2_wayforward.py`
  (extended), `tests/test_edges.py` (state invariance assertion).
- Spec deltas: `workflow-orchestration` (state schema is the contract;
  input-only keys are explicit; gate signal parsed once in a helper),
  `engineering-conventions` (contract test pattern: AST-scan active
  nodes, every schema key must be node-returned or input-only).
