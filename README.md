# Loop Engineering

Self-improving AI-driven software development engine built on LangGraph.

```
DISCOVER → DEFINE → PLAN → ARCH_REVIEW → BUILD → SEED_DATA → VERIFY → SHIP → REFLECT
```




Each cycle runs through these phases with quality gates, HIL (Human-in-the-Loop) review gates, and self-improvement via ChromaDB pattern storage. CLI and Web UI share the same `WorkflowRunner` — identical node execution, different UX layers.



## Architecture

![Loop Engineering Architecture](architecture.png)

### Data Flow

| Component | Connects To | Description |
|-----------|-------------|------------|
| CLI → API Gateway → LangGraph | Workflow Execution | Headless workflow execution |
| HIL Frontend ↔ LangGraph | Human Review | Interrupt/resume for ARCH_REVIEW |
| Phase Nodes → Tools | Skill Invocation | LLM-driven code generation |
| Feedback → ChromaDB | Pattern Storage | Self-improvement loop |

### Quality Gates

| Gate | Condition | Outcome |
|------|-----------|---------|
| ARCH_REVIEW | Approved | → BUILD |
| ARCH_REVIEW | Rejected | → DEFINE |
| BUILD | Pass | → SEED_DATA |
| BUILD | Fail | → PLAN |
| VERIFY | Pass | → SHIP |
| VERIFY | Fail | → BUILD |
## Data Flow

| Component | Connects To | Description |
|-----------|-------------|------------|
| CLI → API Gateway → LangGraph | Workflow Execution | Headless workflow execution |
| HIL Frontend ↔ LangGraph | Human Review | Interrupt/resume for ARCH_REVIEW |
| Phase Nodes → Tools | Skill Invocation | LLM-driven code generation |
| Feedback → ChromaDB | Pattern Storage | Self-improvement loop |

### Quality Gates

| Gate | Condition | Outcome |
|------|-----------|---------|
| ARCH_REVIEW | Approved | → BUILD |
| ARCH_REVIEW | Rejected | → DEFINE |
| BUILD | Pass | → SEED_DATA |
| BUILD | Fail | → PLAN |
| VERIFY | Pass | → SHIP |
| VERIFY | Fail | → BUILD |
## Key Components

- **Entry Points**: CLI (`main.py`) for headless auto-approve, or Web UI (FastAPI `:8011`) for HIL workflow
- **LangGraph Engine**: `StateGraph` with 10 phase nodes, conditional routing via quality gates, OOTB `interrupt_after` for HIL pauses
- **Skills System**: 27 `SKILL.md` files loaded by `tools/loader.py`, invoked via `tools/llm.py` with context optimization
- **HIL Bridge**: SSE event streaming between LangGraph executor and frontend; supports double-pause DISCOVER interview and ARCH_REVIEW diagram approval
- **Feedback Loop**: ChromaDB stores historical patterns across cycles; REFLECT phase queries and generates config diff proposals
- **Deployment**: Single Docker Compose stack (`loop` container = orchestrator + frontend + nginx)

## Quick Start

### Prerequisites

- **Docker** + **Docker Compose**
- **LLM endpoint** (OpenAI-compatible, e.g., vLLM on `http://localhost:8080/v1`)

### Option A: CLI (headless, auto-approve)

```bash
docker compose up -d --build
```

Runs the orchestrator in auto-approve mode. DISCOVER generates default interview notes from the spec.

### Option B: Web UI (HIL)

```bash
docker compose up -d --build loop
```

Open `http://localhost:8011`. Progress streams via Server-Sent Events (SSE) with quality gates dashboard, phase details, and Mermaid diagram rendering at ARCH_REVIEW gates.

### LLM Configuration

```bash
# Local vLLM
export LLM_BASE_URL="http://localhost:8080/v1"
export LLM_MODEL="qwen3.6-27b"

# OpenAI
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-4o"
export OPENAI_API_KEY="sk-..."
```

> ⚠️ **Token Usage**: A full cycle makes 20–35 LLM calls. Monitor your provider's usage dashboard during long runs.

## How It Works

### Pipeline Phases

1. **DISCOVER** — HIL interview node using LangGraph OOTB `interrupt()`. Double-pause: first for project setup (name + description), then for interview questions (9 structured questions). Scans existing codebases for context. Generates `requirement.md`. In Web UI mode, pauses for user input via SSE. In auto-approve mode, generates defaults.

2. **DEFINE** — Generates a structured specification via `speckit-specify`, then produces an API contract via `api-and-interface-design`. Fully automatic — interview data collected in DISCOVER. Incorporates user review feedback if returning from ARCH_REVIEW rejection.

3. **PLAN** — Architecture and task planning: `writing-plans` → `speckit-tasks` → `speckit-analyze` → `doubt-driven-development` → `speckit-checklist`. Generates architecture diagrams via `architecture-diagram-generator`. Diagrams are stored as `plan.md` and `diagrams.md` in the project output folder.

