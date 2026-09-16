# web-frontend (delta)

## ADDED Requirements

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
