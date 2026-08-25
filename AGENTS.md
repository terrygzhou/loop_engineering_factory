# Loop Factory — Agent Context

## What This Is

AI-driven software factory. LangGraph workflow engine that generates greenfield projects end-to-end. Orchestrates a 10-phase pipeline delegating BUILD to OpenHands agents.

## Architecture at a Glance

```
DISCOVER → DEFINE → PLAN → ARCH_REVIEW → BUILD → SEED_DATA → VERIFY → SHIP → REFLECT
              (HIL)    (HIL)      (HIL)        (OpenHands)
```

Two entry points share `graph/executor.py`:
- **CLI** (`main.py`): auto-approve mode
- **Web UI** (`frontend/backend/app.py`): FastAPI :48011, auto-approve on timeout

## Key Constraints

| Item | Detail |
|------|--------|
| **Build command** | `docker compose up -d --build loop` |
| **Ports** | nginx :4080, FastAPI :48011, health :48081, OpenHands Gateway :43005, Phoenix :46006 |
| **LLM** | `LLM_BASE_URL=http://pop-os:8080/v1` (local SGLang Qwen3.6-27B-NVFP4) |
| **No PostgreSQL** | Pattern storage via ChromaDB (internal, no host port) |
| **HIL gates** | DISCOVER (2 pauses), ARCH_REVIEW (1 pause); node-level `interrupt()` from `langgraph.types` |
| **Artifacts** | Generated projects land in `output/` |
| **Skills** | 35 SKILL.md files in `skills/`; loaded by `tools/loader.py` |
| **State** | Custom `SqliteSaver` (graph/sqlite_saver.py) replaces deprecated langgraph checkpoint |
| **Auto-approve** | `auto_approve=true` in config bypasses HIL for headless runs |

## Skill Loading

```
skill_view(name='coding-principles')     # Before any coding task
skill_view(name='systematic-debugging')   # When things break
skill_view(name='subagent-driven-development') # Tasks spanning 3+ files
```

## Code Structure

| Directory | Purpose | Key Files |
|-----------|---------|-----------|
| `graph/` | LangGraph workflow | `main.py` (graph), `state.py` (TypedDict), `edges.py` (routing), `executor.py` (shared logic) |
| `graph/nodes/` | Phase nodes | `discover.py`, `define.py`, `plan.py`, `openhands_build.py` (active BUILD), `build_subgraph_legacy.py` (fallback) |
| `frontend/` | Web UI backend | `backend/app.py` :48011, `backend/workflow_bridge.py` |
| `builder/` | Remote build service (DELETED — OpenHands Gateway handles BUILD) |
| `tools/` | Shared utilities | `llm.py` (invoke_skill + invoke_skill_async), `loader.py` (skills), `context_manager.py` |
| `frontend/` | Web UI backend | `backend/workflow_bridge.py` (1141 lines — largest file) |
| `config/` | Configuration | `config.yaml`, `guardrails.yaml`, `bounds.yaml` |
| `feedback/` | ChromaDB + diffs | `chroma_client.py`, `aggregator.py` |
| `tests/` | Test suite | 160 tests across 4 files |

## Phase Details

**DISCOVER** (2 nodes) — Setup + Interview. HIL gates for project name, description, context folder.
**DEFINE** — Spec + API contract generation. Parallel LLM calls: source-driven + api-design (Phase 4).
**PLAN** — Implementation plan + doubt resolution + 4 architecture diagrams. Parallel diagram generation (Phase 4).
**ARCH_REVIEW** — HIL human approval gate. Reject → PLAN with feedback.
**BUILD** — OpenHands agent delegation via Gateway API. Fallback to `build_subgraph_legacy.py`.
**SEED_DATA** → **VERIFY** → **SHIP** — Pass-through placeholders. VERIFY resets metrics to passing.
**REFLECT** — Self-improvement. Records cycle to ChromaDB, generates config diffs.

## Parallel LLM Calls (Phase 4)

- **DEFINE**: `invoke_skill_async()` runs source-driven + api-design in parallel via `asyncio.gather()`
- **PLAN**: 4 diagram LLM calls run in parallel via `asyncio.gather()`
- Uses `tools/llm.py:invoke_skill_async()` → `asyncio.to_thread()` for blocking LLM calls

## Testing

```bash
.venv/bin/python3 -m pytest tests/ -v
```

160 tests pass. 34 pre-existing failures in `test_services.py`, `test_loader.py`, `test_edges.py` (unrelated).

## Observability

- OTel traces → Phoenix :46006
- Prometheus :9091 (loop orchestrator target needs `/metrics` endpoint — P2)
- Loki via Grafana stack (external network)
- Audit logs → `build/audit_logs/`

## Docker Compose

- `loop` — orchestrator + nginx (:4080/:48011/:48081), CPU limit 2, memory 1G
- `openhands` — agent server (:43005), CPU limit 4, memory 4G
- `chromadb`, `otel-collector`, `phoenix`, `promtail` — supporting services
- Resource limits set on all services

## Auto-Handoff

Every 10 turns → `HANDOFF.md`. On compression → save handoff + git status. Keep ≤50 lines.
