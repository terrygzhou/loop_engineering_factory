# Loop Factory — Agent Instructions

## Skill Loading

Before any coding task, load and follow:
```
skill_view(name='coding-principles')
```

When things break, load:
```
skill_view(name='systematic-debugging')
```

When tasks span 3+ files, load:
```
skill_view(name='subagent-driven-development')
```

## Project Layout

```
loop_factory/
├── main.py              # CLI entry (headless auto-approve)
├── api/                 # FastAPI backend (:8011) — schemas, middleware
├── frontend/            # Static frontend (nginx :80) + backend bridge
├── graph/               # LangGraph engine: state.py, nodes/, edges.py
├── config/              # Centralized config: config.yaml, bounds.yaml, bounds_loader.py
├── tools/               # LLM dispatch, skill loader, OTel instrumentor
├── service/             # Health check server (:8081), OTel instrumentor
├── builder/             # Remote BUILD phase worker (:8200)
├── skills/              # 37 SKILL.md — phase-specific skill chains
├── feedback/            # ChromaDB pattern storage & retrieval
├── log/                # Logging utilities
├── models/              # Data models
├── cron/               # Cron-driven task orchestration
├── data/               # Runtime data: config, feedback, skills
├── storage/             # Persistent storage: cycles, state
├── state/               # Workflow state persistence
├── output/              # Generated artifacts (deploy target)
├── plan/               # Integration plans (e.g. SuperWeb UAT)
├── specs/               # Feature specifications
├── tests/               # Test suite: api/, e2e/, models/, service/
├── scripts/             # Utility scripts
├── docker-compose.yml  # Full stack (loop, chromadb, otel, phoenix, openhands, etc.)
├── Dockerfile           # Loop container image
├── entrypoint.sh        # Container startup script
├── config.yaml          # Legacy root-level config (use config/config.yaml)
├── requirements.txt     # Python dependencies
├── README.md            # Full documentation
├── architecture.html    # Architecture diagram (HTML)
├── image.png            # UI dashboard screenshot
└── langgraph-state-machine.md  # State machine reference
```

## Key Constraints

- **Docker compose**: `docker compose up -d --build loop` (single container = orchestrator + frontend + nginx)
- **No PostgreSQL** — pattern storage via ChromaDB (internal only, no host port)
- **Entry points**: CLI (`main.py`) auto-approves; Web UI (`api/` FastAPI :8011) with auto-approve on timeout
- **Ports**: nginx :80 (static frontend), FastAPI :8011 (API), health :8081, builder :8200
- **LLM**: `LLM_BASE_URL=http://172.25.0.1:8080/v1` (vLLM Qwen3.6-27B on host)
- **Artifacts**: generated projects land in `output/`
- **Skills**: 37 SKILL.md files in `skills/`; loaded by `tools/loader.py`
- **HIL flow**: Mandatory — OOTB `interrupt()` inside nodes. DISCOVER (2 pauses: setup + interview), ARCH_REVIEW (1 pause: architecture review gate). Graph-level `interrupt_after=[]`; HIL is node-level. `auto_approve=true` in config bypasses HIL for headless runs.
