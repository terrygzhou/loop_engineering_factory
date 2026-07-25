# LangGraph Architecture Audit

## Graph Topology

```
START → DISCOVER_SETUP → DISCOVER_INTERVIEW → DEFINE → PLAN → ARCH_REVIEW
          (HIL)            (HIL)                        ↕ (reject→PLAN)
                                                       ↓ (approve)
                                                      BUILD
                                                 ↻ self-loop (retry)
                                                       ↓ pass
                                                   SEED_DATA → VERIFY → SHIP
                                                                 ↓
                                                                REFLECT → END
```

**Key structural issue**: BUILD is wired as a single-node proxy to OpenHands agent-server, but the graph docstring still references a "build subgraph." It's a flat node with HTTP delegation, not an actual subgraph. SEED_DATA and VERIFY are placeholders with no real logic — they're pass-throughs that artificially reset metrics to "all passing."

---

## Phase-by-Phase Breakdown

### 1. DISCOVER_SETUP

| Field | Detail |
|-------|--------|
| **Input** | `state["project_name"]`, `state["project_description"]`, `state["context_folder"]`, `state["improve_mode"]` |
| **Output** | `{project_name, project_description, context_folder, project_folder, project_path, phase, next_phase, artifacts}` |
| **Skills** | `interview-me` |
| **What it does** | Collects project identity. If HIL: pauses for user to fill project name/description/context_folder. If auto-approve: uses defaults. If improve_mode: reads `storage/live.json` for existing deployment, overrides context_folder to deployed path. Creates `project_folder/specs/`, `build/`, `build/diagrams/` directories. |
| **Precondition** | None (first node in graph). `auto_approve` flag determines HIL behavior. |
| **Postcondition** | `state["project_name"]` set; project directories exist on disk. |
| **Observability** | AuditLog logs node input. No quality gate — always advances. |
| **Move-on criteria** | Always → `DISCOVER_INTERVIEW` (unconditional edge) |

### 2. DISCOVER_INTERVIEW

| Field | Detail |
|-------|--------|
| **Input** | `state["project_description"]`, `state["context_folder"]`, `state["artifacts"]["project_context"]` |
| **Output** | `{interview_notes, artifacts: {requirement_md, project_context}}` |
| **Skills** | `interview-me` |
| **What it does** | Two paths: (a) Greenfield: runs `interview-me` skill to generate interview questions → LLM produces `requirement.md`. (b) Existing codebase: scans project tree, routes, models, templates, dependencies, git status, Docker config → builds `project_context` JSON. For existing projects, skips interview HIL. Writes `requirement.md` to `project_folder/specs/`. |
| **Precondition** | `project_name` and `project_folder` set by SETUP. |
| **Postcondition** | `state["artifacts"]["interview_notes"]` populated; `requirement.md` on disk. |
| **Observability** | AuditLog node input/output. |
| **Move-on criteria** | Always → `DEFINE` (unconditional edge) |

### 3. DEFINE

| Field | Detail |
|-------|--------|
| **Input** | `artifacts[interview_notes]`, `artifacts[project_context]`, `user_review_comments` (from ARCH_REVIEW rejection), ChromaDB historical patterns |
| **Output** | `{artifacts: {spec_refined, api_contract, project_name}, phase, metrics[spec_confidence], next_phase}` |
| **Skills** | `writing-plans` → `api-and-interface-design` |
| **What it does** | 3-step pipeline: (1) Loads interview notes from DISCOVER (or project_description fallback). (2) Runs `writing-plans` skill with context (spec path + project context + interview notes + historical ChromaDB feedback) → generates `specification.md`. (3) Runs `api-and-interface-design` skill on spec → generates `api_contract.md`. Estimates `spec_confidence` score (0–1) from artifact quality (length, Gherkin keywords, error handling coverage). If spec_confidence < 0.9: increments loop counter via `_maybe_increment_loop()`. Writes all three files to `project_folder/specs/`. |
| **Precondition** | `project_name` and `interview_notes` (or description) available. |
| **Postcondition** | `specification.md`, `api_contract.md`, `interview_notes.md` on disk. `spec_confidence` computed. |
| **Observability** | AuditLog node input + file writes. `_estimate_spec_confidence()` checks: spec >100 chars (+0.3), API >50 chars (+0.2), interview >50 chars (+0.15), Gherkin keywords (+0.15), edge cases (+0.1), error handling (+0.1). |
| **Move-on criteria** | `spec_confidence >= 0.9` → PLAN. Otherwise self-loop to DEFINE (max 2 loops, then forced forward). |

### 4. PLAN

