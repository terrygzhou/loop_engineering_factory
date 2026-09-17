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
| `tests/` | Test suite | 322 tests across 17 test files + conftest (see Testing below) |

## Phase Details

**DISCOVER** (2 nodes) — Setup + Interview. HIL gates for project name, description, context folder (+ optional `arckit_artifacts` paths: state key, HIL setup field, or `POST /api/start` body; when non-empty the loader runs in `files=` mode, skipping glob discovery; carried forward in state, powers auto-population + `discover_artifact_audit`). The ArcKit pre-scan runs in **every interactive run** (arckit-web-ingestion). **Tier-2 ingestion (arckit-tier2-ingestion)**: loader accepts ten doc-types — Tier-1 ADMP/REQ/STKE/OAAL/PRIN + Tier-2 OAPR/OASTR/TRANS/BPCM/GAPA (canonical globs, highest-version, per-type audit in `discover_artifact_audit`; any subset is valid). DISCOVER writes, when non-empty: `arckit_product_backlog`, `arckit_open_questions` (OAPR D1–D10 TBD), `arckit_strategy_waves` (OASTR §4 waves win; TRANS §1 fallback). **Build-context ingestion (arckit-build-context, W3)**: the loader also extracts four advisory types — `DATA`/`TECH`/`OASEC`/`OAA-ADM-lite` (per `arckit_loader.VALUABLE_ARTIFACT_TYPES`) — and DISCOVER writes, when non-empty: `arckit_data_model`, `arckit_integration_standards`, `arckit_security_controls`, `arckit_nfr_constraints` (key omitted when the type is absent — never sentinels). `discover_artifact_audit` gains `valuable_absent` (valuable types lacking a valid record). ArcKit artifacts-key inventory: `arckit_product_backlog`, `arckit_open_questions`, `arckit_strategy_waves` (Tier-2) + the four W3 keys above.
The ArcKit pre-scan runs in **every interactive run** (arckit-web-ingestion): valid artefacts in `context_folder` auto-populate setup + interview even under the Web bridge's forced-HIL mode; no valid artefacts → HIL gates as before. Headless auto-approve still skips the scan. **Doc prefill**: when the context folder holds plain documents (`.md`/`.txt`/`.adoc`/`.yaml`, non-ArcKit names, ≤20 files / ≤40 KB total) and no valid ArcKit artefacts auto-populated, the interview `interrupt()` payload gains `prefill` (question key → doc-derived answer) + `note`; `questions` is trimmed to only the un-answered categories — the human still confirms. No docs / LLM fatal → payload is byte-identical to the pre-prefill behavior (no `prefill` key). See `tests/test_discover_docs_prefill.py`.
**DEFINE** — Spec + API contract generation. Parallel LLM calls: source-driven + api-design. When set, ArcKit advisory context (integration standards + NFR constraints) is appended to *both* parallel prompts, capped by `context.arckit_advisory_max_chars` in `config/bounds.yaml` (4000).
**PLAN** — Implementation plan + doubt resolution + 4 architecture diagrams. Parallel diagram generation. **W4 (plan-sequence-view)**: use cases are extracted from `arckit_nfr_constraints` `use_cases` (else interview/spec user-flow lines, else none); each gets a Mermaid `sequenceDiagram` view stored as `artifacts.diagrams["sequence_<slug>"]` in the same parallel `asyncio.gather` pass (one extra LLM call per use case). The generic `sequence` view is emitted only when no use cases are found (fallback = pre-W4 behaviour). LLM-None → placeholder, never raises (Decision 3). PNG conversion + `diagram_pngs` cover the new keys via the existing pipeline; the BUILD prompt gains an advisory ARCHITECTURE DIAGRAMS section listing the diagram views present (byte-identical prompt when none).
**ARCH_REVIEW** — HIL human approval gate. Reject → PLAN with feedback. **Missing build inputs (Tier-2)**: when `arckit_open_questions` is non-empty or valuable-absent Tier-2 types show in the audit, the interrupt payload carries `missing_build_inputs` (advisory); resume accepts an optional `answers` mapping, persisted to `artifacts.arch_review_answers` (approve *and* reject) and appended to the BUILD prompt as a "Review supplements" block. No extra HIL pause. The advisory also lists `valuable_absent` DATA/TECH/OASEC/OAA-ADM-lite types (W3; recomputed from audit artefact records when the audit field is absent).
**BUILD** — OpenHands agent delegation via Gateway API (`/api/conversations`). Writes `build_report.json` manifest (Decision 1); a missing/invalid manifest is a **hard fail** (`BuildReportMissingError`, no free-text fallback — superseded the original regex fallback). If the gateway is unreachable/times out, BUILD falls back to the local LangGraph BUILD subgraph. Retry counter in `artifacts.loop_counts["BUILD"]` (max 2). The agent prompt carries advisory ARCKIT sections (product backlog, strategy waves, data model, integration standards, security controls, NFR constraints — emitted only when the artifacts key is set, each truncated to the prompt char limit) plus a "Review supplements" block for `arch_review_answers`. On a VERIFY-to-BUILD retry it also carries a "Failing acceptance tests" advisory block (ids + `expect` text) for `acceptance_results` failures (W5).
**SEED_DATA** — Model-driven when `artifacts["arckit_data_model"]` is set (non-empty entities): writes `seed_data_model` (entities + classification scheme, deterministic, no LLM) and `seed_data_status = "model_driven"`; otherwise the legacy pass-through placeholder (`skipped_placeholder`). Both forward to VERIFY.
**VERIFY** — Conditional gate (Decision 2 + W5 acceptance). `verify_status` in `artifacts` is the source of truth — set from `test_errors`, critical LLM findings, **or machine-checkable acceptance tests** parsed from the spec's fenced `acceptance_tests` JSON block (checks run locally, bounded by `bounds.verify.acceptance_timeout_s`, results in `artifacts.acceptance_results`). pass -> SHIP; fail -> BUILD (loop; retry prompt carries the failing acceptance-test ids) or ERROR (budget exhausted / terminal gate error). LLM review text stays advisory. Counter in `artifacts.loop_counts["VERIFY"]` (max 2); VERIFY is exempt from the generic livelock guard and owns its error semantics (see VERIFY Gate).
**SHIP** — Forward to REFLECT.
**REFLECT** — Self-improvement. Records cycle to ChromaDB, generates config diffs. W3 target: structured `{section,key,op,value}` diffs + semantic Chroma embedding.

