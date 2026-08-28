# Loop Factory — Agent Context

## What This Is

AI-driven software factory. LangGraph workflow engine that generates greenfield projects end-to-end. Orchestrates a 10-phase pipeline delegating BUILD to OpenHands agents.

## Architecture at a Glance

```
DISCOVER → DEFINE → PLAN → ARCH_REVIEW → BUILD → SEED_DATA → VERIFY → SHIP → REFLECT
              (HIL)    (HIL)      (HIL)        (OpenHands)
```

Two entry points share `graph/runner.py`:
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
| **State** | Official `AsyncSqliteSaver` via `graph/checkpointer.py` (replaces deprecated langgraph checkpoint) |
| **Auto-approve** | `auto_approve=true` in config bypasses HIL for headless runs |
| **Compose name** | `loop_factory` (top-level `name:` in docker-compose.yml) — drives container names like `loop_factory-loop-1` |

## Skill Loading

```
skill_view(name='coding-principles')     # Before any coding task
skill_view(name='systematic-debugging')   # When things break
skill_view(name='subagent-driven-development') # Tasks spanning 3+ files
```

## Code Structure

| Directory | Purpose | Key Files |
|-----------|---------|-----------|
| `graph/` | LangGraph workflow | `main.py` (graph), `state.py` (TypedDict + CycleMetrics), `edges.py` (routing), `runner.py` (shared HIL/resume runner), `checkpointer.py` (AsyncSqliteSaver) |
| `graph/nodes/` | Phase nodes | `discover.py`, `define.py`, `plan.py`, `openhands_build.py` (active BUILD), `build_subgraph_legacy.py` (fallback), `verify.py` (conditional gate) |
| `frontend/` | Web UI backend | `backend/app.py` :48011, `backend/workflow_bridge.py` |
| `tools/` | Shared utilities | `llm.py` (invoke_skill + invoke_skill_async + LLMError retry), `loader.py` (skills), `context_manager.py` |
| `config/` | Configuration | `config.yaml`, `guardrails.yaml`, `bounds.yaml` |
| `feedback/` | ChromaDB + diffs | `chroma_client.py`, `aggregator.py`, `diff_engine.py` (W3 target) |
| `tests/` | Test suite | 299 tests across 18 files (see Testing below) |

## Phase Details

**DISCOVER** (2 nodes) — Setup + Interview. HIL gates for project name, description, context folder.
**DEFINE** — Spec + API contract generation. Parallel LLM calls: source-driven + api-design.
**PLAN** — Implementation plan + doubt resolution + 4 architecture diagrams. Parallel diagram generation.
**ARCH_REVIEW** — HIL human approval gate. Reject → PLAN with feedback.
**BUILD** — OpenHands agent delegation via Gateway API (`/api/conversations`). Writes `build_report.json` manifest (Decision 1). Falls back to legacy text parser if manifest absent/invalid. Retry counter in `artifacts.loop_counts["BUILD"]` (max 2).
**SEED_DATA** — Pass-through placeholder.
**VERIFY** — Conditional gate (Decision 2). `verify_status` in `artifacts` is the source of truth: `"pass"` → SHIP; `"fail"` → BUILD (loop) or ERROR (budget exhausted). LLM review text is advisory only. Counter in `artifacts.loop_counts["VERIFY"]` (max 2).
**SHIP** — Forward to REFLECT.
**REFLECT** — Self-improvement. Records cycle to ChromaDB, generates config diffs. W3 target: structured `{section,key,op,value}` diffs + semantic Chroma embedding.

## Decision Log (accepted 2025-07)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | BUILD result = structured `build_report.json` manifest; regex as fallback | Machine-readable, testable, no LLM text parsing in the hot path |
| 2 | VERIFY = conditional gate on deterministic `test_errors`; failing build loops to BUILD or halts, never SHIPs | Prevents shipping broken code; LLM review text alone is advisory |
| 3 | LLM failures = typed errors (`LLMError`); `None`-on-fatal; no sentinel strings | Clean error propagation; no magic strings leaking into state |
| 4 | REFLECT = fix (structured diffs + semantic Chroma embedding); demote to audit-only if not deterministic by W3 | Makes self-improvement testable and safe |
| 5 | Observability order = logs (W1) → in-process metrics bootstrap (W2) → Prometheus scrape (W3) | Incremental; no external dependencies until W3 |

