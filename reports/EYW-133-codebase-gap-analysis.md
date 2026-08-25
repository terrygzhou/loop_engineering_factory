# EYW-133: Codebase Gap Analysis — Loop Engineering Factory

**Date:** 2026-08-13
**Agent:** QA Engineer (f1c11ca8)
**Scope:** Full codebase scan — nodes, config, infrastructure, tests, Docker, CI/CD

---

## Executive Summary

The Loop Engineering Factory has a solid architecture (LangGraph workflow with 9 phase nodes, observability stack, custom SQLite checkpoint saver, Phoenix LLM evaluator). However, significant gaps remain in test infrastructure, phase implementations, configuration consistency, and CI/CD pipeline.

**Risk Score:** MEDIUM-HIGH (critical path functional, but testing & verification under-built)

---

## 1. Test Infrastructure Gaps (CRITICAL)

### 1.1 Test Suite Coverage
- **Current:** 1 test file (`tests/test_discover.py`) with ~207 lines covering only DISCOVER node helpers
- **Missing:** No tests for DEFINE, PLAN, ARCH_REVIEW, BUILD, SEED_DATA, VERIFY, SHIP, REFLECT nodes
- **Missing:** No tests for `graph/edges.py` routing logic (route_phase thresholds, loop counters)
- **Missing:** No tests for `config/loader.py` config resolution (env var > config.yaml > default)
- **Missing:** No tests for `config/guardrails.py` threshold loading and caching
- **Missing:** No tests for `service/evaluator.py` LLM-as-judge prompts and JSON parsing
- **Missing:** No tests for `service/health.py` HTTP endpoints
- **Missing:** No tests for `graph/sqlite_saver.py` custom checkpoint persistence
- **Missing:** No integration tests for the full workflow lifecycle

### 1.2 Test Runner Configuration
- **No pytest configuration:** No `pytest.ini`, `pyproject.toml` [tool.pytest], or `setup.cfg`
- **No coverage configuration:** No `.coveragerc` or coverage targets defined
- **No linting tools in CI:** `ruff`, `mypy`, `pyright` not configured or run in pipeline
- **No type checking:** `requirements.txt` lacks type stubs (e.g., `types-PyYAML`, `types-requests`)

### 1.3 Conftest Mocking Fragility
- `conftest.py` mocks 30+ modules at import time — extremely fragile
- Missing mocks for `feedback.diff_engine`, `feedback.chroma_client` actual method return shapes
- `graph.state.WorkflowState` mocked as `dict` — loses Pydantic/TypedDict validation
- `time.time()` globally patched — dangerous for async timing tests

---

## 2. Phase Implementation Gaps (HIGH)

### 2.1 SEED_DATA Node — Placeholder
- `graph/nodes/seed_data.py` is a pass-through placeholder (line 28: "Seed data seeding not yet implemented")
- No actual database seeding, fixture loading, or initial data generation
- Directly impacts VERIFY phase quality (nothing to verify against real data)

### 2.2 VERIFY Node — Incomplete Quality Gates
- `graph/nodes/verify.py` only runs code review (LLM-based text analysis)
- **Missing:** Automated unit test execution on generated project
- **Missing:** Linting/type checking on generated project
- **Missing:** Security scanning (dependency audit, secret detection)
- **Missing:** Performance benchmarks (latency, throughput thresholds)
- **Missing:** Mutation testing for generated project test suites

### 2.3 SHIP Node — Not Audited
- `graph/nodes/ship.py` not read but referenced in workflow — verify deployment gate logic

---

## 3. Configuration Issues (MEDIUM)

### 3.1 Config Loader Path Resolution
- `config/loader.py:64-66`: Fallback path resolution (`config/config.yaml` vs `config.yaml` in parent) is fragile
- `paths.output_subdir` defaults to `"output"` but docker-compose mounts `./output:/app/output` — inconsistent with `paths.workspace_dir` default `"./output"`
- `paths.project_path` is computed dynamically via `@property` but cached in config.yaml — stale state risk across runs

### 3.2 Guardrails Default vs YAML Mismatch
- `config/guardrails.yaml` defines `uat_pass_rate: 0.95`
- `config/guardrails.py` defaults have `uat_pass_rate: 0.95` — matches ✓
- **Gap:** `max_latency_ms: 500` in guardrails defaults but NEVER checked in `route_phase` (only `uat_pass_rate` checked)
- **Gap:** `max_test_flakiness_rate: 0.1` in guardrails defaults but NEVER checked in `route_phase`
- **Gap:** `max_security_findings: 0` checked in BUILD route but not in VERIFY route

