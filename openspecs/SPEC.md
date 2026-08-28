# Spec: Loop Engineering Factory (Self-Improving AI Workflow)

Reconstructed 2025-07-28 from the live codebase, `AGENTS.md`, `CLAUDE.md`, and the `spec-driven-development` / `source-driven-development` skill templates. Where the spec was previously implicit (docstrings, decision-log comments, inline `EYW-*` references), it is now explicit.

---

## 1. Objective

**What we're building:** An AI-driven software factory that generates greenfield projects end-to-end. A LangGraph workflow engine orchestrates a 9-phase pipeline and delegates BUILD to remote OpenHands agents. The factory is *self-improving*: REFLECT archives each cycle, queries historical patterns, and proposes config diffs for human approval, so future cycles start smarter.

**Why:** Replace hand-coding of similar greenfield products with a repeatable, auditable, LLM-assisted pipeline. Each run produces a complete, tested, deployable project under `output/<project_name>/` and leaves a feedback trail that improves the next run.

**User:** Operator of the factory (developer / DevOps) who wants to spin up a working project from a project name + description, optionally scan an existing context folder, and approve-or-reject the architectural design before any code is generated.

**Acceptance criteria (one happy cycle):**

1. `python main.py --project my-app --spec "…" --auto-approve` exits with phase `REFLECT` and `error=None`.
2. `output/my-app/` contains generated source, tests, `build/solution.md`, `build/verify_report.md`, and a `build_report.json` manifest from the OpenHands agent.
3. An `AuditLog` JSONL record exists for every phase in `build/audit_logs/`.
4. A cycle record exists in the storage dir and is queryable by `query_patterns`.
5. Re-running with the same project name resumes or produces a clean second cycle without corrupting state.

---

## 2. Tech Stack

| Component | Choice | Why |
|---|---|---|
| Orchestration | LangGraph ≥1.x (`langgraph` OOTB) | Checkpointing + `interrupt()` HIL gates + `Command(resume=…)` |
| Checkpointer | `langgraph-checkpoint-sqlite` (`AsyncSqliteSaver`) | Official, serializable; replaces hand-written `SqliteSaver` (EYW-235) |
| LLM | Local SGLang/OpenAI-compatible `Qwen3.6-27B` via `ChatOpenAI` (langchain-openai) | Deterministic local model, no external API |
| Build agent | OpenHands agent-server v1.30.0 (`/api/conversations`) | Remote, Docker-isolated, 4 CPU / 4 GB |
| Vector store | ChromaDB (HTTP, internal, no host port) | Pattern + feedback embeddings; no PostgreSQL |
| Web backend | FastAPI + WebSocket (single shared `WorkflowBridge`) | SSE/WS event stream to the static UI |
| Frontend | Plain static HTML/CSS/JS (`frontend/static`) served by nginx | No build step |
| Observability | OTel (OTLP) → Phoenix :46006; Prometheus in-process :8081; Loki via promtail (external Grafana stack) | Decision 5 staging |
| Tests | `pytest` + `httpx` test client | 299 tests across 18 files |
| Container | Docker Compose (project name `loop_factory`) | Container names `loop_factory-<service>-1` |

**Ports**

| Port | Service |
|---|---|
| 4080 | nginx → static frontend |
| 48011 | uvicorn FastAPI backend |
| 48081 | health / metrics HTTP server |
| 43005 | OpenHands Gateway (published from :8000) |
| 46006 | Phoenix |
| 8000 (internal) | ChromaDB |
| 8081 (internal) | observability |

**LLM:** `http://pop-os:8080/v1`, model `Qwen3.6-27B`, `temperature=0.1`, `max_tokens=65535`.

---

## 3. Commands

```bash
# Build & run the full stack
docker compose up -d --build loop

# Run tests (no Docker needed)
.venv/bin/python3 -m pytest tests/ -q

# Lint / type-check (optional but recommended)
.venv/bin/python3 -m ruff check .
.venv/bin/python3 -m mypy --strict graph tools config frontend

# CLI
.venv/bin/python3 main.py                                   # interactive (DISCOVER HIL)
.venv/bin/python3 main.py --project my-app --spec "…"      # auto-approve
.venv/bin/python3 main.py --project my-app --context /path # scan existing codebase
.venv/bin/python3 main.py --project my-app --improve       # re-run on prior product

# Web UI
open http://localhost:48011/

# Inspect health / metrics
curl http://localhost:48081/health
curl http://localhost:48081/metrics
```

