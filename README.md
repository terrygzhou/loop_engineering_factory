# Loop Factory

AI agent-driven loop-engineering factory to produce software products based on the architecture and business specifications, with minimal human intervention.

![The UI dashboard](image.png)

It is a Self-improving AI-driven software development engine built on LangGraph.


```
DISCOVER → DEFINE → PLAN → ARCH_REVIEW → BUILD → SEED_DATA → VERIFY → SHIP → REFLECT
```

### State Machine

```mermaid
stateDiagram-v2
    direction LR

    [*] --> DISCOVER

    %% Fixed forward edges (graph/main.py)
    DISCOVER --> DEFINE
    DEFINE --> PLAN
    PLAN --> ARCH_REVIEW
    SEED_DATA --> VERIFY
    VERIFY --> SHIP
    SHIP --> REFLECT
    REFLECT --> [*]

    %% Conditional edges (graph/edges.py route_phase)
    ARCH_REVIEW --> BUILD : approved
    ARCH_REVIEW --> PLAN : rejected

    BUILD --> SEED_DATA : gates pass
    BUILD --> BUILD : security / revisions / UAT gate failed
    BUILD --> REFLECT : 3 consecutive build failures

    %% Self-loops (quality gates in edges.py)
    DEFINE --> DEFINE : spec_confidence < 0.9 (max 2 loops)
    PLAN --> PLAN : arch_uncertainty > 0.8 (max 2 loops)

    %% HIL interrupt points
    note right of DISCOVER : interrupt() x2<br/>project_setup + interview
    note right of ARCH_REVIEW : interrupt() x1<br/>human approve/reject

    classDef hil fill:#FFD700,stroke:#B8860B,stroke-width:2px,color:#000
    classDef gate fill:#87CEEB,stroke:#4682B4,stroke-width:2px,color:#000
    classDef normal fill:#F0F0F0,stroke:#999,stroke-width:1px,color:#000
    class DISCOVER,ARCH_REVIEW hil
    class DEFINE,PLAN,BUILD gate
    class SEED_DATA,VERIFY,SHIP,REFLECT normal
```

#### BUILD Phase: OpenHands Agent Delegation

The BUILD node delegates to the OpenHands agent-server via the Gateway API (OpenAI-compatible). Falls back to the local legacy subgraph if the agent-server is unreachable.

```mermaid
graph LR
    START([START]) --> OH_CHECK["OpenHands health\ncheck"]

    OH_CHECK -->|healthy| CREATE_CONV["Create conversation\nPOST /v1/chat/completions"]
    OH_CHECK -->|unhealthy| LEGACY["Legacy subgraph\nbuild_subgraph_legacy.py"]

    CREATE_CONV --> POLL["Poll conversation\nGET /api/conversations/{id}"]
    POLL -->|finished| PARSE["Parse assistant text"]
    POLL -->|timeout| LEGACY

    PARSE --> WRITE_FILES["Write files to disk"]
    WRITE_FILES --> END([END])

    LEGACY --> LEGACY_RUN["Legacy build subgraph\nIMPL_PLAN → IMPLEMENT\nUNIT_TEST → UAT"]
    LEGACY_RUN --> END

    classDef agent fill:#90EE90,stroke:#2E8B57,stroke-width:2px,color:#000
    classDef fallback fill:#FF9800,stroke:#E65100,stroke-width:1px,color:#000
    classDef node fill:#2196F3,stroke:#1565C0,stroke-width:1px,color:#fff
    class OH_CHECK,CREATE_CONV,POLL,PARSE,WRITE_FILES node
    class LEGACY,LEGACY_RUN fallback
```

| Step | Implementation | Notes |
|------|---------------|-------|
| Health check | `GET /health` | Falls back to legacy on any failure |
| Create conversation | `POST /v1/chat/completions` | Profile `build_agent` created idempotently |
| Poll | `GET /api/conversations/{id}` | 5s interval, 1h timeout |
| Parse | Regex → file blocks + test results | Derives `build_status`: pass/partial/fail |
| Write files | Disk I/O to `project_path` | Downstream phases (SEED_DATA, VERIFY) read from disk |
| Legacy fallback | `build_subgraph_legacy.py` | Full IMPL_PLAN → IMPLEMENT → UNIT_TEST → UAT pipeline |

