# SuperWeb UAT Integration — Solution & Implementation Plan

## Problem Statement

The current UAT node in `graph/nodes/build_subgraph.py` is **LLM-prompt-based**: it sends a descriptive prompt to the LLM asking it to "run UAT tests" and parses PASS/FAIL from text output. No actual browser automation occurs.

SuperWeb Testing (`~/workspace/projects/superweb-testing`) provides a real 4-phase pipeline:
```
Source Analysis → Data Generation → Browser Testing (Playwright) → Log Correlation
```
with two execution modes:
- **Scripted** — deterministic Playwright pipeline (default)
- **Agent** — OpenHands AI agent delegation (3-conversation workflow)

## Goal

Replace the LLM-prompt UAT node with SuperWeb execution that:
1. Supports **both scripted and agent modes**
2. Scans the built project source for forms/routes
3. Generates realistic test data via LLM
4. Executes browser automation (Playwright or OpenHands agent)
5. Returns structured JSON → mapped to `BuildSubState`

## Solution Overview

### Architecture

```
BuildSubState (parent)
    │
    ▼
UAT Node
    │  1. Determine mode: scripted vs agent
    │  2. Scripted: superweb run --mode scripted
    │  3. Agent:   superweb run --mode agent (--openhands-start)
    │  4. Parse JSON output (test_results.json or agent_report.json)
    │  5. Map → uat_pass_rate, uat_result, uat_output
    │  6. Cleanup (stop OpenHands if agent mode)
    │  7. Return updated BuildSubState
    ▼
BuildSubState → build_output_mapping() → parent WorkflowState
```

### Mode Selection Logic

Agent mode is the **default**. Scripted mode is a fallback when OpenHands is unavailable.

```python
if state["superweb_mode"] == "scripted":
    # Fallback: deterministic Playwright pipeline
    mode = "scripted"
    timeout = 600     # 10 min
else:
    mode = "agent"   # default
    timeout = 3600   # 60 min
```

**Agent mode** is preferred because:
- OpenHands agent autonomously explores the application (no pre-defined schemas needed)
- Better coverage: agent discovers forms, navigation, and edge cases dynamically
- Adapts to project structure without source code analysis (works for any web app)
- Produces a rich `agent_report.json` with reasoning and artifacts

**Scripted mode** is the fallback when:
- OpenHands container is not available or unreachable
- Agent mode times out or fails
- Explicitly configured as `"scripted"` in bounds

### Integration Points

| Location | Change |
|-----------|--------|
| `graph/nodes/build_subgraph.py` | Replace `uat_node()` body with SuperWeb pipeline execution |
| `Dockerfile` | Install Playwright browsers + superweb-testing |
| `compose.yaml` | Add OpenHands service + Docker socket mount (for agent mode) |
| `config/bounds.yaml` | Add `superweb.*` bounds (timeout, variations, mode) |
| `config/config.yaml` | Add `superweb` service config section |
| `graph/state.py` | Add `superweb_mode` to BuildSubState |

### Key Design Decisions

**Subprocess call**: Run SuperWeb as a subprocess (`superweb run ...`) rather than importing its modules. Reason: SuperWeb runs Playwright/OpenHands in their own event loops; subprocess provides clean isolation from LangGraph context.

**Agent mode**: Uses OpenHands Agent Server container managed via `compose.yaml`. The agent does 3 sequential conversations (analyze → test → report). More powerful but slower (~30 min vs ~10 min for scripted).

**Fallback chain**: If SuperWeb fails (Playwright not installed, container unreachable, timeout), fall back to the existing LLM-prompt UAT as last resort. Maintains backward compatibility.

**Conditional agent mode**: Agent mode is enabled when:
- `superweb.agent_mode: true` in config
- OpenHands container is available and healthy
- Project is web-based (has forms/routes detected)

### Implementation Tasks

#### Phase 1: Infrastructure (Priority: High)

- [ ] **Task 1.1**: Add SuperWeb as subprocess dependency
  - `Dockerfile`: Install superweb-testing + Playwright browsers
  - Build step: `pip install /opt/superweb`
  - Playwright: `playwright install chromium` (already in Dockerfile)

- [ ] **Task 1.2**: Add OpenHands service to `docker-compose.yml`
  - Service: `openhands` on port 3005
  - Mounts: Docker socket, workspace directory, LLM env vars
  - Only started when agent mode is enabled

- [ ] **Task 1.3**: Add config bounds
  - `config/bounds.yaml`:
    ```yaml
    superweb:
      timeout_seconds: 600
      variations: 3
      mode: scripted          # scripted | agent
      agent_timeout: 3600     # agent mode timeout
      fallback_to_llm: true
    ```
  - `config/config.yaml`: `services.superweb` section (base URL, model)

#### Phase 2: UAT Node Rewrite (Priority: High)

- [ ] **Task 2.1**: Replace `uat_node()` in `build_subgraph.py`
  - Detect mode from config bounds
  - Build command with mode-specific args
  - Parse JSON output based on mode:
    - Scripted: `test_results.json` → pass rate from status array
    - Agent: `agent_report.json` → verdict field

- [ ] **Task 2.2**: Agent mode workflow
  - Start OpenHands container (if not running)
  - Run: `superweb run --mode agent --agent-timeout 3600 ...`
  - Parse `agent_report.json` for verdict
  - Stop OpenHands container after completion
  - Handle container errors gracefully

- [ ] **Task 2.3**: Fallback to LLM-prompt UAT
  - If subprocess fails or timeout → existing `invoke_skill()` approach
  - Log fallback event: `[UAT] SuperWeb failed, falling back to LLM prompt`

- [ ] **Task 2.4**: Update `BuildSubState` TypedDict
  - Add fields for SuperWeb mode and output parsing
  - Add `superweb_mode` field to distinguish scripted vs agent

#### Phase 3: Docker Integration (Priority: Medium)

- [ ] **Task 3.1**: Update `docker-compose.yml`
  - Add `openhands` service configuration
  - Mount Docker socket for agent sandbox spawning
  - Network: host.docker.internal for target app access

- [ ] **Task 3.2**: Update `Dockerfile`
  - Copy superweb-testing source
  - Install dependencies
  - Install Playwright browsers

#### Phase 4: Testing & Validation (Priority: Medium)

- [ ] **Task 4.1**: Unit tests for UAT node
  - Mock subprocess return values for both modes
  - Verify pass rate calculation from JSON

- [ ] **Task 4.2**: Integration test
  - Run full BUILD cycle with SuperWeb UAT
  - Verify: scripted mode → agent mode → fallback
  - Confirm pass/fail routing works correctly

### Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Playwright browsers increase Docker image size (~300MB) | Build time, storage | Already installed; no additional cost |
| OpenHands container requires Docker-in-Docker | Complexity | Only for agent mode; scripted mode works without it |
| Agent mode timeout (30-60 min) | Slow pipeline | Configurable; scripted mode is 10 min default |
| Target URL resolution from inside Docker | All tests fail | Use `host.docker.internal` or Docker network hostname |
| SuperWeb output format changes | Parse failures | Fallback chain to LLM prompt preserves functionality |
| Agent mode on non-web projects | Wasted time | Source analysis detects forms/routes; skip if none found |

### Success Criteria

- [ ] UAT node executes real browser tests against the built application (scripted mode)
- [ ] Agent mode: OpenHands agent explores and tests the application autonomously
- [ ] Pass rate calculated from actual test results, not LLM text
- [ ] Fallback to LLM-prompt works when SuperWeb fails
- [ ] No regression in BUILD subgraph flow (SEED → UAT → END)
- [ ] Both modes configurable via `config/bounds.yaml`