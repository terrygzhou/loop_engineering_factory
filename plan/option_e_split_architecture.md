# Option E — Split Architecture Implementation Plan

## Overview

Split the monolithic `loop_factory-loop` container into two specialized services:
- **Orchestrator** (1G limit): Workflow engine, state management, API server
- **Builder** (6G limit): Code generation, Docker builds, Playwright UAT

## Architecture

```
orchestrator (1G)                      builder-worker (6G)
├── LangGraph engine                   ├── LLM generation (heavy)
├── REST API :8011                     ├── Playwright/Chromium
├── Phase routing                      ├── Docker build/test
├── State/checkpoints                  ├── Skill execution
└── Health monitoring                  └── Test execution
        │                                      ▲
        │   POST /api/build {spec, tasks}       │
        │  ──────────────────────────────────▶   │
        │   GET /api/build/{id}/status           │
        │  ◀─────────────────────────────────    │
```

## Communication Contract

### BuildRequest — Orchestrator → Builder

```python
class BuildRequest(BaseModel):
    build_id: str
    project_name: str
    project_path: str          # /app/output/<project_name>
    spec_text: str
    tasks_text: str
    backlog: list[dict]
    skills: dict               # skill registry subset
```

### BuildStatus — Polling Response

```python
class BuildStatus(BaseModel):
    build_id: str
    status: str                # "running" | "pass" | "fail" | "partial"
    sub_phase: str            # current sub-phase
    progress: list[dict]     # backlog items with status
    artifacts: dict         # partial results
    errors: list[str]
    completed_at: str | None
```

### API Endpoints (Builder)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/build` | Submit build → 202 Accepted |
| GET | `/api/build/{id}` | Poll status |
| GET | `/api/build/{id}/logs` | Streaming build logs |
| POST | `/api/build/{id}/cancel` | Cancel in-progress build |
| GET | `/api/health` | Health check |

## Implementation Phases

### Phase 1: Builder Service (Critical)

**New files:**
```
loop_factory/
├── builder/
│   ├── __init__.py
│   ├── api.py              # FastAPI app (endpoints)
│   ├── runner.py          # Build task executor
│   └── state.py           # BuildState model
├── builder/Dockerfile     # Heavy image (Playwright, Docker CLI)
└── docker-compose.yml     # Add builder service
```

**Builder API (`builder/api.py`):**
```python
app = FastAPI()
builds: dict[str, BuildTask] = {}

@app.post("/api/build")
async def submit_build(req: BuildRequest) -> BuildResponse:
    builds[req.build_id] = BuildTask(req)
    asyncio.create_task(run_build(req.build_id))
    return BuildResponse(build_id=req.build_id, status="accepted")

@app.get("/api/build/{build_id}")
async def get_status(build_id: str) -> BuildStatus:
    ...
```

**Builder Runner (`builder/runner.py`):**
```python
class BuildRunner:
    """Execute build subgraph logic outside LangGraph orchestrator."""
    
    async def run(self) -> BuildStatus:
        # Replicate build_subgraph:
        # IMPL_PLAN → CREATE_BACKLOG → IMPLEMENT → UNIT_TEST → INT_TEST → SEED → UAT
        ...
```

### Phase 2: Orchestrator Integration

**New: `graph/nodes/build_proxy.py`:**
```python
class BuildProxy:
    def __init__(self, builder_url: str):
        self.client = HttpClient(base_url=builder_url)
    
    async def build(self, state: dict) -> dict:
        build_id = f"{state['project_name']}-{state['cycle_id']}-{uuid4().hex[:8]}"
        req = BuildRequest(...)
        await self.client.post("/api/build", json=req.model_dump())
        # Poll until complete
        while True:
            status = await self.client.get(f"/api/build/{build_id}")
            if status["status"] in ("pass", "fail", "partial"):
                return self._merge_results(state, status)
            await asyncio.sleep(self.poll_interval)
```

**Changes to `graph/main.py`:**
- Replace `BUILD` node with `BuildProxy` instance
- No changes to other nodes or state schema

### Phase 3: Docker Compose Changes

**`docker-compose.yml`:**
```yaml
services:
  loop:
    deploy:
      resources:
        limits:
          memory: 1G   # ← reduced from 4G
  builder:
    build:
      context: .
      dockerfile: builder/Dockerfile
    ports:
      - "8200:8200"
    volumes:
      - ./output:/app/output
      - /var/run/docker.sock:/var/run/docker.sock:ro
    deploy:
      resources:
        limits:
        memory: 6G
    restart: unless-stopped
```

### Phase 4: Builder Dockerfile

**`builder/Dockerfile`:**
- Heavy dependencies: Playwright, Chromium, Docker CLI
- Inherits requirements.txt
- Runs on port 8200

## Memory Budget

| Container | Before | After | Baseline |
|-----------|--------|-------|----------|
| Orchestrator | 4G (OOM) | 1G (safe) | ~500MB |
| Builder | — | 6G | ~2.5G |
| **Total** | 4G | 7G (+3G budget) | |

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | Orchestrator stays under 1G | `docker stats` |
| 2 | Builder completes without OOM | No exit 137 |
| 3 | Build results merge correctly | State inspection |
| 4 | Concurrent builds isolated | Submit 2 builds |
| 5 | Builder crash ≠ orchestrator crash | Kill builder, verify API |

## Rollback Plan

1. Revert `docker-compose.yml` to single container
2. Replace `build_proxy` with original `build_subgraph` in `graph/main.py`
3. No data loss — orchestrator state is independent

## Estimated Effort

| Component | LOC | Time |
|-----------|-----|------|
| Builder API + runner | ~800 | 4h |
| Builder Dockerfile + compose | ~60 | 1h |
| Build proxy node | ~150 | 2h |
| Orchestrator integration | ~50 | 1h |
| Testing + verification | — | 2h |
| **Total** | **~1060** | **~10h** |

---

*Created: 2026-07-10 | Status: Draft — awaiting approval*