**Outer graph routing** (from `edges.py`): BUILD self-loops if `security_findings > 0`, `review_revisions > max`, or `uat_pass_rate < min`. After 3 consecutive build failures, routes to `REFLECT` to skip `SEED_DATA`/`VERIFY`/`SHIP`.

Each cycle runs through these phases with quality gates, HIL (Human-in-the-Loop) review gates, and self-improvement via ChromaDB pattern storage. CLI and Web UI share the same `WorkflowRunner` — identical node execution, different UX layers.

---

## Architecture

### Container Architecture

```mermaid
graph LR
    subgraph User["User Layer"]
        U[("User")]
    end

    subgraph LoopFactory["Loop Factory"]
        subgraph Entry["Entry Points"]
            CLI["CLI\n(main.py)"]
            WebUI["Web UI\n(FastAPI :8011)"]
            Nginx["nginx\n(:80)"]
        end

        subgraph Engine["LangGraph Engine"]
            Graph["StateGraph\n9 Phases"]
            Nodes["Phase Nodes\ng/nodes/*.py"]
            Bridge["HIL Bridge\nCommand(resume)"]
            BuildProxy["BUILD proxy\nopenhands_build.py"]
        end

        subgraph Tools["Tool Layer"]
            LLM["LLM Tool\n(tools/llm.py)"]
            Skills["Skill Loader\n(20 SKILL.md)"]
            ChromaC["ChromaDB Client\n(feedback/)"]
        end
    end

    subgraph External["External Services"]
        LLM_Srv["LLM Server\n(vLLM :8080)"]
        Docker["Docker Engine"]
        Chroma["ChromaDB :8000\n(internal)"]
        OpenHands["OpenHands\n(:8000)\nAgent Server"]
        Builder["Builder\n(:8200)\nRemote build worker"]
    end

    U -->|browser| WebUI
    U -->|terminal| CLI
    CLI -->|stream| Graph
    WebUI -->|SSE| Bridge
    Bridge --> Graph
    Graph --> Nodes
    Nodes --> LLM
    LLM --> Skills
    LLM --> ChromaC
    LLM -->|"POST /v1/chat/completions"| LLM_Srv
    Graph -->|"build & deploy"| Docker
    ChromaC <--> Chroma
    WebUI --> Nginx

    %% BUILD: OpenHands agent delegation with legacy fallback
    Nodes -->|"BUILD"| BuildProxy
    BuildProxy -->|"agent mode"| OpenHands
    BuildProxy -->|"fallback"| Docker

    classDef default fill:#F0F0F0,stroke:#999,stroke-width:1px,color:#000
    classDef hil fill:#FFD700,stroke:#B8860B,stroke-width:2px,color:#000
    classDef agent fill:#90EE90,stroke:#2E8B57,stroke-width:2px,color:#000
    class BuildProxy agent
    class OpenHands,Builder external
```

### Deployment Architecture

```mermaid
graph TB
    U[("User")]

    subgraph Host["Host Machine"]
        LLM_C[("LLM Server\nvLLM :8080")]

        subgraph DockerStack["Docker Compose Stack"]
            LC[("Loop Container\n:80 / :8011 / :8081")]
            BLD[("Builder\n:8200")]
            CC[("ChromaDB\n:8000 internal")]
            OC[("OTel Collector\n:4318")]
            PH[("Phoenix\n:6006")]
            OH[("OpenHands\n:8000 → :3005")]
            PT[("Promtail")]
        end
    end

    U -->|"HTTP :80 / :8011"| LC
    LC -->|"gRPC :8000"| CC
    LC -->|"OTLP :4318"| OC
    LC -->|"HTTP :8080"| LLM_C
    LC -->|"Gateway"| OH
    LC -->|"build"| BLD
    OH -->|"HTTP :8080"| LLM_C
    OC -->|"HTTP :6006"| PH
    PT -->|"logs"| PH
```

### Component Overview

