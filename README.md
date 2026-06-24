# Loop Engineering

Self-improving AI-driven software development engine built on LangGraph.

```
DISCOVER → DEFINE → REVIEW → PLAN → BUILD → SEED_DATA → VERIFY → SHIP → REFLECT
```

Each cycle runs through these phases with quality gates, HIL (Human-in-the-Loop) review gates, and self-improvement via ChromaDB pattern storage. CLI and Web UI share the same `WorkflowRunner` — identical node execution, different UX layers.

## Architecture

```
┌──────────┐     ┌────────────┐     ┌───────────┐
│    CLI    │────▶│ LangGraph  │────▶│  Skills   │
│  (main.py)│     │ Executor   │     │  (23 SKILL.md)│
└──────────┘     └─────┬──────┘     └───────────┘
                        │
┌──────────┐             │         ┌──────────────┐
│  Web UI  │◀────────────┘         │   Feedback   │
│ (FastAPI)│    WebSocket          │  Aggregator  │
└──────────┘                        └──────┬───────┘
                                           │
                                      ┌──────────────┐
                                      │  ChromaDB    │
                                      │  (Patterns)  │
                                      └──────────────┘
```

## Quick Start

### Prerequisites

- **Python 3.12+**
- **Docker** + **Docker Compose**
- **LLM endpoint** (OpenAI-compatible, e.g., vLLM on `http://localhost:8080/v1`)

### Option A: CLI (host Python)

```bash
cd <project_root>
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start ChromaDB for pattern storage (optional but recommended)
docker run -d --name chromadb-main -p 8000:8000 -v chroma_data:/chroma/chroma chromadb/chroma:latest

# Run workflow
python3 main.py --project my_project --spec "Your project description"
```

### Option B: Docker Compose (all-in-one)

```bash
docker compose up -d --build
```

Runs ChromaDB (port 8000) and the orchestrator container. The LLM endpoint is external.

### Option C: Web UI

```bash
cd frontend && docker compose up -d --build
```

Open `http://localhost:8011`. Progress streams via WebSocket with quality gates dashboard and phase details.

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

1. **DISCOVER** — Scans existing codebase for context, tech stack, and requirements (no LLM calls)
2. **DEFINE** — Structured interview → specification → API contract design
3. **REVIEW** — Human-in-the-Loop gate: inspect spec, API contract, and interview notes before proceeding
4. **PLAN** — Architecture design, task breakdown, analysis, and checklist generation
5. **BUILD** — Iterative code generation with review gates (max 2 retries per cycle)
6. **SEED_DATA** — Test data and fixture generation
7. **VERIFY** — Browser-level UAT (Playwright desktop+mobile), performance, and quality gates
8. **SHIP** — Deployment packaging, observability, and Docker Compose preparation
9. **REFLECT** — Cycle analysis, pattern storage to ChromaDB, and self-improvement proposals

### Skills System

Each node chains skills from `skills/` (23 available). A skill is skipped if missing — the pipeline continues with whatever artifacts were produced.

| Phase | Skills Chained |
|---|---|
| DISCOVER | Filesystem/git/docker scans (no LLM) |
| DEFINE | `interview-me` → `speckit-specify` → `api-and-interface-design` |
| PLAN | `writing-plans` → `speckit-tasks` → `speckit-analyze` → `doubt-driven-development` → `speckit-checklist` |
| BUILD | `incremental-implementation` → `fastapi-jinja2-feature-build` → `test-driven-development` → `security-and-hardening` → `requesting-code-review` |
| SEED_DATA | `ai-workflow-data-seeding` |
| VERIFY | `uat-workflow` → `performance-optimization` (if slow) → `systematic-debugging` (if flaky) |
| SHIP | `observability-and-instrumentation` → `shipping-and-launch` → `docker-compose-deployment` → `git-workflow` |
| REFLECT | Internal diff_engine → `git-workflow` (human approval gate) |

