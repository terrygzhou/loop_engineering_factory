# Loop Factory — Codebase Audit

**Date:** 2026-07-28
**Scope:** Full codebase (200+ files across graph/, api/, builder/, frontend/, config/, tools/, skills/)
**Method:** Static analysis + architecture review

---

## 1. Architecture Overview

Loop Factory is an AI-driven workflow engine built on LangGraph. It orchestrates a 10-phase pipeline:

```
DISCOVER → DEFINE → PLAN → ARCH_REVIEW → BUILD → SEED_DATA → VERIFY → SHIP → REFLECT
```

Two entry points share identical logic via `graph/executor.py`:
- **CLI** (`main.py`): Interactive, auto-approve mode
- **Web UI** (`api/app.py`): FastAPI on :8011 with auto-approve on timeout

Key design decisions:
- HIL (Human-in-the-Loop) gates at DISCOVER (2 pauses) and ARCH_REVIEW (1 pause)
- Custom `SqliteSaver` replaces deprecated `langgraph.checkpoint.sqlite` (langgraph >= 1.0)
- Builder service (:8200) runs BUILD phase remotely with fallback to local `build_subgraph`
- Skills system: 24+ SKILL.md files in `skills/`, loaded by `tools/loader.py`
- Docker Compose deployment: single `loop` container (orchestrator + frontend + nginx)

**Verdict:** Architecture is coherent. The single-container design keeps deployment simple. The shared executor pattern is clean — CLI and Web UI run identical workflow logic.

---

## 2. Security Findings

| Severity | Finding | Location |
|----------|---------|----------|
| **HIGH** | `openhands.secret_key = "changeme"` — hardcoded secret in config | `config/config.yaml` |
| **HIGH** | `docker.sock` mounted with `:ro` but loop container runs `docker compose` commands that require write access — works only because Docker CLI falls back to socket operations that ignore the mount flag on the host | `docker-compose.yml` |
| **MEDIUM** | LLM endpoint `http://pop-os:8080` hardcoded as fallback — host-specific hostname leaks into config | `config/config.yaml`, `tools/llm.py` |
| **MEDIUM** | `run_command()` uses `shell=True` with LLM-generated commands — no command sanitization whitelist | `tools/build_helpers.py:run_command()` |
| **LOW** | No CORS configuration on FastAPI — open to any origin in production | `api/app.py` |

---

## 3. Performance Concerns

| Finding | Impact |
|---------|--------|
| `BuildProxy` creates new `httpx.AsyncClient` per build invocation; never reuses connection pool | Moderate — extra TCP handshakes for each build cycle |
| `build_proxy_node()` spawns a new event loop (`asyncio.new_event_loop`) for each call instead of running natively async — creates/destroys loops per phase | Moderate — event loop churn |
| `SqliteSaver` async methods are blocking wrappers (`aget_tuple` calls `get_tuple` synchronously) | Moderate — blocks async event loop on disk I/O |
| `parse_llm_output()` runs multiple regex passes over full LLM output (up to 8K tokens) with list comprehension for `m.start()` lookups — O(n²) pattern matching | Low — only matters for very large LLM outputs |
| `discovery` node: 460-line monolithic function with sequential LLM calls; no parallelization | Moderate — total latency = sum of all call latencies |

---

## 4. Code Quality Issues

### Dead Code

| File | Status | Evidence |
|------|--------|----------|
| `graph/nodes/build_subgraph_legacy.py` (782 lines) | **Still wired** — used as fallback by `build_proxy_node()` when builder is unreachable | `build_proxy.py:183` |
| `graph/nodes/openhands_build.py` (593 lines) | **Active** — wired as `build_agent` in executor | `graph/executor.py` |
| `builder/` directory | **Active** — remote build service | `docker-compose.yml` |
| PostgreSQL config in `config.yaml` | **Unused** — project confirmed "No PostgreSQL", uses ChromaDB internally | `config/config.yaml` |

### Smell Patterns

**Duplicated Code** — `parse_uat_pass_rate()` and `resolve_service_name()` in `build_helpers.py` duplicate logic from `resolve_app_service()`. All three parse docker-compose YAML to discover service names using nearly identical patterns.

**Message Chains** — `executor.py → node → tools/llm.py → tools/distiller.py → tools/context_manager.py → config/loader.py`. Five-hop chain just to get an LLM response. The `config` object is accessed through module-level import that triggers nested class evaluation.

**Middle Man** — `build.py` (39 lines) is a thin wrapper that delegates entirely to `openhands_build.py`. Could be inlined or removed.

**Speculative Generality** — `CycleMetrics` Pydantic model has fields like `security_findings` and `test_flakiness_rate` that are set but never consumed by REFLECT or edge routing. The guardrails system (`config/guardrails.yaml`) defines thresholds that aren't actively enforced.

**Data Clumps** — `WorkflowState` has both `project_path` and `project_folder` with overlapping semantics. `artifacts` dict is a catch-all for spec text, tasks, backlog, build status, and LLM outputs — classic god-dict pattern.

**Primitive Obsession** — Build backlog items are `dict[str, Any]` instead of typed models. Status strings ("pass"/"fail"/"partial") are magic strings, not enums.

### Structural Issues

- `discover.py` (460 lines) and `plan.py` (523 lines) are monolithic nodes. Each does 5-6 sequential LLM calls with inline prompt construction. Violates single responsibility.
- `graph/state.py` imports `Optional` from `typing` but Python 3.10+ supports `list[X]` and `dict[K,V]` natively — the `from __future__ import annotations` is not present, so some usages still need `List`/`Dict`.
- `WorkflowService` in `api/services.py` stores workflow state in-memory only. No persistence means redeploy loses all active workflows.