| Component | Responsibility | Config Key |
|-----------|---------------|------------|
| `main.py` | CLI entry — headless auto-approve | `workflow.auto_approve` |
| `api/app.py` | FastAPI backend — HIL mode via REST | `services.loop_api.*` |
| `frontend/backend/workflow_bridge.py` | SSE event bridge + HIL interrupt handling | `services.product.*` |
| `graph/main.py` | LangGraph StateGraph definition | `workflow.hil_mode` |
| `graph/nodes/*.py` | Phase node implementations (9 nodes) | `paths.*` |
| `tools/llm.py` | LLM call dispatch with retry & context compression | `services.llm.*` |
| `tools/loader.py` | Skill registry discovery & hot-reload | `workflow.skill_registry_path` |
| `feedback/chroma_client.py` | ChromaDB pattern storage/retrieval | `services.chroma.*` |
| `service/otel_instrumentor.py` | OpenTelemetry trace export | `services.otel.*` |
| `service/evaluator.py` | LLM-as-judge evaluator — context-aware phase scoring → Phoenix UI | `services.otel.*`, `services.llm.*` |
| `service/health.py` | Health check server + dependency verification | `services.observability.*` |
| `config/loader.py` | Three-tier config: `ENV > YAML > default` | N/A (meta) |

---

## Skills Per Workflow State

Each workflow phase chains specialized skills from `skills/` (20 registered). Skills are `SKILL.md` files — context templates that the LLM follows to produce specific outputs. A missing skill is silently skipped.

### Phase-Specific Skill Chains

| Phase | Skills Chained | Purpose |
|-------|----------------|---------|
| **DISCOVER** | `interview-me` (HIL interrupt) → `coding-principles` (context refinement) → Fabric Prompt Engineering | Structured 9-question interview. Scans existing codebases. Generates `requirement.md`. Auto-generates defaults in auto-approve mode. |
| **DEFINE** | `writing-plans` → `api-and-interface-design` | Generates structured specification + API contract. Incorporates user review feedback if returning from ARCH_REVIEW rejection. |
| **PLAN** | `writing-plans` → `doubt-driven-development` → `architecture-diagram-generator` | Implementation plan, architectural doubt resolution, and diagram generation. Outputs `solution.md` + diagrams. |
|| **ARCH_REVIEW** | _(human gate — no skills called)_ | User reviews spec, plan, and Mermaid diagrams. Approve → BUILD, Reject → PLAN. |
| **BUILD** | `incremental-implementation` → `test-driven-development` (per task) → **deploy_gate** (health check) → SuperWeb UAT (`agent` mode default) → `security-and-hardening` → `requesting-code-review` → **SECURITY_GATE** | Per-task code gen with TDD. Docker build + health check. UAT: SuperWeb agent mode with scripted/LLM fallbacks. SECURITY_GATE: aggregate STRIDE security audit + code quality review. |
| **SEED_DATA** | `ai-workflow-data-seeding` | Test data generation. Executes seed scripts inside Docker containers. |
| **VERIFY** | _(placeholder — pass-through to SHIP)_ | Currently a pass-through node. UAT moved to BUILD subgraph. Future: real test execution, linting, security scans, and performance profiling. |
| **SHIP** | `observability-and-instrumentation` → `shipping-and-launch` → `production-deployment` → `git-workflow` | Deployment packaging: observability setup, launch checklist, cloud platform configuration (AWS/Azure/GCP), version tagging. |
| **REFLECT** | Internal `diff_engine` → `context-pruning` → `git-workflow` | Cycle analysis: aggregates metrics, queries ChromaDB patterns, generates config/guardrail diff proposals. Human approval gate for changes. |

### Local Skills Registry (20 skills)