## Decision Log (accepted 2025-07)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | BUILD result = structured `build_report.json` manifest; regex as fallback (later **superseded**: missing/invalid manifest is a hard fail, D1+D3) | Machine-readable, testable, no LLM text parsing in the hot path |
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
- `invoke_skill` / `invoke_skill_async`: on fatal → `return None` (NOT a sentinel string); caller must check.
- Active-path nodes degrade on None (2026-09-16 follow-up): DEFINE spec/parallel, PLAN plan/doubt, SHIP's 4 skill calls, REFLECT git-workflow, DISCOVER fabric/principles/idea-refinement all coerce `None` → `""` (+ warning event) instead of raising `TypeError`; see `tests/test_llm_failure_robustness.py`. DISCOVER doc-prefill (doc-extraction LLM call) returns `(None, None)` on fatal — no `prefill` key in the interrupt payload (byte-identical to pre-prefill behavior).
- Dry-run mode (no LLM configured): returns `"[DRY-RUN] ..."` string — tests must handle this

## BUILD Contract (Decision 1)

- Agent is instructed to write `build_report.json` in the project root with schema:
  ```json
  {"status": "pass|fail|partial", "test_results": "...", "files": [...], "errors": [...]}
  ```
- `graph/nodes/openhands_build.py:_parse_build_report()` validates and normalizes
- Missing/invalid manifest → `BuildReportMissingError` (hard fail; the original legacy regex fallback was removed — Decision 3, no weaker-signal downgrade)
- Unreachable gateway / timed-out / empty conversation → local LangGraph BUILD subgraph (`_run_local_subgraph`)
- `rel_path` sanitization: rejects absolute paths and `..` traversal
- Retry counter: `artifacts.loop_counts["BUILD"]` (max 2); halt sets `next_phase=None` explicitly

## VERIFY Gate (Decision 2 + W5 acceptance)

