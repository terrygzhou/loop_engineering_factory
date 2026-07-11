"""
SHIP node: Add observability, run pre-launch checklist, deploy, version with git.
Skills: observability-and-instrumentation → shipping-and-launch → docker-compose-deployment → git-workflow
"""
import json
import os
from datetime import datetime
from config.loader import config
from config.bounds_loader import bounds
from tools.loader import build_skill_registry
from tools.llm import invoke_skill


def ship_node(state: dict) -> dict:
    """
    SHIP phase: Add observability, run launch checklist, deploy via Docker Compose,
    commit with git workflow.
    """
    print("\n=== SHIP PHASE ===")
    skills = state.get("artifacts", {}).get("skill_registry")
    if skills is None:
        print("  → No skill_registry in state — building from disk...")
        skills = build_skill_registry(config.workflow.skill_registry_path)
        state.setdefault("artifacts", {})["skill_registry"] = skills
    feedback = []

    project_path = state.get("project_path", "")

    # Step 1: Add observability
    obs_skill = skills.get("observability-and-instrumentation", {})
    if obs_skill:
        print("  → Running observability-and-instrumentation...")
        task = "Add structured logging, health endpoints, and RED metrics"
        result = invoke_skill(obs_skill["content"], task,
                             f"Project: {project_path}", llm=None)
        state["artifacts"]["observability"] = result
        feedback.append({"skill": "observability-and-instrumentation", "output": result[:bounds.feedback.max_feedback_entry_chars]})

    # Step 2: Pre-launch checklist
    launch_skill = skills.get("shipping-and-launch", {})
    if launch_skill:
        print("  → Running shipping-and-launch...")
        task = "Run pre-launch checklist: feature flags, rollback plan, staging verification"
        result = invoke_skill(launch_skill["content"], task,
                             f"Project: {project_path}", llm=None)
        state["artifacts"]["launch_checklist"] = result
        feedback.append({"skill": "shipping-and-launch", "output": result[:bounds.feedback.max_feedback_entry_chars]})

    # Step 3: Deploy via Docker Compose (skip rebuild if BUILD already deployed)
    build_status = state.get("artifacts", {}).get("build_status", "")
    deploy_skill = skills.get("docker-compose-deployment", {})
    if deploy_skill:
        if build_status == "pass":
            print("  → BUILD already compiled and deployed. Skipping Docker rebuild.")
            import subprocess
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", config.services.product.url + "/"],
                capture_output=True, text=True, timeout=15,
            )
            state["artifacts"]["deploy_logs"] = f"SKIP_REBUILD: container health={result.stdout.strip()}"
            feedback.append({"skill": "docker-compose-deployment", "output": "Skipped — BUILD already deployed"})
        else:
            print("  → Running docker-compose-deployment (BUILD did not deploy)...")
            task = f"Deploy the application using docker compose up -d --build in: {project_path}"
            result = invoke_skill(deploy_skill["content"], task,
                                 state.get("artifacts", {}).get("launch_checklist", ""),
                                 llm=None)
            state["artifacts"]["deploy_logs"] = result
            feedback.append({"skill": "docker-compose-deployment", "output": result[:bounds.feedback.max_feedback_entry_chars]})

    # Step 4: Git workflow (commit changes)
    git_skill = skills.get("git-workflow", {})
    if git_skill:
        print("  → Running git-workflow...")
        task = "Create atomic, conventional commits for this cycle"
        result = invoke_skill(git_skill["content"], task,
                             f"Cycle: {state['cycle_id']}", llm=None)
        state["artifacts"]["git_log"] = result
        state["config_version"] = state["cycle_id"]
        feedback.append({"skill": "git-workflow", "output": result[:bounds.feedback.max_feedback_entry_chars]})

    # ── Write live.json: product delivery record ──
    # This is the bridge for future --improve cycles:
    # DISCOVER reads this file to find and health-check the running product.
    try:
        from config.loader import config
        from config.loader import config as _cfg
        _storage_dir = _cfg.paths.storage_dir
        _project_path = project_path or state.get("project_folder", "")
        # Derive product_type from DISCOVER scan context if available
        _ctx = state.get("artifacts", {}).get("project_context", "{}")
        _product_type = json.loads(_ctx if isinstance(_ctx, str) else "{}").get("project_type", "python-fastapi")
        from config.loader import config
        from config.loader import config as _cfg
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
        feedback.append({"action": "live_json_written", "path": _live_path})
        print(f"  ✓ live.json written: {_live_path}")

        # ── Deployment history: append-only record ──
        _deploy_dir = os.path.join(_storage_dir, "deployments")
        os.makedirs(_deploy_dir, exist_ok=True)
        _deploy_path = os.path.join(_deploy_dir, f"{state['cycle_id']}.json")
        with open(_deploy_path, "w") as _f:
            json.dump(_live, _f, indent=2)
        feedback.append({"action": "deployment_recorded", "path": _deploy_path})
        print(f"  ✓ deployment recorded: {_deploy_path}")

    except Exception as _e:
        print(f"  ⚠ Could not write live.json or deployment record: {_e}")

    # Mark as successfully launched
    state["metrics"] = state["metrics"].model_copy(update={
        "launch_success": True,
    })
    state["phase"] = "SHIP"
    state["feedback"] = (state.get("feedback", []) + feedback)[-bounds.artifacts.max_feedback_entries:]
    state["next_phase"] = "REFLECT"

    print(f"  ✓ launch_success=True")
    return state
