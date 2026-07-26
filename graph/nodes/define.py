"""
DEFINE node: Generate spec and API contracts from interview notes collected in DISCOVER.
Fully automatic — no user input required (interview is in DISCOVER phase).

Skills: spec-driven-development (spec generation) → api-and-interface-design
"""
import re
from pathlib import Path
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from tools.context_manager import prepare_context_for_llm
from tools.audit_logger import AuditLog
from config.loader import config
from config.bounds_loader import bounds
from feedback.chroma_client import get_chroma_client, query_patterns


def define_node(state: dict) -> dict:
    """
    DEFINE phase: Gather requirements through interview, generate spec,
    design API interfaces. Uses project_context from DISCOVER to inform
    spec creation.

    Returns partial update dict (LangGraph reducer merges).
    """
    print("\n=== DEFINE PHASE ===")

    # ── Audit logging ──
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input("DEFINE", {
        "project_name": state.get("project_name", ""),
        "project_description": (state.get("project_description", "")[:200]),
        "has_project_context": bool(state.get("artifacts", {}).get("project_context")),
        "user_review_comments": bool(state.get("user_review_comments")),
    })

    # ── Capture project name and persist to config ──
    project_name = state.get("project_name", "") or state.get("artifacts", {}).get("project_name", "")
    if project_name:
        if not re.match(r'^[a-zA-Z0-9_-]+$', project_name):
            print(f"  ⚠ Invalid project name '{project_name}' — sanitizing to safe identifier")
            project_name = re.sub(r'[^a-zA-Z0-9_-]', '_', project_name).strip('_')
        try:
            config.set_project_name(project_name)
            print(f"  → Project: {project_name} → {config.paths.project_path}")
        except ValueError as e:
            print(f"  ✗ {e}")
    else:
        print("  ⚠ No project_name — using config default")

    # ── Load skills (lazy-load via cached registry) ──
    skills = build_skill_registry()

    # ── Load project context from DISCOVER ──
    project_context = state.get("artifacts", {}).get("project_context", "")
    if project_context:
        print(f"  → Using project_context from DISCOVER ({len(project_context)} chars)")
    else:
        print("  ⚠ No project_context — DISCOVER may have been skipped")

    # ── Load historical feedback context from ChromaDB ──
    feedback_context = _load_feedback_context(state)

    # ── Handle user review comments (from ARCH_REVIEW rejection) ──
    user_review_comments = state.get("user_review_comments", "")
    if user_review_comments:
        print(f"  → Incorporating user review comments ({len(user_review_comments)} chars)")
        audit.log_user_input("review_feedback", "DEFINE", "Incorporating review comments", "api")

    # ── Step 1: Interview notes (from DISCOVER) ──
    interview_notes = state.get("artifacts", {}).get("interview_notes", "")
    if interview_notes:
        print(f"  → Using interview notes from DISCOVER ({len(interview_notes)} chars)")
    else:
        print("  ⚠ No interview notes — using project description as fallback")
        interview_notes = state.get("project_description", "")

    feedback_entries = [
        {"skill": "interview-me", "output": interview_notes[:bounds.feedback.max_feedback_entry_chars] if interview_notes else "(empty)"}
    ]

    # ── Step 2: Generate/refine spec (structured with traceability + ToT→CoT) ──
    spec_result = None
    spec_skill = skills.get("spec-driven-development", {})
    if spec_skill:
        print("  → Running spec-driven-development for spec generation...")
        context = f"Spec path: {state.get('spec_path', '')}\n"
        if project_context:
            context += f"Existing project context:\n{project_context}\n"
        context += f"Interview notes:\n{interview_notes}\n"
        feedback_ctx = feedback_context if feedback_context else ""
        if feedback_ctx:
            context += f"\n\n{feedback_ctx}\n"
        if user_review_comments:
            context += f"\n\n## User Review Comments (from ARCH_REVIEW rejection)\n{user_review_comments}\n"

        # Context optimization: prune before LLM call
        optimized = prepare_context_for_llm({"context": context}, max_tokens=bounds.context.define_max_tokens)
        spec_result = invoke_skill(
            spec_skill["content"],
            "Produce structured spec with all 6 core areas: objective, commands, project structure, code style, testing strategy, boundaries. Include success criteria and out-of-scope items.",
            optimized["context"], llm=None,
            workflow_id=project_name, phase="DEFINE"
        )
        feedback_entries.append({"skill": "spec-driven-development", "output": spec_result[:bounds.feedback.max_feedback_entry_chars]})

    # ── Step 3: API/interface design (multi-interface, contract-first + ToT→CoT) ──
    api_result = None
    api_skill = skills.get("api-and-interface-design", {})
    if api_skill:
        print("  → Running api-and-interface-design...")
        task = api_and_interface_design
        api_result = invoke_skill(
            api_skill["content"], task,
            state.get("artifacts", {}).get("spec_refined", ""),
            llm=None, workflow_id=project_name, phase="DEFINE"
        )
        feedback_entries.append({"skill": "api-and-interface-design", "output": api_result[:bounds.feedback.max_feedback_entry_chars]})

    # ── Persist to $project_folder/specs/ ──
    project_folder = state.get("project_folder", state.get("project_path", ""))
    specs_dir = Path(project_folder) / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)

    # Write interview_notes.md
    interview_path = specs_dir / "interview_notes.md"
    interview_path.write_text(interview_notes)
    audit.log_file_write("DEFINE", str(interview_path), "markdown", len(interview_notes))

    # Write specification.md
    spec_path = specs_dir / "specification.md"
    if spec_result:
        spec_path.write_text(spec_result)
        audit.log_file_write("DEFINE", str(spec_path), "markdown", len(spec_result))

    # Write api_contract.md
    api_path = specs_dir / "api_contract.md"
    if api_result:
        api_path.write_text(api_result)
        audit.log_file_write("DEFINE", str(api_path), "markdown", len(api_result))

    # ── Build artifacts delta ──
    artifacts_delta = {}
    if project_name:
        artifacts_delta["project_name"] = project_name
    if spec_result:
        artifacts_delta["spec_refined"] = spec_result
    if api_result:
        artifacts_delta["api_contract"] = api_result

    # ── Derive spec_confidence from actual artifact quality ──
    current_artifacts = state.get("artifacts", {})
    merged_artifacts = {**current_artifacts, **artifacts_delta}
    spec_confidence = _estimate_spec_confidence(merged_artifacts)

    # If spec confidence is low, increment loop counter to prevent infinite loops
    min_spec_conf = 0.9  # Match guardrails.yaml default
    if spec_confidence < min_spec_conf:
        from graph.edges import _maybe_increment_loop
        if _maybe_increment_loop(state, "DEFINE"):
            print(f"  ⚠ spec_confidence={spec_confidence:.2f} < {min_spec_conf} — loop limit reached, forcing forward to PLAN")
        else:
            print(f"  ⚠ spec_confidence={spec_confidence:.2f} < {min_spec_conf} — looping back to DEFINE")

    # ── Return partial update ──
    update = {
        "phase": "DEFINE",
        "feedback_context": feedback_context,
        "feedback": feedback_entries,
        "next_phase": "PLAN",
        "human_approval_required": False,
    }

    if project_name:
        update["project_name"] = project_name
        update["project_path"] = config.paths.project_path

    if artifacts_delta:
        update["artifacts"] = artifacts_delta

    # Update metrics
    current_metrics = state.get("metrics")
    if current_metrics and hasattr(current_metrics, "model_copy"):
        update["metrics"] = current_metrics.model_copy(update={"spec_confidence": spec_confidence})

    print(f"  ✓ spec_confidence={spec_confidence:.2f} (derived from artifact quality)")
    print(f"  → Specs written to {specs_dir}/")
    return update