---

## 4. Project Structure

```
loop_engineering_factory/
├── main.py                      # CLI entry → WorkflowRunner (graph/executor.py)
├── graph/
│   ├── main.py                  # build_graph(): wires nodes, edges, HIL
│   ├── state.py                 # WorkflowState TypedDict + CycleMetrics
│   ├── edges.py                 # route_phase() + _forward_paths livelock guard
│   ├── runner.py                # EYW-236 shared HIL/resume streaming generator
│   ├── executor.py              # WorkflowRunner (CLI + Web shared)
│   ├── checkpointer.py          # LazyAsyncSqliteSaver (official AsyncSqliteSaver)
│   ├── ui_bridge.py             # report_skill_running/completed/failed + SkillTimer
│   ├── review_contract.py       # shared CLI+Web HIL section/feedback dataclasses
│   ├── achg_scanner.py          # EYW-184 ACHG board-status scanner (pure FS)
│   └── nodes/
│       ├── discover.py          # HIL #1 (setup) + HIL #2 (interview) + ArcKit ingest
│       ├── define.py            # spec + API contract (parallel LLM, spec-driven + api-design)
│       ├── plan.py              # planning-and-task-breakdown + doubt-driven + 4 diagrams
│       ├── review.py            # ARCH_REVIEW HIL gate (approve / reject / override)
│       ├── openhands_build.py   # PRIMARY BUILD (OpenHands /api/conversations)
│       ├── build_subgraph_legacy.py  # FALLBACK BUILD (LangGraph subgraph)
│       ├── build_helpers.py     # shared subprocess / parse / write helpers
│       ├── seed_data.py         # pass-through placeholder
│       ├── verify.py            # deterministic gate: pytest fail=0, code review
│       ├── ship.py              # observability + launch checklist + deploy + git
│       └── reflect.py           # archive cycle, generate config diffs, HIL approve
├── frontend/
│   ├── backend/
│   │   ├── app.py               # FastAPI + WS + SSE (single WorkflowBridge)
│   │   ├── workflow_bridge.py   # EYW-236 adapter; _BridgeEvents(WorkflowEvents)
│   │   └── abort_manager.py     # WebSocket abort signal
│   ├── nginx/nginx.conf
│   └── static/{index.html, css/, js/}
├── config/
│   ├── loader.py                # YAML → pydantic model (singleton `config`)
│   ├── bounds_loader.py         # bounds.yaml → `bounds` singleton
│   ├── guardrails.py            # guardrails.yaml → `get_threshold` / `get_arch_review_gate`
│   ├── config.yaml
│   ├── guardrails.yaml
│   └── bounds.yaml
├── tools/
│   ├── llm.py                   # invoke_skill / invoke_skill_async / LLMError / backoff
│   ├── loader.py                # skills registry (hot-reload on mtime)
│   ├── distiller.py             # SKILL.md → purpose+process distilled prompt
│   ├── arckit_loader.py         # EYW-171 ArcKit artefact parser (pure FS)
│   ├── context_manager.py       # prepare_context_for_llm (bounds enforcement)
│   ├── audit_logger.py          # per-cycle JSONL in build/audit_logs/
│   ├── prompt_logger.py         # JSONL LLM call audit
│   └── stream_writer.py         # safe_stream_writer (no-op outside runnable)
├── feedback/
│   ├── chroma_client.py         # get_chroma_client / store_pattern / query_patterns
│   ├── aggregator.py            # record_cycle + history store
│   └── diff_engine.py           # generate_config_diffs + dry_run_validation
├── service/
│   ├── health.py                # /health, /metrics, /ready (Prometheus in-process)
│   ├── evaluator.py             # px_evaluator (spec/plan/review scoring)
│   ├── otel_instrumentor.py     # Tracer singleton + start/end_workflow
│   └── px_gate.py               # arch_review_gate quality thresholds
├── log/logging.py               # setup_logger + log_event (JSON or plain)
├── skills/                      # 35 SKILL.md files (spec-driven, TDD, debugging, …)
├── observability/               # otel-collector + promtail configs
├── tests/                       # 299 tests across 18 files
└── output/                      # generated projects land here
```

