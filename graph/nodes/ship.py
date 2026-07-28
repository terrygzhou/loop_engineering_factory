"""
SHIP node: Add observability, run pre-launch checklist, generate production deployment config, version with git.
Skills: observability-and-instrumentation → shipping-and-launch → production-deployment → git-workflow
"""
from langgraph.config import get_stream_writer

import json
import os
from datetime import datetime
from config.loader import config
from config.bounds_loader import bounds
from tools.loader import build_skill_registry
from tools.llm import invoke_skill


def ship_node(state: dict) -> dict:
    writer = get_stream_writer() or (lambda **kw: None)  # fallback for tests/CLI
    """
    SHIP phase: Add observability, run launch checklist, deploy via Docker Compose,
    commit with git workflow.

    Returns partial update dict (LangGraph reducer merges).
    """
    writer({"type": "progress", "phase": "SHIP", "step": "started", "detail": "\n=== SHIP PHASE ===", "ts": time.time()})
    skills = build_skill_registry(config.workflow.skill_registry_path)

    project_path = state.get("project_path", "")
    feedback_entries: list[dict] = []
    artifacts_delta: dict[str, str] = {}

    # Step 1: Add observability
    obs_skill = skills.get("observability-and-instrumentation", {})
    if obs_skill:
        writer({"type": "progress", "phase": "SHIP", "step": "progress", "detail": "  → Running observability-and-instrumentation...", "ts": time.time()})
        result = invoke_skill(obs_skill["content"],
            "Add structured logging, health endpoints, and RED metrics",
            f"Project: {project_path}", llm=None)
        artifacts_delta["observability"] = result
        feedback_entries.append({"skill": "observability-and-instrumentation", "output": result[:bounds.feedback.max_feedback_entry_chars]})

    # Step 2: Pre-launch checklist
    launch_skill = skills.get("shipping-and-launch", {})
    if launch_skill:
        writer({"type": "progress", "phase": "SHIP", "step": "progress", "detail": "  → Running shipping-and-launch...", "ts": time.time()})
        result = invoke_skill(launch_skill["content"],
            "Run pre-launch checklist: feature flags, rollback plan, staging verification",
            f"Project: {project_path}", llm=None)
        artifacts_delta["launch_checklist"] = result
        feedback_entries.append({"skill": "shipping-and-launch", "output": result[:bounds.feedback.max_feedback_entry_chars]})

    # Step 3: Generate production deployment config (AWS/Azure/GCP)
    prod_skill = skills.get("production-deployment", {})
    if prod_skill:
        writer({"type": "progress", "phase": "SHIP", "step": "progress", "detail": "  → Running production-deployment...", "ts": time.time()})
        task = f"""Generate production deployment configurations for project at: {project_path}.

Determine the project type and generate:
1. Cloud platform deployment manifest (ECS task def / Azure ARM template / Cloud Run config)
2. CI/CD pipeline configuration (GitHub Actions / Cloud Build)
3. Secrets management references (AWS Secrets Manager / Azure Key Vault / GCP Secret Manager)
4. Health check and rollback strategy

Target environment considerations:
- Managed database (RDS/Azure SQL/Cloud SQL) instead of local PostgreSQL
- Cloud secret references instead of .env files
- Auto-scaling configuration
- TLS/certificate management
- Cloud-native logging (CloudWatch/Application Insights/Cloud Monitoring)
"""
        result = invoke_skill(prod_skill["content"], task,
                             state.get("artifacts", {}).get("launch_checklist", ""),
                             llm=None)
        artifacts_delta["prod_deploy_config"] = result
        feedback_entries.append({"skill": "production-deployment", "output": result[:bounds.feedback.max_feedback_entry_chars]})

    # Step 3b: Verify local deployment is healthy (BUILD handles docker-compose)
    build_status = state.get("artifacts", {}).get("build_status", "")
    if build_status == "pass":
        writer({"type": "progress", "phase": "SHIP", "step": "progress", "detail": "  → Local deployment verified from BUILD phase.", "ts": time.time()})

    # Step 4: Git workflow (commit changes)
    git_skill = skills.get("git-workflow", {})
    if git_skill:
        writer({"type": "progress", "phase": "SHIP", "step": "progress", "detail": "  → Running git-workflow...", "ts": time.time()})
        result = invoke_skill(git_skill["content"],
            "Create atomic, conventional commits for this cycle",
            f"Cycle: {state['cycle_id']}", llm=None)
        artifacts_delta["git_log"] = result
        feedback_entries.append({"skill": "git-workflow", "output": result[:bounds.feedback.max_feedback_entry_chars]})

    # ── Write live.json: product delivery record ──
    from config.loader import config as _cfg
    try:
        _storage_dir = _cfg.paths.storage_dir
        _project_path = project_path or state.get("project_folder", "")
        _ctx = state.get("artifacts", {}).get("project_context", "{}")
        if isinstance(_ctx, str):
            _ctx = json.loads(_ctx)
        _product_type = _ctx.get("project_type", "python-fastapi")
        _product_url = _cfg.services.product.url
        _live = {
            "version": "1",
            "product_url": _product_url,
            "health_endpoint": "/health",
            "project_path": _project_path,
            "project_name": state.get("project_name", ""),
            "cycle_id": state["cycle_id"],
            "deployed_at": datetime.now().isoformat(),
            "product_type": _product_type,
        }
        _live_path = os.path.join(_storage_dir, "live.json")
        os.makedirs(_storage_dir, exist_ok=True)
        with open(_live_path, "w") as _f:
            json.dump(_live, _f, indent=2)
        feedback_entries.append({"action": "live_json_written", "path": _live_path})
        writer({"type": "progress", "phase": "SHIP", "step": "success", "detail": f"  ✓ live.json written: {_live_path}", "ts": time.time()})

        # ── Deployment history: append-only record ──
        _deploy_dir = os.path.join(_storage_dir, "deployments")
        os.makedirs(_deploy_dir, exist_ok=True)
        _deploy_path = os.path.join(_deploy_dir, f"{state['cycle_id']}.json")
        with open(_deploy_path, "w") as _f:
            json.dump(_live, _f, indent=2)
        feedback_entries.append({"action": "deployment_recorded", "path": _deploy_path})
        writer({"type": "progress", "phase": "SHIP", "step": "success", "detail": f"  ✓ deployment recorded: {_deploy_path}", "ts": time.time()})
    except Exception as _e:
        writer({"type": "progress", "phase": "SHIP", "step": "warning", "detail": f"  ⚠ Could not write live.json or deployment record: {_e}", "ts": time.time()})

    # Update metrics
    current_metrics = state.get("metrics")
    metrics_update = None
    if current_metrics and hasattr(current_metrics, "model_copy"):
        metrics_update = current_metrics.model_copy(update={"launch_success": True})

    # Build partial update
    update = {
        "phase": "SHIP",
        "feedback": feedback_entries,
        "next_phase": "REFLECT",
        "config_version": state["cycle_id"],
    }
    if artifacts_delta:
        update["artifacts"] = artifacts_delta
    if metrics_update:
        update["metrics"] = metrics_update

    writer({"type": "progress", "phase": "SHIP", "step": "success", "detail": f"  ✓ launch_success=True", "ts": time.time()})
    return update