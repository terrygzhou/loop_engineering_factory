# repo-structure (delta)

## MODIFIED Requirements

### Requirement: Directory layout
The repository SHALL keep the layout defined below; skills SHALL remain
`SKILL.md` files under skills/ and tests under tests/ (neither may be
excluded from the Docker build context).

| Path | Purpose |
|---|---|
| `graph/` | LangGraph workflow: main.py, state.py, edges.py, runner.py, executor.py, checkpointer.py, ui_bridge.py, review_contract.py, achg_scanner.py, nodes/ |
| `graph/nodes/` | Node entry points (discover, define, plan, review, openhands_build, seed_data, verify, ship, reflect, build_subgraph_legacy, build_helpers) plus their split sibling modules: discover_scan, discover_prefill, discover_interview, plan_diagrams, plan_confidence, verify_review, verify_tooling, verify_acceptance, openhands_client, openhands_report, openhands_prompt, openhands_merge, define_prompts, define_confidence, review_payload, reflect_skill_review, reflect_diffs, build_legacy_nodes, build_legacy_superapp |
| `frontend/` | backend/ (FastAPI app.py, workflow_bridge.py, abort_manager.py), nginx/, static/ |
| `config/` | loader.py, guardrails.py, bounds_loader.py, config.yaml, guardrails.yaml, bounds.yaml |
| `tools/` | llm.py, loader.py, distiller.py, arckit_loader.py, context_manager.py, audit_logger.py, prompt_logger.py, stream_writer.py |
| `feedback/` | chroma_client.py, aggregator.py, diff_engine.py |
| `service/` | health.py, evaluator.py, otel_instrumentor.py, px_gate.py |
| `log/` | logging.py (setup_logger + log_event) |
| `skills/` | 35 SKILL.md files |
| `tests/` | 312 tests, flat, conftest at tests/conftest.py |
| `output/` | generated projects land here |

A sibling module in `graph/nodes/` SHALL be named `<node>_<concern>.py`
or `build_legacy_<concern>.py` and SHALL be imported only by its owning
node file or by tests targeting the moved helper directly. Node entry
points (`*_node`, `openhands_build_proxy_factory`, `build_subgraph_node`,
`get_compiled_subgraph`) SHALL remain importable from the original node
modules.

#### Scenario: Sibling module is not imported by another phase
- **WHEN** `graph/nodes/plan.py` (or any other node module) is diffed after
  a split
- **THEN** it imports only its own siblings (`plan_diagrams`,
  `plan_confidence`) and never another phase's siblings such as
  `verify_review` or `openhands_report`.

#### Scenario: Sibling layout listed
- **WHEN** an operator inspects `graph/nodes/`
- **THEN** each split node file is accompanied by its sibling modules and
  the public entry points are still exported from the original module.
