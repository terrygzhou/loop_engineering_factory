"""
ARCHITECTURE node: Generate architecture diagrams from workflow artifacts.
Uses architecture-diagram-generator skill to create visual representations.

Outputs:
  - Component diagram (system components + relationships)
  - Sequence diagram (request flow)
  - Data flow diagram (entity relationships)
  - Deployment diagram (infrastructure)
"""
import json
import os
from pathlib import Path
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from tools.context_manager import prepare_context_for_llm


def _extract_components(spec: str, api_contract: str) -> list[str]:
    """Extract named components from spec and API contract."""
    components = []
    # Extract from API contract
    import re
    # Look for endpoint paths as components
    endpoints = re.findall(r'(?:GET|POST|PUT|DELETE|PATCH)\s+/(\w+)', api_contract)
    for ep in endpoints:
        components.append(f"{ep}-endpoint")
    # Look for entity names in spec
    entities = re.findall(r'(?:entity|model|table|database)\s*[:=]?\s*["\']?(\w+)', spec, re.I)
    components.extend(entities)
    return list(set(components)) if components else ["main-component"]


def _generate_diagram(skills: dict, diagram_type: str, state: dict) -> str:
    """Generate a specific diagram type from workflow artifacts."""
    arch_skill = skills.get("architecture-diagram-generator", {})
    if not arch_skill:
        return f"# {diagram_type} - skill not available"

    spec = state.get("artifacts", {}).get("spec_refined", "")
    api = state.get("artifacts", {}).get("api_contract", "")
    plan = state.get("artifacts", {}).get("plan", "")
    tasks = state.get("artifacts", {}).get("tasks", "")
    doubt = state.get("artifacts", {}).get("doubt_resolution", "")

    context = f"Spec:\n{spec}\n\nAPI Contract:\n{api}\n\nPlan:\n{plan}\n\nTasks:\n{tasks}\n\nDoubt Resolution:\n{doubt}"

    task = f"Generate a {diagram_type} diagram as a Mermaid graph. Include all components, relationships, and data flows. Use the spec and API contract as the primary source of truth."

    diagram = invoke_skill(
        arch_skill["content"],
        task,
        context,
        llm=None,
        workflow_id=state.get("project_name", ""),
        phase="ARCHITECTURE",
    )
    return diagram


def architecture_node(state: dict) -> dict:
    """Generate architecture diagrams from workflow artifacts."""
    print("\n=== ARCHITECTURE PHASE ===")

    # Load skills
    skills = state.get("artifacts", {}).get("skill_registry")
    if skills is None:
        skills = build_skill_registry(os.getenv("SKILLS_DIR", "~/.hermes/skills"))
        state.setdefault("artifacts", {})["skill_registry"] = skills

    # Create output directory
    diagrams_dir = Path("build/diagrams")
    diagrams_dir.mkdir(parents=True, exist_ok=True)

    # Generate diagrams
    diagrams = {}

    print("  → Generating component diagram...")
    component_diagram = _generate_diagram(skills, "component", state)
    component_path = diagrams_dir / "component-diagram.mmd"
    component_path.write_text(component_diagram)
    diagrams["component"] = str(component_path)

    print("  → Generating sequence diagram...")
    sequence_diagram = _generate_diagram(skills, "sequence", state)
    sequence_path = diagrams_dir / "sequence-diagram.mmd"
    sequence_path.write_text(sequence_diagram)
    diagrams["sequence"] = str(sequence_path)

    print("  → Generating data flow diagram...")
    data_flow = _generate_diagram(skills, "data flow", state)
    data_flow_path = diagrams_dir / "data-flow.mmd"
    data_flow_path.write_text(data_flow)
    diagrams["data_flow"] = str(data_flow_path)

    print("  → Generating deployment diagram...")
    deployment_diagram = _generate_diagram(skills, "deployment", state)
    deployment_path = diagrams_dir / "deployment-diagram.mmd"
    deployment_path.write_text(deployment_diagram)
    diagrams["deployment"] = str(deployment_path)

    # Update state
    state["artifacts"]["diagrams"] = diagrams
    state["diagrams"] = diagrams
    state["diagram_status"] = "pending"
    state["phase"] = "ARCHITECTURE"
    state["next_phase"] = "ARCH_REVIEW"
    state["human_approval_required"] = True

    print(f"  ✓ Generated {len(diagrams)} diagrams → {diagrams_dir}")
    return state