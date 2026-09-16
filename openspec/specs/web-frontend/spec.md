# web-frontend

## Purpose
The operator UI: a static frontend served by nginx plus a FastAPI backend
bridging the shared workflow runner.

## Requirements

### Requirement: Web backend
frontend/backend/app.py SHALL serve the FastAPI backend on :48011 with a
single shared WorkflowBridge (workflow_bridge.py) that adapts the shared
runner (graph/executor.py WorkflowRunner) and emits stream events over
WebSocket/SSE; aborts SHALL be handled by abort_manager.py.

#### Scenario: Streamed progress
- **WHEN** a workflow runs from the Web UI
- **THEN** phase/progress/skill events stream to the browser as they occur
- **AND** the abort button stops the run via the abort signal

### Requirement: Static frontend
The frontend SHALL be plain static HTML/CSS/JS under frontend/static served
by nginx (:4080), with no build step.

#### Scenario: Static serving
- **WHEN** a browser requests http://localhost:4080/
- **THEN** nginx serves index.html plus the static assets directly from
  frontend/static

### Requirement: Start request accepts ArcKit artefact paths
The Web API start endpoint (`frontend/backend/app.py`, `StartRequest`)
SHALL expose `arckit_artifacts: list[str] = []` (optional). The start
handler SHALL forward it to the bridge (`bridge._arckit_artifacts`),
which SHALL seed `state["arckit_artifacts"]` in `_build_executor_state`
only when non-empty (empty list → key absent, glob discovery default).

#### Scenario: Start with explicit artefacts
- **WHEN** the start request body contains
  `"arckit_artifacts": ["/app/output/arckit/ARC-001-ADMP-v1.0.md"]`
- **THEN** the workflow's DISCOVER state carries that list and the
  loader's explicit-list path applies

#### Scenario: Default start request unchanged
- **WHEN** the start request omits the field
- **THEN** request handling is byte-compatible with the pre-change
  behaviour (no `arckit_artifacts` key in state)
