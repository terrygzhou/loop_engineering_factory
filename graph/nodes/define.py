"""
DEFINE node: Generate spec and API contracts from interview notes collected in DISCOVER.
Fully automatic — no user input required (interview is in DISCOVER phase).

Skills: writing-plans (spec generation) → api-and-interface-design
"""
import re
from pathlib import Path
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from tools.context_manager import prepare_context_for_llm
from tools.audit_logger import AuditLog
from config.loader import config
from config.bounds_loader import bounds

def _cap_list(lst: list, max_len: int) -> list:
    """Trim list to last max_len entries."""
    return lst[-max_len:]
from feedback.chroma_client import get_chroma_client, query_patterns

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

def define_node(state: dict) -> dict:
    """
    DEFINE phase: Gather requirements through interview, generate spec,
    design API interfaces. Uses project_context from DISCOVER to inform
    spec creation.

    Input:
      - project_description: User's project description
      - project_context: Discovery results from DISCOVER
      - user_review_comments: Optional feedback from ARCH_REVIEW rejection
      - feedback_context: Historical patterns from ChromaDB
      - interview_notes: Previously collected answers (if retry)

    Output:
      - $project_folder/specs/interview_notes.md
      - $project_folder/specs/specification.md
      - $project_folder/specs/api_contract.md
      - state["artifacts"]["interview_notes"], "spec_refined", "api_contract"
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
            state["project_name"] = project_name
            state["artifacts"]["project_name"] = project_name
            state["project_path"] = config.paths.project_path
            print(f"  → Project: {project_name} → {config.paths.project_path}")
        except ValueError as e:
            print(f"  ✗ {e}")
    else:
        print("  ⚠ No project_name — using config default")

    # ── Load skills ──
    skills = state.get("artifacts", {}).get("skill_registry")
    if skills is None:
        print("  → No skill_registry in state — building from disk...")
        skills = build_skill_registry()
        state.setdefault("artifacts", {})["skill_registry"] = skills
    feedback = []

    # ── Load project context from DISCOVER ──
    project_context = state.get("artifacts", {}).get("project_context", "")
    if project_context:
        print(f"  → Using project_context from DISCOVER ({len(project_context)} chars)")
    else:
        print("  ⚠ No project_context — DISCOVER may have been skipped")

    # ── Load historical feedback context from ChromaDB ──
    feedback_context = _load_feedback_context(state)
    state["feedback_context"] = feedback_context

    # ── Handle user review comments (from ARCH_REVIEW rejection) ──
    user_review_comments = state.get("user_review_comments", "")
    if user_review_comments:
        print(f"  → Incorporating user review comments ({len(user_review_comments)} chars)")
        audit.log_user_input("review_feedback", "DEFINE", "Incorporating review comments", "api")

    # ── Step 1: Interview notes (from DISCOVER) ──
    # DEFINE is fully automatic — interview is collected in DISCOVER phase.
    # If interview_notes exist, proceed to spec generation.
    # If not (e.g., legacy state), use project_description as fallback.
    interview_notes = state.get("artifacts", {}).get("interview_notes", "")
    if interview_notes:
        print(f"  → Using interview notes from DISCOVER ({len(interview_notes)} chars)")
    else:
        print("  ⚠ No interview notes — using project description as fallback")
        interview_notes = state.get("project_description", "")

    feedback.append({"skill": "interview-me", "output": interview_notes[:bounds.feedback.max_feedback_entry_chars] if interview_notes else "(empty)"})

    # ── Step 2: Generate/refine spec (structured with traceability + ToT→CoT) ──
    spec_skill = skills.get("writing-plans", {})
    if spec_skill:
        print("  → Running writing-plans for spec generation...")
        context = f"Spec path: {state.get('spec_path', '')}\n"
        if project_context:
            context += f"Existing project context:\n{project_context}\n"
        context += f"Interview notes:\n{interview_notes}\n"
        if feedback_context:
            context += f"\n\n{feedback_context}\n"
        if user_review_comments:
            context += f"\n\n## User Review Comments (from ARCH_REVIEW rejection)\n{user_review_comments}\n"

        # Context optimization: prune before LLM call
        optimized = prepare_context_for_llm({"context": context}, max_tokens=bounds.context.define_max_tokens)
        result = invoke_skill(
            spec_skill["content"],
            "Produce a complete, actionable specification. Include user stories with acceptance criteria, edge cases, non-functional requirements, and out-of-scope items.",
            optimized["context"], llm=None,
            workflow_id=project_name, phase="DEFINE"
        )
        state["artifacts"]["spec_refined"] = result
        feedback.append({"skill": "writing-plans", "output": result[:bounds.feedback.max_feedback_entry_chars]})

    # ── Step 3: API/interface design (multi-interface, contract-first + ToT→CoT) ──
    api_skill = skills.get("api-and-interface-design", {})
    if api_skill:
        print("  → Running api-and-interface-design...")
        task = api_and_interface_design
        result = invoke_skill(
            api_skill["content"], task,
            state.get("artifacts", {}).get("spec_refined", ""),
            llm=None, workflow_id=project_name, phase="DEFINE"
        )
        state["artifacts"]["api_contract"] = result
        feedback.append({"skill": "api-and-interface-design", "output": result[:bounds.feedback.max_feedback_entry_chars]})

    # ── Persist to $project_folder/specs/ ──
    project_folder = state.get("project_folder", state.get("project_path", ""))
    specs_dir = Path(project_folder) / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)

    # Write interview_notes.md
    interview_path = specs_dir / "interview_notes.md"
    interview_content = state.get("artifacts", {}).get("interview_notes", "")
    interview_path.write_text(interview_content)
    audit.log_file_write("DEFINE", str(interview_path), "markdown", len(interview_content))

    # Write specification.md
    spec_path = specs_dir / "specification.md"
    spec_content = state.get("artifacts", {}).get("spec_refined", "")
    spec_path.write_text(spec_content)
    audit.log_file_write("DEFINE", str(spec_path), "markdown", len(spec_content))

    # Write api_contract.md
    api_path = specs_dir / "api_contract.md"
    api_content = state.get("artifacts", {}).get("api_contract", "")
    api_path.write_text(api_content)
    audit.log_file_write("DEFINE", str(api_path), "markdown", len(api_content))

    # ── Derive spec_confidence from actual artifact quality ──
    spec_confidence = _estimate_spec_confidence(state["artifacts"])

    # If spec confidence is low, increment loop counter to prevent infinite loops
    # Nodes must increment loop counters (edges don't persist mutations)
    min_spec_conf = 0.9  # Match guardrails.yaml default
    if spec_confidence < min_spec_conf:
        from graph.edges import _maybe_increment_loop
        if _maybe_increment_loop(state, "DEFINE"):
            print(f"  ⚠ spec_confidence={spec_confidence:.2f} < {min_spec_conf} — loop limit reached, forcing forward to PLAN")
        else:
            print(f"  ⚠ spec_confidence={spec_confidence:.2f} < {min_spec_conf} — looping back to DEFINE")

    state["metrics"] = state["metrics"].model_copy(update={
        "spec_confidence": spec_confidence,
    })
    state["phase"] = "DEFINE"
    state["feedback"] = _cap_list(state.get("feedback", []) + feedback, bounds.artifacts.max_feedback_entries)
    state["next_phase"] = "PLAN"
    state["human_approval_required"] = False

    print(f"  ✓ spec_confidence={spec_confidence:.2f} (derived from artifact quality)")
    print(f"  → Specs written to {specs_dir}/")
    return state