```
skills/
├── ai-workflow-data-seeding/SKILL.md       # SEED_DATA phase
├── api-and-interface-design/SKILL.md        # DEFINE phase
├── architecture-diagram-generator/SKILL.md # PLAN phase
├── code-simplification/SKILL.md            # Standalone (future VERIFY phase)
├── coding-principles/SKILL.md              # DISCOVER phase (context refinement)
├── docker-compose-deployment/SKILL.md      # Standalone (local dev reference)
├── doubt-driven-development/SKILL.md       # PLAN phase
├── git-workflow/SKILL.md                   # SHIP + REFLECT phases
├── incremental-implementation/SKILL.md     # BUILD phase
├── interview-me/SKILL.md                   # DISCOVER phase
├── observability-and-instrumentation/SKILL.md # SHIP phase
├── performance-optimization/SKILL.md       # Standalone (future VERIFY phase)
├── production-deployment/SKILL.md         # SHIP phase
├── requesting-code-review/SKILL.md        # BUILD phase (SECURITY_GATE)
├── security-and-hardening/SKILL.md        # BUILD phase (SECURITY_GATE)
├── shipping-and-launch/SKILL.md            # SHIP phase
├── systematic-debugging/SKILL.md          # Standalone (future VERIFY phase)
├── test-driven-development/SKILL.md       # BUILD phase
├── uat-workflow/SKILL.md                   # BUILD phase (fallback)
└── writing-plans/SKILL.md                  # DEFINE + PLAN phases
```

**Total per cycle**: ~20–35 LLM calls. BUILD loops (up to 2 retries) can increase this.

---

## How to Run It Locally

### Prerequisites

- **Docker** + **Docker Compose** (v2.20+)
- **LLM endpoint** (OpenAI-compatible, e.g., vLLM Qwen3.6-27B on `:8080`)

### Configuration

All external parameters are centralized in `config/config.yaml`. Override via environment variables or direct YAML edits:

```bash
# Quick override — no code changes needed
export LLM_BASE_URL="http://host.docker.internal:8080/v1"
export LLM_MODEL="Qwen3.6-27B"
export LOG_LEVEL="info"
```

Or edit `config/config.yaml` directly:

```yaml
services:
  llm:
    base_url: http://host.docker.internal:8080/v1
    model: Qwen3.6-27B
    temperature: 0.1
    max_tokens: 32768

observability:
  log_level: info
  port: 8081
```

### Option A: CLI (Headless, Auto-Approve)

Runs the full pipeline without human intervention. DISCOVER generates default interview notes from the spec.

```bash
# Build and start (no bind mounts — uses Docker volume for output)
docker compose up -d --build loop

# Monitor logs
docker compose logs -f loop

# Access the health endpoint
curl http://localhost:8081/health
```

### Option B: Web UI (Human-in-the-Loop)

Interactive mode with SSE event streaming, quality gates dashboard, and diagram rendering.

```bash
# Start the stack
docker compose up -d --build loop

# Open the UI
# Frontend: http://localhost (nginx :80)
# API: http://localhost:8011
# Health: http://localhost:8081
```

### Docker Stack Services

| Service | Port | Purpose |
|---------|------|---------|
| `loop` | :80 | nginx — static frontend |
| `loop` | :8011 | FastAPI backend — workflow API |
| `loop` | :8081 | Health check server |
| `chromadb` | :8000 (internal) | Pattern storage |
| `otel-collector` | :4318 | OpenTelemetry trace collection |
| `phoenix` | :6006 | Trace visualization + LLM evaluation UI (Arize Phoenix) |
| `prometheus` | :9090 | Metrics scraping |
| `grafana` | :3000 | Observability dashboards |
| `promtail` | _(internal)_ | Log aggregation |
| `openhands` | :3005 | OpenHands Agent Server — SuperWeb UAT agent mode |

### Stopping & Restarting

```bash
# Stop everything
docker compose down

# Rebuild without cache (after code changes)
docker compose build --no-cache loop
docker compose up -d loop

# Full restart (preserves volumes)
docker compose stop
docker compose rm -f
docker compose up -d --build
```

> ⚠️ **Token Usage**: A full cycle makes 20–35 LLM calls. Monitor your provider's usage dashboard during long runs.

---

## Key Components

