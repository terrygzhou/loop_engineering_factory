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

    %% Conditional edges (graph/edges.py route_phase)
    ARCH_REVIEW --> BUILD : approved
    ARCH_REVIEW --> PLAN : rejected

    BUILD --> SEED_DATA : gates pass
    BUILD --> BUILD : security / revisions / UAT gate failed
    BUILD --> REFLECT : 3 consecutive build failures

    %% HIL interrupt points (in-node interrupt())
    note right of DISCOVER : interrupt() x2<br/>project_setup + interview
    note right of ARCH_REVIEW : interrupt() x1<br/>human approve/reject

    classDef hil fill:#FFD700,stroke:#B8860B,stroke-width:2px,color:#000
    classDef gate fill:#87CEEB,stroke:#4682B4,stroke-width:2px,color:#000
    classDef normal fill:#F0F0F0,stroke:#999,stroke-width:1px,color:#000
    class DISCOVER,ARCH_REVIEW hil
    class DEFINE,PLAN,BUILD,SHIP gate
    class SEED_DATA,VERIFY,REFLECT normal
```

#### BUILD Phase: OpenHands Agent Delegation

The BUILD node delegates to the OpenHands agent-server via the Gateway API (OpenAI-compatible). Falls back to inline build logic if the agent-server is unreachable.

```mermaid
graph LR
    START([START]) --> OH_CHECK["OpenHands health<br/>check"]

    OH_CHECK -->|healthy| CREATE_CONV["Create conversation<br/>POST /v1/chat/completions"]
    OH_CHECK -->|unhealthy| INLINE["Inline fallback<br/>build logic"]

    CREATE_CONV --> POLL["Poll conversation<br/>GET /api/conversations/{id}"]
    POLL -->|finished| PARSE["Parse assistant text"]
    POLL -->|timeout| INLINE

    PARSE --> WRITE_FILES["Write files to disk"]
    WRITE_FILES --> GATE["Quality gates<br/>Security + UAT + Review"]
    GATE -->|pass| END([END])
    GATE -->|fail| START

    INLINE --> INLINE_BUILD["Incremental implementation<br/>per task from backlog"]
    INLINE_BUILD --> GATE

    classDef agent fill:#90EE90,stroke:#2E8B57,stroke-width:2px,color:#000
    classDef fallback fill:#FF9800,stroke:#E65100,stroke-width:1px,color:#000
    classDef node fill:#2196F3,stroke:#1565C0,stroke-width:1px,color:#fff
    classDef gate fill:#87CEEB,stroke:#4682B4,stroke-width:2px,color:#000
    class OH_CHECK,CREATE_CONV,POLL,PARSE,WRITE_FILES node
    class INLINE,INLINE_BUILD fallback
    class GATE gate
