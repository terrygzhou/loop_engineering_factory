# web-frontend (delta)

## MODIFIED Requirements

### Requirement: Per-workflow abort signal
`frontend/backend/abort_manager.AbortManager` SHALL key its cached
`asyncio.Event` on the owning event loop AND a workflow id:
`AbortManager.get(workflow_id=None)` returns (and caches) a manager
dedicated to that workflow. Two concurrent workflows SHALL NOT share an
abort flag. An event created on loop A SHALL NOT be observed by code
running on loop B: the event is created lazily on first use in the
running loop (per-loop recreation), so cross-loop `is_aborted` /
`wait` see a fresh state rather than a stale one.

- The Web bridge (`frontend/backend/workflow_bridge.py`) SHALL pass its
  workflow id to `AbortManager.get(...)`.
- The module-level no-arg `get()` keeps working for single-workflow
  callers (default workflow id).

#### Scenario: Concurrent workflows are isolated
- **WHEN** workflow A signals abort while workflow B is running
- **THEN** B's manager reports not-aborted and A's reports aborted

#### Scenario: Cross-loop stale state is impossible
- **WHEN** a manager created on loop A is `wait()`ed on loop B
- **THEN** the wait observes a fresh (not pre-set) abort state