- **Entry Points**: CLI (`main.py`) for headless auto-approve, or Web UI (FastAPI `:8011`) for HIL workflow
- **LangGraph Engine**: `StateGraph` with 9 phase nodes, conditional routing via quality gates, OOTB `interrupt_after` for HIL pauses
- **Skills System**: 20 `SKILL.md` files loaded by `tools/loader.py`, invoked via `tools/llm.py` with context optimization
- **HIL Bridge**: SSE event streaming between LangGraph executor and frontend; supports double-pause DISCOVER interview and ARCH_REVIEW diagram approval
- **Feedback Loop**: ChromaDB stores historical patterns across cycles; REFLECT phase queries and generates config diff proposals
- **Evaluation**: `service/evaluator.py` runs LLM-as-judge on DISCOVER, PLAN, and REVIEW outputs; results stream to Phoenix UI via OTel spans. Context-aware — the evaluator extracts project domain from the spec before scoring. Graceful degradation: eval failures never block the workflow.
- **Deployment**: Single Docker Compose stack (`loop` container = orchestrator + frontend + nginx)

---

## Configuration

Three-tier priority: **Environment Variables** > **`config/config.yaml`** > **Built-in Defaults**.

All external parameters are centralized — zero hardcoded URLs, ports, or paths in production code.

```yaml
paths:
  project_name: test_discover_fix
  workspace_dir: ./output
  skills_dir: skills
  storage_dir: ./storage
  guardrails_path: ./config/guardrails.yaml

services:
  llm:
    base_url: http://host.docker.internal:8080/v1
    model: Qwen3.6-27B
  chroma:
    url: http://chromadb:8000
  loop_api:
    url: http://localhost:8011
  product:
    url: http://localhost:8010

workflow:
  hil_mode: auto
  max_retries: 2
  auto_approve: false

superweb:
  mode: agent
  openhands_url: http://openhands:8000
  openhands_port: 3005
  agent_conversations: 3
  agent_timeout_seconds: 3600
```

---

## Dependencies

```
langgraph, langchain-core, langgraph-checkpoint, langgraph-sdk
pydantic, pyyaml, httpx, aiohttp
chromadb (pattern storage)
opentelemetry-api, opentelemetry-sdk, arize-phoenix (observability + evaluation)
uvicorn, fastapi (web UI)
superweb-testing (UAT — agent mode: OpenHands, scripted: Playwright)
```

Install: baked into Docker image via `docker compose up -d --build`.

---

## Evaluation

At phase-completion, `service/evaluator.py` runs LLM-as-judge on phase outputs. Each evaluation is context-aware — the LLM first extracts the project's domain from the spec, then scores against criteria tailored to that context. Results stream to the Phoenix UI at `localhost:6006` via OTel span attributes.

### Evaluators

| Evaluator | Phase | Dimensions |
|---|---|---|
| `spec_quality` | DISCOVER | `domain_fit`, `clarity`, `completeness`, `consistency`, `actionability` |
| `plan_score` | PLAN | `coverage`, `actionability`, `architecture`, `risk`, `domain_fit` |
| `review_score` | ARCH_REVIEW | `thoroughness`, `specificity`, `actionability`, `severity`, `domain_fit` |
| `build_score` | BUILD | `code_quality`, `test_coverage`, `security_posture`, `maintainability` |
| `ship_score` | SHIP | `config_completeness`, `resilience`, `observability`, `security_hardening` |

### How It Works

1. Phase completes → `_run_phase_eval()` called in `graph/executor.py`
2. Evaluator sends context + output to LLM (`Qwen3.6-27B`)
3. LLM returns scores (0.0–1.0) with rationale
4. Results attached as OTel span attributes → Phoenix UI at `:6006`

Evaluations are **non-blocking** — if the LLM is unreachable or the eval times out, the workflow continues. Each eval adds ~3s per phase.

---

## Guardrails

Security-sensitive keywords (`auth`, `payment`, `billing`, `credential`, `secret`, `api_key`, `token`, etc.) trigger human approval. See `config/guardrails.yaml` for full thresholds and feedback rules.

Quality thresholds enforced per phase:

| Threshold | Default | Phase |
|---|---|---|
| `min_spec_confidence` | ≥ 0.9 | DEFINE |
| `max_arch_uncertainty` | ≤ 0.8 | PLAN |
| `max_security_findings` | 0 | BUILD |
| `max_review_revisions` | ≤ 2 | BUILD |
| `min_uat_pass_rate` | ≥ 0.95 | VERIFY |
| `max_latency_ms` | ≤ 500 | VERIFY (perf) |
| `max_test_flakiness_rate` | ≤ 0.1 | VERIFY (debug) |