**Total per cycle**: ~20–35 LLM calls. BUILD loops (up to 2 retries) can increase this.

### Quality Gates

Thresholds from `config/guardrails.yaml`:

| Phase | Gate |
|---|---|
| DEFINE | `spec_confidence ≥ 0.9` or loop back |
| PLAN | `arch_uncertainty ≤ 0.8` or loop back |
| BUILD | `security_findings = 0`, `review_revisions ≤ 2`, Docker builds, health check, pytest — or loop back |
| SEED_DATA | `seed_errors` is empty or loop back to BUILD |
| VERIFY | `uat_pass_rate ≥ 0.95` or loop back to BUILD |
| REFLECT | Human approval required for config changes |

### Self-Improvement Loop

After SHIP, REFLECT:
1. Aggregates cycle metrics and feedback
2. Queries ChromaDB for historical patterns
3. Meta-agent generates proposed skill config diffs
4. Dry-run validation against guardrails
5. Human approval gate (CLI or Web UI)
6. Approved changes committed via `git-workflow`

Low-risk changes (confidence ≥ 0.95, zero security findings) can auto-apply.

## Project Structure

```
loop_engineering/
├── main.py                    # CLI entry point
├── config/
│   ├── config.yaml           # Three-tier config (env > YAML > defaults)
│   ├── loader.py            # Config resolution
│   ├── guardrails.yaml       # Quality thresholds
│   └── guardrails.py         # Runtime threshold loader
├── graph/
│   ├── main.py               # LangGraph construction
│   ├── executor.py          # Shared WorkflowRunner (CLI + Web UI)
│   ├── state.py             # WorkflowState + CycleMetrics
│   ├── edges.py             # Conditional routing
│   └── nodes/                # DISCOVER, DEFINE, REVIEW, PLAN, BUILD, SEED_DATA, VERIFY, SHIP, REFLECT
│       └── review_contract.py  # Shared HIL contract (CLI & Web UI parity)
├── feedback/
│   ├── aggregator.py        # Cycle recording, ChromaDB queries
│   ├── chroma_client.py     # Pattern embeddings, similarity search
│   └── diff_engine.py       # Config diff generation
├── tools/
│   ├── llm.py               # LLM invocation with skill injection
│   └── loader.py           # Skill registry builder
├── skills/                   # 23 SKILL.md files (one per skill)
├── frontend/                 # Web UI (FastAPI + nginx + uvicorn)
│   ├── backend/            # FastAPI app, WebSocket streaming, workflow bridge
│   └── static/             # HTML/CSS/JS frontend
├── storage/cycles/         # Persistent cycle data
├── specs/                   # Example specs from the workflow
├── docker-compose.yml       # All-in-one: ChromaDB + orchestrator
├── Dockerfile               # CLI orchestrator image
└── requirements.txt        # Python dependencies
```

## Configuration

Three-tier priority: **Environment Variables** > **`config/config.yaml`** > **Built-in Defaults**.

Key settings in `config.yaml`:
```yaml
paths:
  project_name: my_crm
  workspace_dir: ~/workspace/projects
  project_path: '{{project_name}}'
  skills_dir: skills
  storage_dir: ./storage

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
langgraph, langchain-core, langchain-openai, langgraph-checkpoint
pydantic, pyyaml, typer, rich, chromadb, httpx
```

Install: `pip install -r requirements.txt` (CLI mode) or baked into Docker image (Docker mode).

## Example Runs

```bash
# Interactive CLI (prompts for name and spec)
python3 main.py

# Auto-approve with inline spec
python3 main.py --project myapp --spec "Build a REST API" --auto-approve

# Scan existing codebase
python3 main.py --project myapp --context ./existing_code
```

## Guardrails

Security-sensitive keywords (`auth`, `payment`, `billing`, `credential`, `secret`, etc.) trigger human approval. See `config/guardrails.yaml` for full thresholds and feedback rules.