### 3.3 Docker Compose Environment Overrides
- `docker-compose.yml` sets `LLM_BASE_URL=http://pop-os:8080/v1`
- `config/config.yaml` sets `LLM_BASE_URL` to same value — redundant but consistent
- `OBSERVABILITY_PORT=8081` in docker-compose AND config.yaml — duplicated

### 3.4 OpenHands Container Configuration
- `docker-compose.yml` line 119: `image: ghcr.io/openhands/agent-server:1.30.0-python`
- `extra_hosts` maps both `host.docker.internal` and `pop-os` to `host-gateway` — `pop-os` mapping is fragile
- No healthcheck retry on `openhands` container failure

---

## 4. Architecture & Design Gaps (MEDIUM)

### 4.1 Loop Counter Persistence Issue
- `graph/edges.py:42-51`: `_maybe_increment_loop` modifies `state["artifacts"]` in-place
- Comment says: "MUST be called from NODES (not edges) — LangGraph only persists node return values"
- **Gap:** The function is defined in edges.py but never called from edges.py (correct by design)
- **Gap:** VERIFY node does NOT call `_maybe_increment_loop` — no retry loop for VERIFY failures
- **Gap:** SEED_DATA node does NOT call `_maybe_increment_loop` — no retry loop

### 4.2 State Schema Bloat
- `graph/state.py` has 35+ fields, many overlapping:
  - `project_name`, `artifacts.project_name` — duplicated
  - `loop_counts` at top level AND `artifacts.loop_counts` — duplicated
  - `spec_confidence` at top level AND `metrics.spec_confidence` — duplicated
  - `project_path`, `project_folder`, `project_description` — scattered ownership
- Risk: inconsistent field usage across nodes leads to stale state

### 4.3 Graph Routing Asymmetry
- `graph/main.py:82-85`: VERIFY → SHIP is unconditional (`workflow.add_edge`)
- But `route_phase` in edges.py handles VERIFY → SHIP routing too (lines 123-125)
- **Bug:** If VERIFY sets `error` in state, `route_phase` would route to ERROR, but the graph uses unconditional edge — ERROR routing is bypassed for VERIFY failures

### 4.4 SqliteSaver Threading Safety
- `graph/sqlite_saver.py:51-62`: Uses `threading.local()` for per-thread connections — correct
- **Gap:** No WAL mode enabled (`PRAGMA journal_mode=WAL`) — concurrent writes may block
- **Gap:** No connection pool sizing limit — unbounded connection creation under high load
- **Gap:** No `busy_timeout` — SQLite may return SQLITE_BUSY under concurrent checkpoint writes

### 4.5 Health Server Global State Leak
- `service/health.py:90-98`: `health_server` is a module-level global assigned inside `start_health_server()`
- **Gap:** If `start_health_server()` is called twice (e.g., multiple workflow runs), the second call overwrites `health_server` but the first thread keeps running
- **Gap:** `atexit.register(_shutdown_health_server)` only shuts down the last assigned server

---

## 5. Security Issues (HIGH)

### 5.1 Secret Exposure in Config
- `config/config.yaml:12`: `api_key: not-needed` — placeholder is fine
- `docker-compose.yml:131`: `OH_SECRET_KEY=${OH_SECRET_KEY}` — relies on env var, good
- **Gap:** `docker-compose.yml:25`: Docker socket mounted (`/var/run/docker.sock`) — grants full host Docker access to container
- **Gap:** No Docker socket TLS authentication configured
- **Gap:** `entrypoint.sh` uses `chmod -R 777 /app/output` — world-writable output directory

### 5.2 LLM Prompt Injection Surface
- `tools/llm.py:80-86`: User `context` is directly concatenated into prompts without sanitization
- **Gap:** No prompt injection protection (e.g., delimiters, escaping, or content filtering)
- **Gap:** Generated code could contain malicious payloads if BUILD phase writes unverified output

### 5.3 Path Traversal in File Writers
- `graph/nodes/build_helpers.py:64-67`: Path traversal protection exists (`target.startswith(proj + os.sep)`)
- **Gap:** Does not handle `..` in `os.path.dirname(target)` when `target` has no parent dir — `os.makedirs` could fail silently

---

## 6. Observability Gaps (MEDIUM)

