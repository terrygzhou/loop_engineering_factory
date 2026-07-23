# Loop Factory — Codebase Audit Report

**Date:** 2026-07-23
**Scope:** Full cross-layer audit (Graph → Bridge → Frontend → API → Config)

---

## Findings

### 🔴 P0 — Critical

| ID | Severity | Title | Files | Impact |
|---|---|---|---|---|
| A-001 | P0 | Dual backend architectures, zero integration | `api/`, `frontend/backend/` | `api/` (WorkflowService, routes) and `frontend/backend/` (WorkflowBridge) are **independent** FastAPI apps. `api/routes.py` defines `/workflow/*` endpoints with stub implementations (no workflow actually runs). Frontend calls `/api/*` on `frontend/backend/app.py`. `api/` is dead code — 100% untested, untested, unused. |
| A-002 | P0 | CORS wildcard with credentials | `frontend/backend/app.py:52-58` | `allow_origins=["*"], allow_credentials=True` — insecure for production. Any origin can send authenticated requests. |

### 🟠 P1 — Significant

| ID | Severity | Title | Files | Impact |
|---|---|---|---|---|
| A-003 | P1 | Phase matrix drift: SEED_DATA & VERIFY orphaned in HTML | `frontend/static/index.html` | HTML pipeline shows 9 phases. Graph+bridge implement 7. SEED_DATA and VERIFY have no graph nodes, bridge tracking, or edge routing — UI shows phantom phases that never activate. |
| A-004 | P1 | Bridge silently falls back to simulated mode | `frontend/backend/workflow_bridge.py:321-353` | `_try_import_real()` catches `ImportError` and sets `_use_real_workflow = False` with a print(). No UI indication. Workflow runs simulated mode silently producing fake results. |
| A-005 | P1 | Zero authentication on API endpoints | `api/`, `frontend/backend/app.py` | No auth on any endpoint or WebSocket. Anyone can start workflows, approve HIL, abort, read state. |
| A-006 | P1 | Tests are stubs with zero coverage | `tests/` | 8 test files. `test_disabled_modules.py` explicitly skips tests. `test_routes.py`, `test_services.py`, `test_middleware.py` exist but have no real assertions. No tests for graph nodes, bridge, or executor. |
| A-007 | P1 | HIL phase naming inconsistency | `frontend/backend/workflow_bridge.py:116`, `graph/nodes/review.py` | Bridge `HIL_PHASES = {"DISCOVER", "ARCH_REVIEW"}`. Graph register node as `review_node` → "ARCH_REVIEW" in graph but file is `review.py`. Semantic match but fragile — no shared constant enforces alignment. |

### 🟡 P2 — Moderate

| ID | Severity | Title | Files | Impact |
|---|---|---|---|---|
| A-008 | P2 | Bridge stores state in-memory, partial persistence | `frontend/backend/workflow_bridge.py:129-192` | `phase_states`, `events`, `user_inputs` are in-memory dicts. `_save_persisted_inputs()` only persists user inputs. Container restart loses all progress tracking. Recovery from checkpoint DB is incomplete. |
| A-009 | P2 | Builder fallback OOM risk | `graph/nodes/build_proxy.py`, `graph/nodes/build_subgraph.py` | Builder unreachable → subgraph runs inline in orchestrator container. 825-line subgraph with sequential backlog processing can block 3600s and exhaust memory. |
| A-010 | P2 | State duplication: bridge + checkpoint DB | `frontend/backend/workflow_bridge.py`, `graph/executor.py` | Bridge tracks phases in-memory AND checkpoint DB. No sync mechanism — they can diverge. |
| A-011 | P2 | Path traversal protection incomplete | `config/loader.py:172-173` | Rejects `/var/lib/docker`, `/app`, `/container`. Doesn't normalize `..` sequences or validate against volume mounts. |
| A-012 | P2 | Unused root `config.yaml` alongside `config/config.yaml` | `config.yaml`, `config/config.yaml` | Two config files. Root `config.yaml` is legacy. Loader prefers `config/config.yaml` but root one still exists and could confuse contributors. |

### 🔵 Info

| ID | Severity | Title | Files | Impact |
|---|---|---|---|---|
| A-013 | Info | Edge routing: REFLECT has no conditional routing | `graph/edges.py` | `REFLECT` always goes to END. This is correct — no loopback. Edge function doesn't reference REFLECT at all. Minor: adding it would make the code more explicit. |
| A-014 | Info | Guardrails thresholds hardcoded as defaults | `config/guardrails.py:14-26` | Works correctly. YAML can override. Clean design. |

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Loop Factory                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  CLI (main.py) ──→ executor.py ──→ graph/main.py (LangGraph)       │
│                                │                                   │
│                               │ streams chunks                      │
│                                ↓                                   │
│  ┌─────────────────────────────────────────────┐                   │
│  │  Graph Nodes (7):                           │                   │
│  │  DISCOVER → DEFINE → PLAN → ARCH_REVIEW     │                   │
│  │  → BUILD → SHIP → REFLECT → END            │                   │
│  │                                             │                   │
│  │  HIL gates: DISCOVER (interrupt ×2),        │                   │
│  │  ARCH_REVIEW (interrupt ×1)                │                   │
│  │                                             │                   │
│  │  Edge routing:                            │                   │
│  │  Fixed: DISCOVER→DEFINE, DEFINE→PLAN,       │                   │
│  │    PLAN→ARCH_REVIEW, SHIP→REFLECT          │                   │
│  │  Conditional: ARCH_REVIEW, BUILD (quality  │                   │
│  │    gates with loop counters)              │                   │
│  └─────────────────────────────────────────────┘                   │
│                                                                     │
│  Web UI (frontend/backend/app.py :8011)                              │
│  ├── WorkflowBridge (PHASES, HIL_PHASES, run_real/simulated)       │
│  ├── REST: /api/status, /api/metrics, /api/start,                   │
│  │         /api/abort, /api/input                                  │
│  ├── WS: /ws/progress                                              │
│  └── Static: index.html (9 phases including orphaned)            │
│                                                                     │
│  API (api/app.py :8011) — DEAD CODE                                  │
│  ├── WorkflowService (stubs)                                      │
│  ├── REST: /workflow/* (9 endpoints)                                │
│  └── WS: /ws/{workflow_id}                                        │
│                                                                     │
│  Skills: 24 SKILL.md in skills/                                   │
│  Config: config/config.yaml + bounds.yaml + guardrails.yaml       │
│  Observability: OTel, Phoenix evaluator, health server :8081      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Recommendations

1. **Consolidate or remove `api/`** — Either wire `WorkflowService` to share `WorkflowBridge`, or deprecate entirely. Dead code is security and maintenance risk.
2. **Add auth** — At minimum, API key or session token on all endpoints.
3. **Bridge fallback visibility** — Surface simulated vs real mode in UI status.
4. **Sync bridge + checkpoint state** — Derive bridge phase tracking from checkpoint DB rather than maintaining dual state.
5. **Phase alignment** — Remove SEED_DATA/VERIFY from HTML OR implement them as real graph nodes.