- `graph/nodes/verify.py` writes `artifacts.verify_status` = pass or fail
- **W5 acceptance tests**: `parse_acceptance_block` (`tools/acceptance.py`) extracts the spec's fenced `{"acceptance_tests": [{id, check[, expect]}]}` JSON; each `check` runs locally, bounded by `bounds.verify.acceptance_timeout_s`. Results land in `artifacts.acceptance_results` (**JSON string**); any `passed: false` folds into `verify_status = "fail"`. No block -> gate behaves exactly as today (`test_errors` only).
- `graph/edges.py:route_phase` VERIFY branch owns its own error/counter semantics - the **generic livelock guard is exempted for VERIFY** (`if error and not next_phase and phase != "VERIFY"`):
  - Gate completed-and-failed (`verify_status == "fail"` OR `test_errors > 0`):
    - loop counter `>= max_loops(2)` -> `"ERROR"` (budget exhausted, halt, never SHIP)
    - counter `>= 1` -> `"BUILD"` (retry; W5 retry prompt carries failing acceptance ids)
    - counter `== 0`, no terminal error -> `"BUILD"` (first deterministic failure, plain retry)
  - Terminal error (`error` set, `next_phase is None`) that **never completed** the gate (counter `== 0`) -> `"ERROR"` (LLM-fatal escape; no retry)
  - Otherwise -> `"SHIP"`
- `_forward_paths["VERIFY"] = "ERROR"` (the generic livelock guard still routes an unowned VERIFY forward to ERROR; a completed-gate retry is handled in the branch above)

## Testing

```bash
.venv/bin/python3 -m pytest tests/ -q
```

~364 tests across 28 files, 0 failures when run in a normal environment (verified 2026-09-16; W2 baseline was 299). In the **sandboxed agent env** the suite is green except two documented environmental caveats (7 `to_thread`/aiosqlite hang files + 9 sandbox-blocked `test_health` socket tests) - see "Environment-Flake & Sandbox Caveats" below. Key test files:

| File | Coverage |
|------|----------|
| `test_w2_wayforward.py` | build_report.json parsing, manifest prompt, rel_path traversal, VERIFY routing (4 paths), LLMError retry/exhaustion/fatal, BUILD counter halt/increment/reset, route_phase BUILD budget |
| `test_llm_failure_robustness.py` | active-path nodes (define/plan/ship/reflect + discover fabric/refine) degrade gracefully when `invoke_skill` returns None (LLM fatal, Decision 3) — no `TypeError`, fallbacks exercised |
| `test_edges.py` | route_phase all phases, _forward_paths chain, HIL interlocks |
| `test_workflow_lifecycle.py` | full chain coverage, forward paths valid |
| `test_checkpointer.py` | AsyncSqliteSaver round-trip |
| `test_runner_hil_loop.py` | HIL interrupt/resume cycle |

## Environment-Flake & Sandbox Caveats (agent env only; pass in CI)

Two environmental conditions in the sandboxed agent env make a full `pytest tests/ -q` fail that are **not** code regressions; both pass in a normal CI environment:

1. **`asyncio.to_thread` event-loop-wakeup hang.** In this sandbox a worker thread can run to completion, but the awaiting event loop never wakes, so `asyncio.to_thread(...)` never resumes. Proven with a 3-line repro independent of this repo (worker prints START/END, main never prints its `to_thread` line; `EXIT=124` on timeout). It affects any test that drives a real (non-mocked) blocking-IO path: `asyncio.to_thread` (DISCOVER LLM calls, `tools/llm.py`) and `aiosqlite` (`graph/checkpointer.py`). ~7 files hang: `test_bridge_custom_events`, `test_checkpointer`, `test_discover_arckit`, `test_runner`, `test_runner_hil_loop`, `test_ui_bridge`, `test_w3_behavioral`. Run files **individually** with a `timeout` in this env; tests that monkeypatch the LLM/checkpointer (e.g. `test_discover.py`, `test_verify_acceptance.py`) pass because they avoid the real path.

2. **Socket bind blocked.** `socket.socket()`/bind raises `PermissionError: [Errno 1] Operation not permitted` in the sandbox, so the 9 socket-dependent `tests/test_health.py` tests fail (the other 10 pass). `service/health.py` / `test_health.py` are untouched by the recent changes; these pass in CI.

> Gate command used for close-out (2026-09-16): `pytest tests/ -q` with the 7 hang files `--ignore`d and the 9 health socket tests `--deselect`ed -> **355 passed, 9 deselected, 0 failures**; `ruff check .` clean.

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

`.dockerignore` excludes: `.venv/`, `output/`, `build/`, `storage/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `coverage.xml`, `htmlcov/`, `.git/`, `.gitignore`, `docs/`, `reports/`, `.codegraph/`.
DO NOT ignore `*.md` (skills are `SKILL.md`) or `tests/` (self-check tests).

## Auto-Handoff

Every 10 turns → `HANDOFF.md`. On compression → save handoff + git status. Keep ≤50 lines.
