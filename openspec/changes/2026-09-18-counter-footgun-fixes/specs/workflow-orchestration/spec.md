# workflow-orchestration (delta)

## MODIFIED Requirements

### Requirement: Phase routing ownership
Route counters are owned by NODES, never by edges. A node that needs to
increment a phase's retry counter SHALL build a fresh `loop_counts` dict
(from the incoming `state["artifacts"]["loop_counts"]`, default empty),
update it, and return it inside the node's partial-update `artifacts`
delta so LangGraph's `_dict_merge` reducer persists it. Edges read the
counter only (`graph/edges.py:_get_loop_count`).

The in-place-mutation helper `_maybe_increment_loop` is REMOVED. Its
replacement is the pure helper `graph/edges.py:increment_loop(artifacts,
phase) -> (dict, bool)` which returns a NEW artifacts dict plus a
`max_exceeded` flag (max = 2). No function in `graph/` or `tools/` SHALL
mutate `state["artifacts"]` in place.

#### Scenario: Low-confidence DEFINE persists its counter
- **WHEN** `define_node` completes with `spec_confidence` below the
  guardrail threshold and the incoming `artifacts.loop_counts["DEFINE"]`
  is absent or 0
- **THEN** the node's returned update contains
  `artifacts.loop_counts["DEFINE"] == 1`
- **AND** the next low-confidence DEFINE run (counter now 1) returns
  `artifacts.loop_counts["DEFINE"] == 2`
- **AND** `route_phase` then forwards DEFINE → PLAN (livelock guard
  fires; the unbounded DEFINE→DEFINE loop is gone)

#### Scenario: Edges never mutate state
- **WHEN** `route_phase` is called for any phase
- **THEN** `state["artifacts"]` is byte-identical after the call
  (edges are read-only; only node returns change state)