api_and_interface_design = (
    "Design the API interfaces based on the specification.\n"
    "For each endpoint, define:\n"
    "- HTTP method, path, request schema, response schema\n"
    "- Authentication requirements\n"
    "- Rate limiting and validation rules\n"
    "- Error handling strategy"
)


def _load_feedback_context(state: dict) -> str:
    """Query ChromaDB for historical patterns relevant to this project type."""
    try:
        client = get_chroma_client()
        if client is None:
            return ""
        project_name = state.get("project_name", "unknown")
        project_ctx = state.get("artifacts", {}).get("project_context", "")
        query_text = f"project: {project_name} context: {project_ctx[:bounds.feedback.max_context_query_chars]}"
        results = query_patterns(client, {"project": project_name, "context": query_text[:bounds.feedback.max_context_query_chars]}, top_k=bounds.feedback.max_chroma_patterns)
        if not results:
            return ""
        parts = ["== Historical Lessons Learned =="]
        for i, pat in enumerate(results, 1):
            doc = pat.get("document", "")
            parts.append(f"\n[Past Cycle {i}] (similarity distance: {pat.get('distance', '?'):.3f})\n{doc[:bounds.feedback.max_pattern_doc_chars]}")
        parts.append("\n== End Historical Lessons ==")
        text = "\n".join(parts)
        print(f"  → Loaded {len(results)} historical feedback patterns")
        return text
    except Exception as e:
        return ""


def _estimate_spec_confidence(artifacts: dict) -> float:
    """Derive spec confidence from actual artifact content."""
    score = 0.0
    spec_text = artifacts.get("spec_refined", "")
    api_text = artifacts.get("api_contract", "")
    interview_text = artifacts.get("interview_notes", "")
    if spec_text and len(spec_text) > 100:
        score += 0.3
    if api_text and len(api_text) > 50:
        score += 0.2
    if interview_text and len(interview_text) > 50:
        score += 0.15
    spec_lower = spec_text.lower()
    if any(kw in spec_lower for kw in ["given", "when", "then", "acceptance", "criteria", "scenario"]):
        score += 0.15
    if any(kw in spec_lower for kw in ["edge case", "edge-case", "corner case", "empty", "invalid", "error"]):
        score += 0.1
    if any(kw in spec_lower for kw in ["error handling", "exception", "failure", "rollback", "fallback"]):
        score += 0.1
    return min(score, 1.0)