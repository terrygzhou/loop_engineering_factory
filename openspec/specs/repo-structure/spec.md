# repo-structure

## Purpose
The canonical layout, service ports, and entry points of the repository, so
tooling and agents can locate each subsystem deterministically.

## Requirements

### Requirement: Directory layout
The repository SHALL keep the layout defined below; skills SHALL remain
`SKILL.md` files under skills/ and tests under tests/ (neither may be
excluded from the Docker build context).

| Path | Purpose |
|---|---|
| `graph/` | LangGraph workflow: main.py, state.py, edges.py, runner.py, executor.py, checkpointer.py, ui_bridge.py, review_contract.py, achg_scanner.py, nodes/ |
| `graph/nodes/` | discover, define, plan, review, openhands_build, build_subgraph_legacy, build_helpers, seed_data, verify, ship, reflect. Sibling modules (seam split): `review_payload.py`, `define_prompts.py`, `define_confidence.py`, `verify_review.py`, `verify_tooling.py`, `verify_acceptance.py`, `openhands_client.py`, `openhands_report.py`, `openhands_prompt.py`, `openhands_merge.py`, `plan_diagrams.py`, `plan_confidence.py`, `discover_scan.py`, `discover_prefill.py`, `discover_interview.py`, `build_legacy_nodes.py`, `build_legacy_superapp.py`. Each sibling is imported only by its owning node file or by tests that target the moved helper directly; the node file re-exports all moved names so existing test imports keep resolving |
| `frontend/` | backend/ (FastAPI app.py, workflow_bridge.py, abort_manager.py), nginx/, static/ |
| `config/` | loader.py, guardrails.py, bounds_loader.py, config.yaml, guardrails.yaml, bounds.yaml |
| `tools/` | llm.py, loader.py, distiller.py, arckit_loader.py, context_manager.py, audit_logger.py, prompt_logger.py, stream_writer.py |
| `feedback/` | chroma_client.py, aggregator.py, diff_engine.py |
| `service/` | health.py, evaluator.py, otel_instrumentor.py, px_gate.py |
| `log/` | logging.py (setup_logger + log_event) |
| `skills/` | 35 SKILL.md files |
| `tests/` | 312 tests, flat, conftest at tests/conftest.py |
| `output/` | generated projects land here |

#### Scenario: Generated project output
- **WHEN** a cycle completes SHIP
- **THEN** the generated project lives under output/<project_name>/

#### Scenario: Docker context guards
- **WHEN** the Docker image is built
- **THEN** .dockerignore excludes caches and build artifacts but never
  `*.md` (skills) or `tests/`

### Requirement: Service ports
The system SHALL expose the fixed port table; changing a port or the compose
project name (loop_factory) is a breaking change requiring approval.

| Port | Service |
|---|---|
| 4080 | nginx → static frontend |
| 48011 | FastAPI backend (uvicorn) |
| 48081 | health / metrics (in-container :8081) |
| 43005 | OpenHands Gateway (internal :8000) |
| 46006 | Phoenix |
| 8000 | ChromaDB (internal only) |

#### Scenario: Health probe
- **WHEN** an operator runs `curl http://localhost:48081/health`
- **THEN** the health server responds, and /metrics returns the five
  Prometheus series

### Requirement: Entry points
The CLI SHALL be `main.py` (auto-approve via --auto-approve, context scan via
--context, re-run via --improve); the Web entry SHALL be the FastAPI backend
on :48011; both SHALL share the runner in graph/executor.py.

#### Scenario: CLI auto-approve
- **WHEN** `python main.py --project x --spec "…" --auto-approve` runs
- **THEN** the full pipeline runs headless to REFLECT without HIL pauses