```

| Step | Implementation | Notes |
|------|---------------|-------|
| Health check | `GET /health` | Falls back to inline build on any failure |
| Create conversation | `POST /v1/chat/completions` | Profile `build_agent` created idempotently |
| Poll | `GET /api/conversations/{id}` | 5s interval, 1h timeout |
| Parse | Regex → file blocks + test results | Derives `build_status`: pass/partial/fail |
| Write files | Disk I/O to `project_path` | Downstream phases (SEED_DATA, VERIFY) read from disk |
| Quality gates | `route_phase()` in `edges.py` | Security findings, UAT pass rate, review revisions |
| Inline fallback | Direct implementation in `openhands_build.py` | Full per-task incremental implementation pipeline |

**Outer graph routing** (from `edges.py`): All conditional routing via `route_phase()` — no unconditional edges from BUILD, SHIP, or REFLECT. BUILD self-loops if `security_findings > 0`, `review_revisions > max`, or `uat_pass_rate < min`. After 3 consecutive build failures, routes to `REFLECT` to skip `SEED_DATA`/`VERIFY`/`SHIP`.

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
            CLI["CLI<br/>(main.py)"]
            WebUI["Web UI<br/>(FastAPI :8011)"]
            Nginx["nginx<br/>(:80)"]
        end

        subgraph Engine["LangGraph Engine"]
            Graph["StateGraph<br/>9 Phases"]
            Nodes["Phase Nodes<br/>g/nodes/*.py"]
            Bridge["HIL Bridge<br/>Command(resume)"]
            BuildProxy["BUILD proxy<br/>openhands_build.py"]
            Router["Router<br/>edges.py route_phase()"]
        end

        subgraph Tools["Tool Layer"]
            LLM["LLM Tool<br/>(tools/llm.py)"]
            Skills["Skill Loader<br/>(35 SKILL.md)"]
            ChromaC["ChromaDB Client<br/>(feedback/)"]
        end
    end

    subgraph External["External Services"]
        LLM_Srv["LLM Server<br/>(SGLang :8080)"]
        Docker["Docker Engine"]
        Chroma["ChromaDB :8000<br/>(internal)"]
        OpenHands["OpenHands<br/>(:3005)<br/>Agent Server"]
        Builder["DELETED<br/>OpenHands Gateway replaces remote builder"]
    end

    U -->|browser| WebUI
    U -->|terminal| CLI
    CLI -->|stream| Graph
    WebUI -->|SSE| Bridge
    Bridge --> Graph
    Graph --> Nodes
    Graph --> Router
    Router --> Nodes
    Nodes --> LLM
    LLM --> Skills
    LLM --> ChromaC
    LLM -->|"POST /v1/chat/completions"| LLM_Srv
    Graph -->|"build & deploy"| Docker
    ChromaC <--> Chroma
    WebUI --> Nginx

    %% BUILD: OpenHands agent delegation with inline fallback
    Nodes -->|"BUILD"| BuildProxy
    BuildProxy -->|"agent mode"| OpenHands
    BuildProxy -->|"inline fallback"| Docker

    classDef default fill:#F0F0F0,stroke:#999,stroke-width:1px,color:#000
    classDef hil fill:#FFD700,stroke:#B8860B,stroke-width:2px,color:#000
    classDef agent fill:#90EE90,stroke:#2E8B57,stroke-width:2px,color:#000
    classDef router fill:#87CEEB,stroke:#4682B4,stroke-width:2px,color:#000
    class BuildProxy agent
    class OpenHands,Builder external
    class Router router
```

### Deployment Architecture