| Field | Detail |
|-------|--------|
| **Input** | `artifacts[spec_refined]`, `artifacts[interview_notes]`, `user_review_comments` (if rejected from ARCH_REVIEW), ChromaDB historical patterns |
| **Output** | `{artifacts: {plan, doubt_resolution, diagrams, diagram_pngs, solution_md, tasks, analysis, checklist}, phase, metrics[arch_uncertainty, task_count]}` |
| **Skills** | `writing-plans` → `doubt-driven-development` → architecture diagram generator (Mermaid) |
| **What it does** | 3-step pipeline: (1) `writing-plans` generates implementation plan with architecture, file structure, milestones, tasks (max 3000 words, context-optimized). (2) `doubt-driven-development` challenges plan — identifies top 3 risks. (3) Generates 4 Mermaid diagrams (component, sequence, data-flow, deployment) → converts to PNG via Playwright. Assembles `solution.md` combining all artifacts. Computes `arch_uncertainty` from doubt resolution quality. Writes to `project_folder/build/` and `build/diagrams/`. |
| **Precondition** | `spec_refined` and `interview_notes` present. |
| **Postcondition** | `solution.md` + 4 diagram files (`.mmd` + `.png`) on disk. `arch_uncertainty` metric set. |
| **Observability** | AuditLog. Diagram count, task count, uncertainty tracked in metrics. |
| **Move-on criteria** | `arch_uncertainty <= 0.8` (guardrails default) → ARCH_REVIEW. Otherwise self-loop to PLAN (max 2 loops). |

### 5. ARCH_REVIEW

| Field | Detail |
|-------|--------|
| **Input** | ALL PLAN artifacts (spec, plan, tasks, analysis, doubt_resolution, checklist, api_contract, interview_notes, diagrams with PNGs), `metrics[arch_uncertainty, task_count, diagram_count]` |
| **Output** | `{artifacts[review_approved: bool], diagram_status, user_review_comments (if rejected), next_phase}` |
| **Skills** | None (human gate) |
| **What it does** | HIL interrupt: presents all artifacts + metrics to human reviewer. Approve → sets `review_approved=True`, advances to BUILD. Reject → sets `review_approved=False`, captures `user_review_comments`, sends back to PLAN. Auto-approve mode skips interrupt entirely. |
| **Precondition** | PLAN completed with artifacts. `auto_approve` flag controls HIL behavior. |
| **Postcondition** | `review_approved` boolean in artifacts. If rejected, `user_review_comments` propagates to DEFINE. |
| **Observability** | AuditLog logs approval decision + comments. |
| **Move-on criteria** | `review_approved` → BUILD. Rejection → PLAN (with feedback). No loop limit on human rejections. |

### 6. BUILD

| Field | Detail |
|-------|--------|
| **Input** | `artifacts[spec_refined]`, `artifacts[tasks]`, `artifacts[solution_md]` (or `solution_path`), `project_path`, `project_name` |
| **Output** | `{artifacts: {build_status, build_log, test_results, generated_code_files, build_errors, uat_report}, metrics[uat_pass_rate], _build_fail_count, next_phase}` |
| **Skills** | OpenHands agent (codeact profile, 50 iterations, local LLM Qwen3.6-27B) |
| **What it does** | Delegates to OpenHands agent-server via Gateway API. Constructs prompt from spec + tasks + solution.md. Creates conversation → polls for completion (5s interval, 1h timeout). On failure/timeout/5xx: falls back to `_fallback_legacy_build()`. Parses response: extracts generated code files, writes them to `project_path` immediately. Derives `uat_pass_rate` from build status (pass=1.0, partial=0.5, fail=0.0). Tracks `_build_fail_count` — 3 consecutive failures → sets `error` + `next_phase: REFLECT`. |
| **Precondition** | `review_approved=True` from ARCH_REVIEW. `spec_refined` and tasks available. |
| **Postcondition** | Source code written to disk. `build_status` in artifacts. `uat_pass_rate` in metrics. |
| **Observability** | Build status, test results, security findings, error list all in artifacts. Logging with `logger.info/warning/error`. |
| **Move-on criteria** | **Three gates from `route_phase`**: (1) `security_findings <= 0` (strict), (2) `review_revisions <= 2`, (3) `uat_pass_rate >= 0.95`. All pass → SEED_DATA. Any fail → self-loop to BUILD (edge-side counter, max 2 loops). 3 consecutive node-level failures → REFLECT. |

### 7. SEED_DATA

| Field | Detail |
|-------|--------|
| **Input** | Nothing meaningful — pass-through |
| **Output** | `{artifacts[seed_data_status: "skipped_placeholder"], next_phase: VERIFY}` |
| **Skills** | None |
| **What it does** | Placeholder. No real logic. Logs that it's skipped. |
| **Precondition** | BUILD passed quality gates. |
| **Postcondition** | `seed_data_status` set. |
| **Observability** | AuditLog only. |
| **Move-on criteria** | Always → VERIFY (unconditional edge). |

### 8. VERIFY

| Field | Detail |
|-------|--------|
| **Input** | Nothing — pass-through |
| **Output** | `{artifacts[verify_status: "skipped_placeholder"], metrics reset to all-passing, next_phase: SHIP}` |
| **Skills** | None |
| **What it does** | Placeholder. **Dangerous**: resets `uat_pass_rate=1.0`, `security_findings=0`, `test_flakiness_rate=0.0`, etc. This silently clears any failure signals from BUILD. |
| **Precondition** | SEED_DATA completed. |
| **Postcondition** | Metrics artificially set to passing. |
| **Observability** | AuditLog only. |
| **Move-on criteria** | Always → SHIP (unconditional edge). |