4. **ARCH_REVIEW** — HIL gate: pauses execution so the user can review the specification, plan, and architecture diagrams before BUILD begins. Web UI renders Mermaid diagrams client-side with tabbed diagram viewer. User can approve (proceeds to BUILD) or reject with feedback (loops back to DEFINE). Max 2 retries before forced progression.

5. **BUILD** — Iterative code generation per task item: `incremental-implementation` → `test-driven-development` (per item). Final aggregate passes: `security-and-hardening` (STRIDE model) → `requesting-code-review`. Runs Docker Compose build, health check, and pytest. Max 2 retries per cycle.

6. **SEED_DATA** — Test data and fixture generation via `ai-workflow-data-seeding`. Executes seed script inside the running Docker container.

7. **VERIFY** — Comprehensive validation: `uat-workflow` (Playwright) mandatory. Conditional passes: `performance-optimization` (if P95 latency > 500 ms) → `systematic-debugging` (if flakiness > 10%) → `code-simplification` (if review revisions exceed threshold).

8. **SHIP** — Deployment packaging: `observability-and-instrumentation` → `shipping-and-launch` → `docker-compose-deployment` (if BUILD did not deploy) → `git-workflow` (version tag).

9. **REFLECT** — Cycle analysis: aggregates metrics and feedback, queries ChromaDB for historical patterns, meta-agent generates proposed config/guardrail diffs, dry-run validation, human approval gate for changes. Approved changes committed via `git-workflow`.

### Skills System

Each node chains skills from `skills/` (27 currently registered). A skill is skipped if missing — the pipeline continues with whatever artifacts were produced.

| Phase | Skills Chained |
|---|---|
| DISCOVER | `interview-me` → Fabric Prompt Engineering → codebase scan (filesystem/git/docker) |
| DEFINE | `speckit-specify` → `api-and-interface-design` |
| PLAN | `writing-plans` → `speckit-tasks` → `speckit-analyze` → `doubt-driven-development` → `speckit-checklist` → `architecture-diagram-generator` |
| ARCH_REVIEW | HIL gate (human reviews spec + plan + Mermaid diagrams — no skills called) |
| BUILD | `incremental-implementation` → `test-driven-development` (per task item) → `security-and-hardening` → `requesting-code-review` (aggregate) |
| SEED_DATA | `ai-workflow-data-seeding` |
| VERIFY | `uat-workflow` (mandatory) → `performance-optimization` (if slow) → `systematic-debugging` (if flaky) → `code-simplification` (if high revision count) |
| SHIP | `observability-and-instrumentation` → `shipping-and-launch` → `docker-compose-deployment` → `git-workflow` |
| REFLECT | Internal `diff_engine` + meta-agent → `git-workflow` (commit approved diffs) |

**Total per cycle**: ~20–35 LLM calls. BUILD loops (up to 2 retries) can increase this.

### Quality Gates

Thresholds from `config/guardrails.yaml`:

| Phase | Gate |
|---|---|
| DISCOVER | HIL required in Web UI mode; auto-generates defaults in auto-approve mode |
| DEFINE | `spec_confidence ≥ 0.9` or loop back |
| PLAN | `arch_uncertainty ≤ 0.8` or loop back |
| BUILD | `security_findings = 0`, `review_revisions ≤ 2`, Docker build + health check + pytest pass — or loop back |
| SEED_DATA | `seed_errors` is empty or loop back to BUILD |
| VERIFY | `uat_pass_rate ≥ 0.95` or loop back to BUILD |
| REFLECT | Human approval required for config changes (auto-apply low-risk when confidence ≥ 0.95) |

### Self-Improvement Loop

After SHIP, REFLECT:
1. Aggregates cycle metrics and feedback
2. Queries ChromaDB for historical patterns
3. Meta-agent generates proposed skill/config/guardrail diffs
4. Dry-run validation against guardrails
5. Human approval gate (Web UI)
6. Approved changes committed via `git-workflow`

Low-risk changes (confidence ≥ 0.95, zero security findings) can auto-apply.



## Configuration

Three-tier priority: **Environment Variables** > **`config/config.yaml`** > **Built-in Defaults**.

Key settings in `config.yaml`:
```yaml
paths:
  project_name: test_discover_fix
  workspace_dir: ~/your_path/projects
  project_path: '{{project_name}}'
  skills_dir: skills
  storage_dir: ./storage
  guardrails_path: ./config/guardrails.yaml

workflow:
  hil_mode: auto
  max_retries: 2
  auto_approve: false
```

LLM settings in `config/guardrails.yaml`:
```yaml
llm:
  model: Qwen3.6-27B
  base_url: ${LLM_BASE_URL:-http://localhost:8080/v1}
  temperature: 0.1
  max_retries: 3
```

## Dependencies

```
langgraph, langchain-core, langgraph-checkpoint, langgraph-sdk
pydantic, pyyaml, httpx, aiohttp
chromadb (pattern storage)
opentelemetry-api, opentelemetry-sdk (observability)
```

Install: baked into Docker image via `docker compose up -d --build`.

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