---

## 5. Code Style

- Python 3.10+; type hints everywhere; `from __future__ import annotations` where forward refs are needed.
- Loggers are module-scoped (`logger = logging.getLogger(__name__)`); **no** `print()` in production paths (CLI prints are allowed in `main.py` only).
- Every node returns a *partial-update* dict (LangGraph reducer merges). Mutate `state` only through the returned dict, except for the documented `loop_counts` pattern: nodes increment `state["artifacts"]["loop_counts"][phase]` *before* returning and replace the whole dict, because LangGraph only persists node return values.
- Skill invocations use `tools/llm.invoke_skill` / `invoke_skill_async`; always check the return for `None` (Decision 3).
- Prompts to the LLM are built from `tools/distiller.distill_skill` output, capped by `config/bounds.yaml` token/char limits.
- HIL pauses use `from langgraph.types import interrupt` (in-node). The `interrupt_after` list at compile time is used only when `auto_approve` is off.

Example node pattern (from `graph/nodes/seed_data.py`):

```python
def seed_data_node(state: dict) -> dict:
    writer = safe_stream_writer()
    writer(
        {
            "type": "progress",
            "phase": "SEED_DATA",
            "step": "started",
            "detail": "…",
            "ts": time.time(),
        }
    )
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input("SEED_DATA", {"is_placeholder": True})
    return {
        "phase": "SEED_DATA",
        "next_phase": "VERIFY",
        "artifacts": {"seed_data_status": "skipped_placeholder"},
    }
```

Naming: `snake_case` modules, `PascalCase` classes, `SCREAMING_SNAKE` constants. Files are lower-case + underscore.

---

## 6. Testing Strategy

**Framework:** `pytest` (no plugins beyond `pytest-mock` / `httpx` for FastAPI tests).

**Layout:** 18 files, 299 tests, flat under `tests/`. No sub-packages; conftest at `tests/conftest.py`.

**Levels:**

| Level | Files | Scope |
|---|---|---|
| Unit | `test_checkpointer.py`, `test_config_guardrails.py`, `test_config_loader.py`, `test_discover.py`, `test_edges.py` | Pure functions / state machines, no LLM |
| Behavioural | `test_w3_behavioral.py` | Node state invariants (happy + error), `invoke_skill` → `None` |
| Wayforward | `test_w2_wayforward.py` | `build_report.json` parse, manifest prompt, `rel_path` traversal, 4 VERIFY routes, `LLMError` retry/exhaustion/fatal, BUILD counter halt/increment/reset, `route_phase` BUILD budget |
| Lifecycle | `test_workflow_lifecycle.py` | Full chain coverage + `_forward_paths` validity |
| HIL | `test_runner_hil_loop.py`, `test_arch_review_interlocks.py`, `test_bridge_custom_events.py`, `test_ui_bridge.py` | interrupt → resume cycle, ACHG interlock, custom stream events |
| HTTP | `tests/api/`, `test_health.py` | FastAPI test client |

**Conventions:**

- Tests must run **without** a live LLM, OpenHands server, or Chroma DB. `invoke_skill` returns `None` when no LLM is configured; dry-run returns `"[DRY-RUN] …"`.
- A failing test is always a *state invariant* failure, never an LLM-content assertion.
- Every state-machine branch (including `loop_count >= max_loops` livelock paths) has a dedicated test.

---

## 7. Boundaries

### Always

- Run `.venv/bin/python3 -m pytest tests/ -q` before any commit.
- Return partial-update dicts from nodes; never mutate the top-level state outside the documented `loop_counts` pattern.
- Check every `invoke_skill` return for `None` (Decision 3).
- Persist `loop_counts` in `state["artifacts"]["loop_counts"]` (never top-level) and replace the whole dict when incrementing.
- Sanitize OpenHands `rel_path` against absolute / `..` traversal before writing.
- Emit `AuditLog.log_node_input` / `log_node_output` from every node.
- Route all LLM traffic through `tools/llm.py` — no direct `ChatOpenAI` in nodes.

### Ask first

