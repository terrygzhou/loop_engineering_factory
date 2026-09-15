# workflow-orchestration

## Purpose
Defines the 9-phase greenfield pipeline and how control flows between phases,
shared by both the CLI and Web entry points.

## Requirements

### Requirement: Phase pipeline
The system SHALL orchestrate project generation through the phase chain
DISCOVER → DEFINE → PLAN → ARCH_REVIEW → BUILD → SEED_DATA → VERIFY → SHIP →
REFLECT, compiled in graph/main.py, with an ERROR terminal sink.

#### Scenario: Happy cycle
- **WHEN** `python main.py --project x --spec "…" --auto-approve` completes
- **THEN** the final phase is REFLECT with error=None
- **AND** output/x/ contains build_report.json, build/solution.md, and build/verify_report.md

#### Scenario: Fatal error halts
- **WHEN** a phase sets error and next_phase=None
- **THEN** route_phase routes to ERROR and the run halts without shipping

### Requirement: Phase routing ownership
graph/edges.py:route_phase SHALL be the single routing authority. Edges SHALL
read loop counters from artifacts.loop_counts only; nodes SHALL increment
counters before returning (replacing the whole dict, per LangGraph persistence).

#### Scenario: Livelock guard
- **WHEN** a phase's loop_count reaches max_loops (2)
- **THEN** route_phase returns the generic _forward_paths[phase]
- **AND** for VERIFY that forward path is ERROR, never SHIP

### Requirement: Shared runner
The CLI (main.py) and Web (frontend/backend/app.py → workflow_bridge.py) SHALL
share one async runner (graph/runner.py run_workflow + graph/executor.py
WorkflowRunner) that owns stream → interrupt → resume, with adapters supplying
input handlers and event sinks.

#### Scenario: Web/CLI resume parity
- **WHEN** a run pauses at an HIL gate in the Web UI
- **THEN** resuming via the bridge produces the same state transitions as the
  CLI resume path