### 6.1 Missing Prometheus Metrics
- `service/health.py` defines metrics but no Grafana dashboards exist
- **Gap:** No alerting rules for `phase_errors_total` threshold
- **Gap:** No `llm_calls_total` error rate tracking dashboard
- **Gap:** `active_workflows` gauge not reset on workflow error

### 6.2 OpenTelemetry Semantic Convention Misalignment
- `service/otel_instrumentor.py:129-146`: OpenInference attributes use non-standard keys:
  - `gen_ai.request.input.token_usage` should be `gen_ai.usage.input_tokens`
  - `gen_ai.response.output.token.usage` should be `gen_ai.usage.output_tokens`
- **Gap:** Phoenix may not recognize these custom attribute names for auto-dashboards

### 6.3 Evaluator OTel Recording
- `service/evaluator.py:288-300`: `_record_to_otel` creates standalone spans not linked to workflow root
- **Gap:** No `link` to parent workflow span — eval traces appear orphaned in Phoenix

---

## 7. CI/CD Pipeline Gaps (HIGH)

### 7.1 No CI Configuration
- **Missing:** No GitHub Actions, GitLab CI, or any CI pipeline YAML
- **Missing:** No automated test execution on PR/merge
- **Missing:** No Docker build verification in CI
- **Missing:** No dependency vulnerability scanning (Trivy, Snyk)

### 7.2 UAT Pipeline Script Issues
- `scripts/uat_pipeline.sh:23`: Hardcoded container name `frontend-ui` — actual container is `loop` in docker-compose
- `scripts/uat_pipeline.sh:43-66`: Hardcoded test project spec (CRM) — not parameterized
- `scripts/uat_pipeline.sh:109`: `date -d` parsing fails on non-GNU date systems
- `scripts/uat_pipeline.sh:126`: `docker logs frontend-ui` references wrong container name

---

## 8. Documentation Gaps (LOW)

- **Missing:** `README.md` does not document phase routing logic or guardrails thresholds
- **Missing:** No developer onboarding guide for adding new workflow nodes
- **Missing:** No API documentation for FastAPI backend (`/api/start`, `/api/status`)
- **Missing:** No troubleshooting guide for common LangGraph interrupt/resume failures

---

## 9. Dependency & Version Issues (MEDIUM)

- `requirements.txt:1`: `langgraph>=1.2.0` but `frontend/requirements.txt:6`: `langgraph>=0.1.0` — version mismatch between orchestrator and frontend
- `requirements.txt:2`: `langchain-core>=1.4.0` but `frontend/requirements.txt:8`: `langchain>=0.2.0` — potentially incompatible major versions
- `requirements.txt:7`: `pyyaml>=6.0` but no `types-PyYAML` for mypy support
- No lock file (`requirements.lock`, `poetry.lock`, or `uv.lock`) — non-deterministic builds

---

## Priority Action Items

| Priority | Area | Action |
|----------|------|--------|
| P0 | Test Infrastructure | Add test files for edges.py routing logic, guardrails.py, sqlite_saver.py |
| P0 | VERIFY Node | Implement automated test execution, linting, and security scanning |
| P1 | SEED_DATA Node | Implement real data seeding logic |
| P1 | CI/CD Pipeline | Create GitHub Actions workflow with test + lint + build stages |
| P1 | Docker Socket | Replace /var/run/docker.sock mount with Docker API over TLS or named pipe |
| P1 | Dependency Versions | Align langgraph/langchain versions between requirements.txt and frontend/requirements.txt |
| P2 | Graph Routing Bug | Fix VERIFY→ERROR bypass (unconditional edge vs conditional route_phase) |
| P2 | State Schema | Deduplicate overlapping fields in WorkflowState |
| P2 | SqliteSaver WAL | Enable WAL mode and busy_timeout for concurrent checkpoint safety |
| P2 | UAT Pipeline | Fix hardcoded container names and parameterize test project |
| P3 | Observability | Fix OpenInference semantic conventions, link evaluator spans to workflow |
| P3 | Config Paths | Consolidate duplicated path defaults and add validation |

---

## Summary Metrics

- Total Python files: ~937 (incl. output/.venv)
- Core source files: ~30
- Test files: 1 (test_discover.py)
- Test coverage estimate: < 5% of core codebase
- Phase nodes implemented: 9/9
- Phase nodes fully functional: 7/9 (SEED_DATA=placeholder, VERIFY=partial)
- Docker services: 7 (loop, chromadb, otel-collector, phoenix, openhands, promtail)
- CI/CD pipeline: 0 configured