```mermaid
graph TB
    U[("User")]

    subgraph Host["Host Machine"]
        LLM_C[("LLM Server<br/>SGLang :8080")]

        subgraph DockerStack["Docker Compose Stack"]
            LC[("Loop Container<br/>:80 / :8011 / :8081")]
            BLD["DELETED<br/>OpenHands Gateway replaces remote builder"]
            CC[("ChromaDB<br/>:8000 internal")]
            OC[("OTel Collector<br/>:4318")]
            PH[("Phoenix<br/>:6006")]
            OH[("OpenHands<br/>:3005")]
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
| `frontend/backend/app.py` | FastAPI backend — workflow API :8011 | `services.loop_api.*` |
| `frontend/backend/workflow_bridge.py` | SSE event bridge + HIL interrupt handling | `services.product.*` |
| `graph/main.py` | LangGraph StateGraph definition | `workflow.hil_mode` |
| `graph/edges.py` | Conditional routing via `route_phase()` — quality gates, loop limits, forward paths | N/A |
| `graph/nodes/*.py` | Phase node implementations (9 nodes) | `paths.*` |
| `graph/state.py` | WorkflowState (37 fields) + CycleMetrics (11 fields) — pruned for token efficiency | N/A |
| `graph/executor.py` | WorkflowRunner — orchestrates graph execution with HIL pauses | N/A |
| `tools/llm.py` | LLM call dispatch with retry & context compression | `services.llm.*` |
| `tools/loader.py` | Skill registry discovery & hot-reload | `workflow.skill_registry_path` |
| `feedback/chroma_client.py` | ChromaDB pattern storage/retrieval | `services.chroma.*` |
| `service/otel_instrumentor.py` | OpenTelemetry trace export | `services.otel.*` |
| `service/evaluator.py` | LLM-as-judge evaluator — context-aware phase scoring → Phoenix UI | `services.otel.*`, `services.llm.*` |
| `service/health.py` | Health check server + dependency verification | `services.observability.*` |
| `config/loader.py` | Three-tier config: `ENV > YAML > default` | N/A (meta) |

---

## Skills Per Workflow State

Each workflow phase chains specialized skills from `skills/` (35 registered). Skills are `SKILL.md` files — context templates that the LLM follows to produce specific outputs. A missing skill is silently skipped.

### Phase-Specific Skill Chains

| Phase | Skills Chained | Purpose |
|-------|----------------|---------|
| **DISCOVER** | `fabric-prompts` (requirement generation) → `interview-me` (HIL interrupt) → `coding-principles` (context refinement) | Auto-generates `requirement.md` via Fabric. Structured 9-question interview. Scans existing codebases. |
| **DEFINE** | `spec-driven-development` (spec) → `source-driven-development` + `api-and-interface-design` (parallel) | Generates structured specification. Parallel LLM calls for source analysis and API contract via `asyncio.gather()`. |
| **PLAN** | `planning-and-task-breakdown` → `doubt-driven-development` → `architecture-diagram-generator` (4 diagrams in parallel) | Implementation plan, architectural doubt resolution, and 4 parallel diagram generations. |
| **ARCH_REVIEW** | _(human gate — no skills called)_ | User reviews spec, plan, and Mermaid diagrams. Approve → BUILD, Reject → PLAN. |
| **BUILD** | `incremental-implementation` → `test-driven-development` (per task) → **deploy_gate** (health check) → OpenHands Agent UAT (`agent` mode default) → `security-and-hardening` → `requesting-code-review` → **SECURITY_GATE** | Per-task code gen with TDD (legacy subgraph). Docker build + health check. BUILD phase: OpenHands agent delegation via Gateway API. SECURITY_GATE: aggregate STRIDE security audit + code quality review. |
| **SEED_DATA** | `ai-workflow-data-seeding` | Test data generation. Executes seed scripts inside Docker containers. |
| **VERIFY** | _(placeholder — pass-through to SHIP)_ | Currently a pass-through node. UAT moved to BUILD subgraph. Future: real test execution, linting, security scans, and performance profiling. |
| **SHIP** | `observability-and-instrumentation` → `shipping-and-launch` → `production-deployment` → `git-workflow` | Deployment packaging: observability setup, launch checklist, cloud platform configuration (AWS/Azure/GCP), version tagging. |
| **REFLECT** | Self-improvement via ChromaDB pattern storage | Aggregates cycle metrics, queries historical patterns, generates config/guardrail diff proposals for next cycle. |

### Local Skills Registry (35 skills)

```
skills/
├── ai-workflow-data-seeding/SKILL.md             # SEED_DATA phase
├── api-and-interface-design/SKILL.md              # DEFINE phase
├── architecture-diagram-generator/SKILL.md        # PLAN phase
├── browser-testing-with-devtools/SKILL.md         # Standalone
├── ci-cd-and-automation/SKILL.md                  # Standalone
├── code-review-and-quality/SKILL.md               # BUILD phase (quality)
├── code-simplification/SKILL.md                   # Standalone (future VERIFY)
├── coding-principles/SKILL.md                     # DISCOVER phase (context refinement)
├── context-engineering/SKILL.md                   # Standalone
├── debugging-and-error-recovery/SKILL.md          # Standalone
├── deprecation-and-migration/SKILL.md             # Standalone
├── docker-compose-deployment/SKILL.md             # Standalone (local dev reference)
├── documentation-and-adrs/SKILL.md                # Standalone
├── doubt-driven-development/SKILL.md              # PLAN phase
├── fabric-prompts/SKILL.md                        # DISCOVER phase (prompt optimization)
├── frontend-ui-engineering/SKILL.md               # Standalone
├── git-workflow/SKILL.md                          # SHIP + REFLECT phases
├── git-workflow-and-versioning/SKILL.md           # Standalone
├── idea-refine/SKILL.md                           # DISCOVER phase
├── incremental-implementation/SKILL.md            # BUILD phase
├── interview-me/SKILL.md                          # DISCOVER phase (HIL)
├── observability-and-instrumentation/SKILL.md     # SHIP phase
├── performance-optimization/SKILL.md              # Standalone (future VERIFY)
├── planning-and-task-breakdown/SKILL.md           # PLAN phase
├── production-deployment/SKILL.md                 # SHIP phase
├── requesting-code-review/SKILL.md                # BUILD phase (SECURITY_GATE)
├── security-and-hardening/SKILL.md                # BUILD phase (SECURITY_GATE)
├── shipping-and-launch/SKILL.md                   # SHIP phase
├── source-driven-development/SKILL.md             # DEFINE phase (parallel)
├── spec-driven-development/SKILL.md               # DEFINE phase (parallel)
├── systematic-debugging/SKILL.md                  # Standalone (future VERIFY)
├── test-driven-development/SKILL.md               # BUILD phase
├── uat-workflow/SKILL.md                          # BUILD phase (fallback)
├── using-agent-skills/SKILL.md                    # Standalone
└── writing-plans/SKILL.md                         # DEFINE + PLAN phases
```

**Total per cycle**: ~25–40 LLM calls (parallel calls in DEFINE and PLAN phases). BUILD loops (up to 2 retries) can increase this.

---

## How to Run It Locally

### Prerequisites

- **Docker** + **Docker Compose** (v2.20+)
- **LLM endpoint** (OpenAI-compatible, e.g., SGLang Qwen3.6-27B on `:8080`)

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
| `promtail` | _(internal)_ | Log aggregation |
| `openhands` | :3005 | OpenHands Agent Server — BUILD delegation |

> **Note**: Prometheus and Grafana run as a separate Grafana stack on the host (`~/.hermes/grafana-stack/`), not in this Docker Compose file.

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

> ⚠️ **Token Usage**: A full cycle makes ~25–40 LLM calls (with parallel calls in DEFINE and PLAN). Monitor your provider's usage dashboard during long runs.

---

## Key Components

- **Entry Points**: CLI (`main.py`) for headless auto-approve, or Web UI (FastAPI `:8011`) for HIL workflow
- **LangGraph Engine**: `StateGraph` with 9 phase nodes, conditional routing via `route_phase()` in `edges.py`, in-node `interrupt()` for HIL pauses
- **State Management**: `WorkflowState` (37 fields) + `CycleMetrics` (11 fields) — pruned for token efficiency. All keys initialized in `graph/executor.py`
- **Skills System**: 35 `SKILL.md` files loaded by `tools/loader.py`, invoked via `tools/llm.py` with context optimization
- **HIL Bridge**: SSE event streaming between LangGraph executor and frontend; uses in-node `interrupt()` calls for DISCOVER double-pause and ARCH_REVIEW approval
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
  openhands_port: 8000
  agent_conversations: 3
  agent_timeout_seconds: 3600
```

---

## Dependencies

```
langgraph, langchain-core, langgraph-checkpoint (workflow engine)
pydantic, pyyaml, httpx (core utilities)
chromadb (pattern storage)
opentelemetry-api, opentelemetry-sdk, arize-phoenix (observability + evaluation)
uvicorn, fastapi (web UI)
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

> All evaluators are non-blocking — eval failures never stop the workflow. `ship_score` exists in `service/evaluator.py` but is called at SHIP completion via `eval_ship()`.

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
| `min_uat_pass_rate` | ≥ 0.95 | BUILD (via quality gates) |
| `max_latency_ms` | ≤ 500 | VERIFY (perf — placeholder) |
| `max_test_flakiness_rate` | ≤ 0.1 | VERIFY (debug — placeholder) |
