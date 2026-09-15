# checkpointer

## Purpose
Persistent SQLite checkpointing so a workflow run can be resumed from the last
completed step after a crash or kill.

## Requirements

### Requirement: Checkpoint resume
The system SHALL persist each workflow step to SQLite via the official
langgraph AsyncSqliteSaver (wrapped by graph/checkpointer.py
LazyAsyncSqliteSaver, EYW-235) and resume from the last checkpoint when the
same thread_id is re-invoked.

#### Scenario: Resume after kill
- **WHEN** a run is killed mid-phase and re-invoked with the same thread_id
- **THEN** the workflow resumes from the last persisted checkpoint, not from
  the start

### Requirement: State serializability
WorkflowState SHALL be fully serializable so no per-state stripping is
required on save (EYW-233).

#### Scenario: Full state round-trip
- **WHEN** a WorkflowState is saved and reloaded
- **THEN** all fields survive the round-trip intact, including artifacts and
  loop counters

### Requirement: Resume is observable
Resuming a killed run SHALL resume at the last completed phase — earlier
phases SHALL NOT re-execute.

#### Scenario: No re-execution on resume
- **WHEN** a run killed after PLAN is resumed with the same thread_id
- **THEN** execution continues from ARCH_REVIEW and PLAN node effects are not
  repeated

### Requirement: One checkpointer per event loop
Each workflow run SHALL materialize its own LazyAsyncSqliteSaver inside the
event loop it runs in (the official AsyncSqliteSaver captures the running
loop at construction).

#### Scenario: Concurrent runs
- **WHEN** multiple concurrent runs share the same checkpoints.db file
- **THEN** each run uses its own saver instance and cross-instance
  persistence still works (graph-level HIL interrupt → resume e2e)
