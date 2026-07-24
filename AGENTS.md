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


## Key Constraints

- **Docker compose**: `docker compose up -d --build loop` (single container = orchestrator + frontend + nginx)
- **No PostgreSQL** — pattern storage via ChromaDB (internal only, no host port)
- **Entry points**: CLI (`main.py`) auto-approves; Web UI (`api/` FastAPI :8011) with auto-approve on timeout
- **Ports**: nginx :80 (static frontend), FastAPI :8011 (API), health :8081, builder :8200
- **LLM**: `LLM_BASE_URL=http://172.25.0.1:8080/v1` (vLLM Qwen3.6-27B on host)
- **Artifacts**: generated projects land in `output/`
- **Skills**: 37 SKILL.md files in `skills/`; loaded by `tools/loader.py`
- **HIL flow**: Mandatory — OOTB `interrupt()` inside nodes. DISCOVER (2 pauses: setup + interview), ARCH_REVIEW (1 pause: architecture review gate). Graph-level `interrupt_after=[]`; HIL is node-level. `auto_approve=true` in config bypasses HIL for headless runs.