- Add or remove a phase in `graph/main.py` or change `route_phase` in `graph/edges.py`.
- Change the `_forward_paths` map (livelock guard) or `max_loops = 2` constants.
- Change OpenHands API surface (port, header, payload, `build_report.json` schema).
- Change the `build_report.json` manifest schema (Decision 1).
- Add a new ChromaDB collection or change `init_collections` names.
- Add / drop a port in `docker-compose.yml` or change the compose `name:`.
- Add a new LLM provider or model without updating `config/services.llm`.
- Add a new top-level `artifacts.*` key that a node reads back from a *different* node.

### Never

- Commit secrets or `OH_SECRET_KEY` into the repo (use env vars).
- Remove a failing test to make CI green — fix the behaviour, not the assertion.
- Use `print()` for user-facing progress in nodes (use `safe_stream_writer`).
- Call `input()` in `main.py` before the workflow starts (DISCOVER owns all human input).
- Let `VERIFY` route to `SHIP` when `test_errors > 0` or `verify_status == "fail"` (Decision 2).
- Let `BUILD` loop indefinitely: `artifacts.loop_counts["BUILD"] >= 2` must halt (`next_phase=None`, route to `ERROR`).
- Let an exhausted `VERIFY` loop reach `SHIP` — it must route to `ERROR`.
- Put untyped sentinel strings (`"__ERROR__"`) in state; use `error: Optional[str]` + `LLMError` (Decision 3).
- Add a new HIL pause to a node that already resumed in the same step (LangGraph 1.x suppresses it; merge two HIL pauses into one node).
- Use `POSTGRES` / a real DB — pattern storage is ChromaDB only.
- Ignore `*.md` in `.dockerignore` (skills are `SKILL.md`).

---

## 8. Success Criteria (testable)

1. **Full pipeline (auto-approve):** `python main.py --project x --spec "…" --auto-approve` → final phase `REFLECT`, `error=None`, `output/x/` contains `build_report.json`, `build/solution.md`, `build/verify_report.md`.
2. **HIL cycle:** Interactive CLI prompts at DISCOVER (project_setup + interview) and ARCH_REVIEW (approve/reject). Rejecting with feedback loops back to PLAN with `user_review_comments` set; approval advances to BUILD.
3. **Livelock guard:** After `max_loops = 2` on any phase, `route_phase` returns `_forward_paths[phase]` — `VERIFY` → `ERROR`, never `SHIP`.
4. **Build retry:** `artifacts.loop_counts["BUILD"]` increments on retry; at `>= 2`, `next_phase=None` and routing is to `ERROR`.
5. **VERIFY gate:** `verify_status == "fail"` or `test_errors > 0` → BUILD (loop) or ERROR (budget exhausted). `verify_status == "pass"` → SHIP.
6. **LLM errors:** `LLMError` is raised after bounded backoff (base 1.0 s, cap 15 s, max 2 retries); `invoke_skill` returns `None` on fatal. 401/403/404/model-not-found are non-retryable.
7. **build_report.json:** `_parse_build_report` validates `status ∈ {pass, fail, partial}`, `test_results`, `files`, `errors`; rejects `rel_path` with `..` or absolute paths; falls back to legacy regex parse when manifest absent.
8. **Checkpoint resume:** Killing the run mid-phase and re-invoking with the same `thread_id` resumes from the last checkpoint; `AsyncSqliteSaver` round-trips `WorkflowState`.
9. **Auto-approve:** `auto_approve=true` in config or `--auto-approve` flag skips both DISCOVER HILs and the ARCH_REVIEW HIL, and the graph compiles *without* `interrupt_after`.
10. **ACHG interlock (EYW-184):** If any ACHG in the ArcKit tree has `PENDING` board status, `auto-approve` of ARCH_REVIEW is blocked; explicit human `approve` or `reject` is required.
11. **Pattern storage:** `store_pattern` writes to the ChromaDB `patterns` collection; `query_patterns(top_k=3)` returns top-3 matches; failure is graceful (returns `[]` / `None`).
12. **Config diff (REFLECT):** `generate_config_diffs` returns structured `{section, key, op, value}` entries; `dry_run_validation` runs against a copy before apply; human approval is required when `human_approval_required=true`.
13. **Observability:** `/metrics` on :8081 exposes `workflow_duration_seconds`, `phase_duration_seconds`, `phase_errors_total`, `llm_calls_total`, `active_workflows`.
14. **No live-LLM dependency in tests:** All 299 tests pass with `LLM_BASE_URL` unset and `invoke_skill` → `None`.