---

## 5. Configuration Issues

| Finding | Location |
|---------|----------|
| `project_path: '{{project_name}}'` — Jinja template string stored as literal value, not resolved | `config/config.yaml` |
| Duplicate Postgres config section despite "No PostgreSQL" policy | `config/config.yaml` |
| `logs/` and `tests/` listed twice in `.gitignore` | `.gitignore` |
| `output_dir: /app/output` (container path) vs `workspace_dir: ./output` (host path) — two different paths for the same concept | `config/config.yaml` |
| Hardcoded model name `Qwen3.6-27B-NVFP4` in multiple places instead of single config value | `tools/llm.py`, `config.yaml` |

---

## 6. Testing Coverage

| Area | Status |
|------|--------|
| Unit tests | **None found** — no test files in the codebase |
| Integration tests | **None** — no `tests/` directory with test content |
| LLM mocking | **Not implemented** — `tools/llm.py` has no test fixtures or mock providers |
| Edge function tests | **Not tested** — `edges.py` routing logic is unverifiable without tests |
| Config loader tests | **Not tested** — the nested class evaluation pattern is fragile without test coverage |

**Verdict:** Zero automated test coverage. The codebase relies entirely on manual verification through Docker Compose runs. This is the single highest-risk gap.

---

## 7. DevOps / Deployment

| Finding | Impact |
|---------|--------|
| `Dockerfile` multi-stage build: builder stage installs OpenHands full deps, then final stage only copies needed artifacts — good pattern | Positive |
| `docker-compose.yml` healthchecks use `nc -z` — works but fragile; would break if nginx changes bind address | Low |
| No `.dockerignore` found — build context may include unnecessary files | Low |
| `requirements.txt` pins `langgraph>=0.5` but custom `SqliteSaver` is tightly coupled to internal LangGraph APIs — any major version bump could break checkpointing | High |
| `Dockerfile` runs as root — no `USER` directive for non-root execution | Medium |
| No resource limits in `docker-compose.yml` — container can consume unbounded memory/CPU | Medium |

---

## 8. Observability Gaps

| Finding | Detail |
|---------|--------|
| OTel instrumentation exists (`service/otel_instrumentor.py`) but uses graceful import with fallback — if OTel packages are missing, tracing silently degrades to no-ops |
| No structured logging — `print()` statements throughout executor, nodes, and build helpers |
| Audit logging (`tools/audit_logger.py`) writes JSON to `build/audit_logs/` — good, but no rotation policy or size limit |
| No distributed tracing correlation IDs across CLI → LangGraph node → LLM call → builder service |
| Prometheus metrics endpoint not exposed — despite project having Grafana/Prometheus stack, loop_factory doesn't expose `/metrics` |

---

## 9. Recommendations (Prioritized)

### P0 — Immediate

1. **Replace `openhands.secret_key = "changeme"`** — use environment variable or secrets manager. A generated project inherits this secret.
2. **Add basic test suite** — at minimum: edge routing logic, config loader resolution order, `parse_llm_output()` parser, `SqliteSaver` serialization roundtrip.
3. **Fix `SqliteSaver` async methods** — use `asyncio.to_thread()` or run SQLite in a dedicated thread pool instead of blocking the event loop.

### P1 — Short-term (1-2 weeks)

4. **Split `discover.py` and `plan.py`** into sub-nodes. Each LLM call becomes its own node with clear input/output contracts.
5. **Consolidate docker-compose parsing** — `resolve_app_service()`, `resolve_service_name()`, and related helpers should be a single function in `build_helpers.py`.
6. **Enum for status values** — replace magic strings ("pass"/"fail"/"partial") with proper enums across build proxy and workflow state.
7. **Add resource limits** to `docker-compose.yml` — `deploy.resources.limits` for memory and CPU.
8. **Drop duplicate Postgres config** from `config.yaml`.

### P2 — Medium-term (1-2 months)

9. **Migrate `WorkflowService` to persistent storage** — SQLite or the existing `SqliteSaver` checkpoint system so active workflows survive redeploy.
10. **Add CORS middleware** to FastAPI with configurable allow-origins.
11. **Command sanitization** — add an allowlist or sandbox for `run_command()` with `shell=True`.
12. **Expose Prometheus metrics** — `/metrics` endpoint with phase duration, error rates, and LLM token counts.
13. **Run container as non-root** — add `USER` directive to Dockerfile.

### P3 — Long-term

14. **Typed backlog items** — replace `dict[str, Any]` with Pydantic models for build backlog.
15. **Distributed tracing** — propagate trace IDs from API request through LangGraph nodes to LLM calls.
16. **Guardrails enforcement** — wire the thresholds in `guardrails.yaml` to actual edge routing decisions in REFLECT → REBUILD logic.

---

## 10. Summary

| Category | Score (1-5) | Notes |
|----------|-------------|-------|
| Architecture | 4 | Clean separation of concerns, good shared executor pattern |
| Security | 2 | Hardcoded secrets, shell injection via LLM commands |
| Performance | 3 | Async wrappers block, event loop churn in build proxy |
| Code Quality | 2 | Dead code still wired, monolithic nodes, zero tests |
| Configuration | 2 | Duplicates, hardcoded values, unresolved templates |
| Observability | 2 | Print statements, no metrics endpoint, no log rotation |
| DevOps | 3 | Multi-stage Docker is good, missing resource limits and .dockerignore |

**Overall risk: MEDIUM.** The architecture is sound, but the lack of tests and hardcoded secrets are the two things that could cause real incidents. Fix P0 items first.