## Parallel LLM Calls

- **DEFINE**: `invoke_skill_async()` runs source-driven + api-design in parallel via `asyncio.gather()`
- **PLAN**: 4 diagram LLM calls run in parallel via `asyncio.gather()`
- Uses `tools/llm.py:invoke_skill_async()` → `asyncio.to_thread()` for blocking LLM calls

## LLM Error Handling (Decision 3)

- `tools/llm.py` defines `LLMError` (fatal) and `_LLMTimeout` (retryable)
- `_invoke_with_retry`: bounded exponential backoff (base 1.0s, cap 15s, max 2 retries)
- `_is_retryable`: transient errors (5xx, timeout, connection) retry; 401/403/404/model-not-found do NOT
- `invoke_skill` / `invoke_skill_async`: on fatal → `return None` (NOT a sentinel string); caller must check
- Dry-run mode (no LLM configured): returns `"[DRY-RUN] ..."` string — tests must handle this

## BUILD Contract (Decision 1)

- Agent is instructed to write `build_report.json` in the project root with schema:
  ```json
  {"status": "pass|fail|partial", "test_results": "...", "files": [...], "errors": [...]}
  ```
- `graph/nodes/openhands_build.py:_parse_build_report()` validates and normalizes
- Fallback: legacy regex parser (`_parse_assistant_text`) if manifest absent/invalid
- `rel_path` sanitization: rejects absolute paths and `..` traversal
- Retry counter: `artifacts.loop_counts["BUILD"]` (max 2); halt sets `next_phase=None` explicitly

## VERIFY Gate (Decision 2)

- `graph/nodes/verify.py` writes `artifacts.verify_status` = `"pass"` or `"fail"`
- `graph/edges.py:route_phase` VERIFY branch:
  - `verify_status == "fail"` OR `test_errors > 0` → `"BUILD"` (loop back)
  - Loop counter `>= max_loops(2)` → `"ERROR"` (halt, never SHIP)
  - `error` set AND `next_phase is None` → `"ERROR"` (LLM-fatal escape)
  - Otherwise → `"SHIP"`
- `_forward_paths["VERIFY"] = "ERROR"` (the generic livelock guard fires before the phase-specific branch)

## Testing

```bash
.venv/bin/python3 -m pytest tests/ -q
```

299 tests, 0 failures (W2 baseline). Key test files:

| File | Coverage |
|------|----------|
| `test_w2_wayforward.py` | build_report.json parsing, manifest prompt, rel_path traversal, VERIFY routing (4 paths), LLMError retry/exhaustion/fatal, BUILD counter halt/increment/reset, route_phase BUILD budget |
| `test_edges.py` | route_phase all phases, _forward_paths chain, HIL interlocks |
| `test_workflow_lifecycle.py` | full chain coverage, forward paths valid |
| `test_checkpointer.py` | AsyncSqliteSaver round-trip |
| `test_runner_hil_loop.py` | HIL interrupt/resume cycle |

## Observability

- OTel traces → Phoenix :46006
- Prometheus :9091 (loop orchestrator target needs `/metrics` endpoint — W3)
- Loki via Grafana stack (external network); promtail filters `loop_factory-loop-1`
- Audit logs → `build/audit_logs/`
- In-process metrics bootstrap: W2 (W3 = Prometheus scrape + prompt-snapshot tests)

## Docker Compose

- `loop` — orchestrator + nginx (:4080/:48011/:48081), CPU limit 2, memory 1G
- `openhands` — agent server (:43005), CPU limit 4, memory 4G, `container_name: openhands-server`
- `chromadb`, `otel-collector`, `phoenix`, `promtail` — supporting services
- Resource limits set on all services
- Top-level `name: loop_factory` in docker-compose.yml → container names are `loop_factory-<service>-1`

## Docker Build Context

`.dockerignore` excludes: `.venv/`, `output/`, `build/`, `log/`, `storage/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `coverage.xml`, `htmlcov/`, `.git/`, `.gitignore`, `docs/`, `reports/`, `.codegraph/`.
DO NOT ignore `*.md` (skills are `SKILL.md`) or `tests/` (self-check tests).

## Auto-Handoff

Every 10 turns → `HANDOFF.md`. On compression → save handoff + git status. Keep ≤50 lines.