### 9. SHIP

| Field | Detail |
|-------|--------|
| **Input** | `project_path`, `artifacts[build_status]`, `artifacts[project_context]` |
| **Output** | `{artifacts: {observability, launch_checklist, prod_deploy_config, git_log}, metrics[launch_success], next_phase: REFLECT}` |
| **Skills** | `observability-and-instrumentation` → `shipping-and-launch` → `production-deployment` → `git-workflow` |
| **What it does** | 4-step pipeline: (1) Adds structured logging, health endpoints, RED metrics. (2) Generates pre-launch checklist (feature flags, rollback plan, staging). (3) Generates cloud deployment configs (ECS/Azure/Cloud Run, CI/CD, secrets management). (4) Git workflow for atomic commits. Writes `storage/live.json` (deployment record) and `storage/deployments/{cycle_id}.json` (append-only history). Sets `launch_success=True`. |
| **Precondition** | VERIFY completed (placeholder). `project_path` available. |
| **Postcondition** | Deployment record on disk. `live.json` updated. `launch_success` metric set. |
| **Observability** | `launch_success` boolean in metrics. AuditLog for each step. |
| **Move-on criteria** | Always → REFLECT (unconditional edge). |

### 10. REFLECT

| Field | Detail |
|-------|--------|
| **Input** | `metrics` (full CycleMetrics), `artifacts`, `feedback`, `cycle_id`, guardrails.yaml |
| **Output** | `{artifacts[proposed_diffs, git_commit], feedback, config_version, next_phase: END}` |
| **Skills** | Internal meta-agent (`generate_config_diffs`) → `git-workflow` |
| **What it does** | Self-improvement loop: (1) Records cycle data to `storage/cycles/` via FeedbackAggregator. (2) Loads guardrails.yaml. (3) Queries ChromaDB for historical patterns (semantic similarity on metrics). (4) Generates proposed config/skill diffs using LLM meta-agent. (5) Dry-run validation of changes. (6) HIL approval gate for applying diffs. (7) If approved: patches `guardrails.yaml`, commits via git-workflow. Stores current cycle pattern in ChromaDB for future reflection. |
| **Precondition** | SHIP completed. `launch_success=True`. |
| **Postcondition** | Cycle archived. Guardrails optionally updated. ChromaDB pattern stored. |
| **Observability** | Cycle metrics recorded. Config diffs logged. Git commit for applied changes. |
| **Move-on criteria** | Always → END (cycle complete). |

---

## Critical Issues

### BUILD Placement
**Problem**: BUILD is a single HTTP proxy node to OpenHands, not a subgraph. The docstring claims "falls back to the local build_subgraph" but `build_subgraph_legacy.py` is the fallback — it's an inline function `_fallback_legacy_build()`, not a graph subgraph. There's no conditional routing between BUILD and SEED_DATA/VERIFY/SHIP in `main.py` edges — those are all unconditional `add_edge()`. Only `route_phase` from `edges.py` handles BUILD→BUILD retry via the conditional edge.

**SEED_DATA → VERIFY → SHIP** is a linear pass-through chain. Neither node does anything real. The real gate is BUILD's quality checks in `route_phase`. SEED_DATA and VERIFY are architectural placeholders that exist for future expansion but currently provide no value — VERIFY actively *resets* metrics to passing, which is a bug if BUILD failures were supposed to propagate.

### Metric Reset Bug
VERIFY sets `uat_pass_rate=1.0`, `security_findings=0`, `test_flakiness_rate=0.0`, etc. This means even if BUILD failed UAT but didn't hit the 3-strike abort, VERIFY would silently make everything look fine. The BUILD→SEED_DATA→VERIFY→SHIP path should only be reachable when BUILD actually passes — but `route_phase` checks BUILD gates *before* routing to SEED_DATA. If BUILD fails gates, it self-loops. If it passes gates, VERIFY's reset is harmless but misleading (metrics become stale noise).

### Loop Counter Inconsistency
- DEFINE/PLAN/ARCH_REVIEW: `_maybe_increment_loop()` called from NODE code. Edge reads counter.
- BUILD: edge-side counter increment in `route_phase` itself. This is a violation — edges should be read-only, but BUILD is the exception because the node doesn't always persist `loop_counts` before routing.
- `_forward_paths` has entries for all phases but only DEFINE, PLAN, and BUILD actually self-loop via `route_phase`. ARCH_REVIEW reject→PLAN is not loop-counted.

### Threshold Defaults
| Threshold | Default | Risk |
|-----------|---------|------|
| `min_spec_confidence` | 0.9 | Tight — only works if spec has Gherkin keywords + error handling |
| `max_arch_uncertainty` | 0.8 | Lenient — depends on doubt skill quality |
| `max_security_findings` | 0 | Strict — any finding blocks BUILD |
| `max_review_revisions` | 2 | Reasonable |
| `uat_pass_rate` | 0.95 | Irrelevant (VERIFY resets to 1.0) |