---

## 9. Open Questions — Resolved (2026-07-07)

| # | Question | Decision | Rationale |
|---|---|---|---|
| 1 | SEED_DATA placeholder | **Keep pass-through** | Greenfield projects have no production data; project-specific seeding belongs in the per-project spec, not the pipeline. Revisit only when seeding becomes a repeatable first-class requirement. |
| 2 | OpenHands agent version pin | **Pin `1.30.0`** | The BUILD contract (build_report.json manifest prompt) depends on agent behaviour; unpinned upgrades are silent contract changes. Bump as an explicit, tested change. |
| 3 | `build_report.json` `schema_version` | **Skip for now (YAGNI)** | Exactly one reader (`_parse_build_report`). Add a version field when a second reader or second writer generation appears. |
| 4 | External Prometheus scrape | **Deferred** | Decision 5 explicitly stages W3; in-process metrics on :8081 cover current needs. Pull forward when the loop-orchestrator scrape target actually exists. |
| 5 | Phoenix `database_uri` default | **Keep compose default** | The `phoenix_data` volume at `/var/lib/phoenix` makes the path canonical and persistent; override by editing the compose env if a different path is ever needed — no config key. |
| 6 | ArcKit new TYPE codes in v2 | **No new types planned** | `arckit_loader.py` already tolerates unknowns (status `UNKNOWN`, per-artifact error lists). Extend the parser when new artefact types actually ship, not speculatively. |
| 7 | Auto-approve + PENDING ACHG interlock | **Interlock wins** | `review.py` blocks auto-approve while any ACHG is PENDING and forces an explicit human decision — matches §8.10. Preserved behaviour, no code change. |
| 8 | `spec_confidence` keyword heuristic | **Keep heuristic** | An LLM-judged scorer would re-introduce the nondeterminism Decision 2 removed from gates. Heuristic with a documented ceiling is sufficient until mis-scoring shows up in evidence. |

---

## 10. Decision Log (accepted 2025-07, verbatim from `AGENTS.md`)

| # | Decision | Rationale |
|---|---|---|
| 1 | BUILD result = structured `build_report.json` manifest; regex as fallback | Machine-readable, testable, no LLM text parsing in the hot path |
| 2 | VERIFY = conditional gate on deterministic `test_errors`; failing build loops to BUILD or halts, never SHIPs | Prevents shipping broken code; LLM review text alone is advisory |
| 3 | LLM failures = typed errors (`LLMError`); `None`-on-fatal; no sentinel strings | Clean error propagation; no magic strings leaking into state |
| 4 | REFLECT = fix (structured diffs + semantic Chroma embedding); demote to audit-only if not deterministic by W3 | Makes self-improvement testable and safe |
| 5 | Observability order = logs (W1) → in-process metrics bootstrap (W2) → Prometheus scrape (W3) | Incremental; no external dependencies until W3 |

---

*Reconstructed by the agent on 2025-07-28 from the codebase at HEAD. Source files referenced: `graph/main.py`, `graph/state.py`, `graph/edges.py`, `graph/runner.py`, `graph/checkpointer.py`, `graph/executor.py`, `graph/ui_bridge.py`, `graph/achg_scanner.py`, `graph/review_contract.py`, `graph/nodes/{discover,define,plan,review,openhands_build,build_subgraph_legacy,build_helpers,seed_data,verify,ship,reflect}.py`, `tools/{llm,loader,distiller,arckit_loader,context_manager,audit_logger,prompt_logger,stream_writer}.py`, `config/{loader,bounds_loader,guardrails}.py`, `feedback/{chroma_client,aggregator,diff_engine}.py`, `service/{health,evaluator,otel_instrumentor,px_gate}.py`, `frontend/backend/{app,workflow_bridge,abort_manager}.py`, `main.py`, `docker-compose.yml`, `config/{config.yaml,guardrails.yaml,bounds.yaml}`, `tests/test_w2_wayforward.py`, `tests/test_w3_behavioral.py`, `AGENTS.md`, `CLAUDE.md`, and the `spec-driven-development` + `source-driven-development` skills.*
