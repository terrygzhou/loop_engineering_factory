"""
SEED_DATA node: Generate random test data against data models and API specs.
Outputs: seeding scripts, instructions, edge cases to $project_folder/build/seed_data/

Skills: ai-workflow-data-seeding
"""
import os
import ast
import json
import subprocess
from pathlib import Path
from tools.loader import build_skill_registry
from tools.llm import invoke_skill
from tools.audit_logger import AuditLog
from graph.nodes.build import find_docker_project


def seed_data_node(state: dict) -> dict:
    """
    SEED_DATA phase: Generate random test data against data models and API specs.
    Outputs seeding scripts, instructions, and edge cases to project folder.

    Input:
      - code_generated: Implementation code from BUILD
      - spec_refined: Specification with data model definitions
      - api_contract: API contract with model schemas
      - project_folder: Target directory

    Output:
      - $project_folder/build/seed_data/seed.py: Seeding script
      - $project_folder/build/seed_data/instructions.md: Usage instructions
      - $project_folder/build/seed_data/edge_cases.md: Edge case scenarios
      - $project_folder/build/seed_data/schema.md: Data model reference
    """
    print("\n=== SEED DATA PHASE ===")

    # ── Audit logging ──
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input("SEED_DATA", {
        "has_code": bool(state.get("artifacts", {}).get("code_generated")),
        "has_spec": bool(state.get("artifacts", {}).get("spec_refined")),
    })

    skills = state.get("artifacts", {}).get("skill_registry")
    if skills is None:
        print("  → No skill_registry in state — building from disk...")
        skills = build_skill_registry(os.getenv("SKILLS_DIR", "~/.hermes/skills"))
        state.setdefault("artifacts", {})["skill_registry"] = skills

    project_path = state.get("project_path", "")
    project_folder = state.get("project_folder", project_path)
    if not project_path:
        print("  ⚠ No project_path specified, skipping seed data generation")
        state["phase"] = "SEED_DATA"
        state["next_phase"] = "VERIFY"
        return state

    # ── Resolve docker project dir ──
    docker_proj = find_docker_project(project_path)
    print(f"  → Docker project dir: {docker_proj}")

    # ── Create output directory ──
    seed_dir = Path(project_folder) / "build" / "seed_data"
    seed_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Extract data models from code ──
    data_models = _extract_data_models(docker_proj)
    api_specs = _extract_api_specs(docker_proj)
    state["artifacts"]["data_models"] = json.dumps(data_models, indent=2)

    # ── Step 2: Generate seed script via LLM ──
    seed_skill = skills.get("ai-workflow-data-seeding", {})
    if not seed_skill:
        seed_skill = {
            "content": """Generate a seed script that:
1. Reads the project models from the project directory
2. Creates a Python script that populates the database
3. Uses SQLAlchemy 2.0 async insert() with deterministic data
4. Handles UUID vs Integer primary keys appropriately
5. Seeds all models with realistic data
6. Is idempotent (safe to run multiple times)
Output ONLY valid Python code. No markdown, no explanations outside the code."""
        }

    task = f"""Generate random test data seed script for project at {docker_proj}.
Data models available: {len(data_models)} models
API specs available: {len(api_specs)} endpoints

Requirements:
- Generate at least 5 records per model with realistic random data
- Include edge cases: null fields, empty strings, boundary values
- Make the script idempotent with INSERT OR IGNORE or check-first pattern
- Include a --all flag to seed everything, or model names to seed specific tables
"""

    context = (
        state.get("artifacts", {}).get("spec_refined", "") +
        "\n\n" +
        state.get("artifacts", {}).get("code_generated", "") +
        "\n\n" +
        f"Data models: {json.dumps(data_models, indent=2)}\n" +
        f"API specs: {json.dumps(api_specs, indent=2)}"
    )

    print("  → [GENERATION] Generating seed script via LLM...")
    seed_script = invoke_skill(seed_skill["content"], task, context, llm=None)
    state["artifacts"]["seed_script"] = seed_script

    # ── Step 3: Validate seed script ──
    clean_script = seed_script.strip()
    if clean_script.startswith("```"):
        lines = clean_script.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean_script = "\n".join(lines)

    try:
        ast.parse(clean_script)
        print("  ✓ [VALIDATION] Seed script is valid Python (AST parse passed)")
    except SyntaxError as e:
        print(f"  ✗ [VALIDATION] Seed script is NOT valid Python: {e}")
        print(f"  → First 200 chars: {clean_script[:200]}")
        state["artifacts"]["seed_errors"] = f"SyntaxError: {e}"
        state["error"] = f"Seed script failed AST validation: {e}"
        state["phase"] = "SEED_DATA"
        state["next_phase"] = "BUILD"
        return state

    # ── Step 4: Write seed script to $project_folder/build/seed_data/ ──
    seed_path = seed_dir / "seed.py"
    seed_path.write_text(clean_script)
    audit.log_file_write("SEED_DATA", str(seed_path), "python", len(clean_script))
    print(f"  → seed.py written: {seed_path} ({len(clean_script)} chars)")

    # ── Step 5: Generate instructions ──
    instructions = _generate_instructions(seed_path, data_models, docker_proj)
    instructions_path = seed_dir / "instructions.md"
    instructions_path.write_text(instructions)
    audit.log_file_write("SEED_DATA", str(instructions_path), "markdown", len(instructions))
    print(f"  → instructions.md written: {instructions_path}")

    # ── Step 6: Generate edge cases document ──
    edge_cases = _generate_edge_cases(data_models, api_specs)
    edge_cases_path = seed_dir / "edge_cases.md"
    edge_cases_path.write_text(edge_cases)
    audit.log_file_write("SEED_DATA", str(edge_cases_path), "markdown", len(edge_cases))
    print(f"  → edge_cases.md written: {edge_cases_path}")

    # ── Step 7: Generate schema reference ──
    schema_md = _generate_schema_md(data_models, api_specs)
    schema_path = seed_dir / "schema.md"
    schema_path.write_text(schema_md)
    audit.log_file_write("SEED_DATA", str(schema_path), "markdown", len(schema_md))
    print(f"  → schema.md written: {schema_path}")

    # ── Step 8: Copy seed script to Docker project for execution ──
    docker_seed_path = Path(docker_proj) / "app" / "seed.py"
    docker_seed_path.parent.mkdir(parents=True, exist_ok=True)
    docker_seed_path.write_text(clean_script)
    print(f"  → Seed script copied to {docker_seed_path} for Docker execution")

    # ── Step 9: Execute seed script inside Docker ──
    print("  → [EXECUTION] Running seed script in Docker container...")
    try:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "api", "python", "-m", "app.seed"],
            capture_output=True, text=True, timeout=60, cwd=docker_proj,
        )
        seed_output = result.stdout + result.stderr
        print(f"  Seed output:\n{seed_output[:500]}")

        if result.returncode != 0:
            print("  ✗ Seed script failed with exit code", result.returncode)
            state["artifacts"]["seed_errors"] = seed_output
            state["error"] = f"Seed script failed (exit {result.returncode}): {seed_output[:300]}"
            state["next_phase"] = "BUILD"
        else:
            print("  ✓ Seed data populated successfully")
            state["artifacts"]["seed_result"] = seed_output
            state["error"] = None
            state["next_phase"] = "VERIFY"
    except subprocess.TimeoutExpired:
        print("  ✗ Seed script timed out (>60s)")
        state["artifacts"]["seed_errors"] = "Seed script timed out"
        state["error"] = "Seed script timed out after 60s"
        state["next_phase"] = "BUILD"
    except Exception as e:
        print(f"  ✗ Seed execution failed: {e}")
        state["artifacts"]["seed_errors"] = str(e)
        state["error"] = f"Seed execution failed: {e}"
        state["next_phase"] = "BUILD"

    # ── Audit output ──
    audit.log_node_output("SEED_DATA", {
        "seed_script_path": str(seed_path),
        "instructions_path": str(instructions_path),
        "edge_cases_path": str(edge_cases_path),
        "schema_path": str(schema_path),
        "models_count": len(data_models),
        "executed": state["next_phase"] == "VERIFY",
    })
    audit.log_node_transition(
        "SEED_DATA",
        state["next_phase"],
        state["error"] or "seeding complete"
    )

    state["phase"] = "SEED_DATA"
    state["metrics"] = state["metrics"].model_copy(update={
        "seed_executed": state["next_phase"] == "VERIFY",
    })

    return state


def _extract_data_models(docker_proj: str) -> list[dict]:
    """Extract data models from project code."""
    models = []
    p = Path(docker_proj) / "app" / "models"
    if not p.exists():
        return models
    import re
    for pyfile in p.glob("*.py"):
        if pyfile.name.startswith("_"):
            continue
        text = pyfile.read_text(errors="replace")
        for match in re.finditer(
            r'class\s+(\w+)\s*\([^)]*(?:Base|Model|DeclarativeBase)[^)]*\)',
            text
        ):
            model_name = match.group(1)
            # Extract fields
            fields = re.findall(
                rf'(?:class\s+{model_name}\s*\([^)]*\)[^:]*:|class\s+{model_name}.*?)(.*?)(\n\nclass|\Z)',
                text, re.DOTALL
            )
            field_list = []
            for _, block in fields:
                field_matches = re.findall(r'(\w+)\s*:\s*(\w+)', block)
                for fname, ftype in field_matches:
                    field_list.append({"name": fname, "type": ftype})
            models.append({
                "name": model_name,
                "file": str(pyfile.relative_to(Path(docker_proj))),
                "fields": field_list,
            })
    return models


def _extract_api_specs(docker_proj: str) -> list[dict]:
    """Extract API specs from route files."""
    specs = []
    p = Path(docker_proj)
    import re
    for router_dir in [p / "app" / "api", p / "app" / "routers"]:
        if not router_dir.exists():
            continue
        for pyfile in router_dir.glob("*.py"):
            if pyfile.name.startswith("_"):
                continue
            text = pyfile.read_text(errors="replace")
            patterns = re.findall(
                r'@\w+\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']',
                text
            )
            for method, path in patterns:
                specs.append({
                    "method": method.upper(),
                    "path": path,
                    "file": str(pyfile.relative_to(p)),
                })
    return specs


def _generate_instructions(seed_path: Path, models: list[dict], docker_proj: str) -> str:
    """Generate usage instructions for seed data."""
    lines = [
        "# Seed Data Instructions",
        "",
        "## Usage",
        "",
        "### Run all seeds",
        f"```bash",
        f"cd {docker_proj}",
        f"docker compose exec api python -m app.seed --all",
        f"```",
        "",
        "### Run specific model seeds",
        "",
    ]
    for model in models[:10]:
        lines.append(f"- `{model['name']}`: Seed {model['name'].lower()} data")
    lines.append("")
    lines.append("## Output Files")
    lines.append(f"- `{seed_path.name}`: Main seeding script")
    lines.append("- `instructions.md`: This file")
    lines.append("- `edge_cases.md`: Edge case scenarios tested")
    lines.append("- `schema.md`: Data model reference")
    lines.append("")
    lines.append("## Notes")
    lines.append("- Scripts are idempotent — safe to run multiple times")
    lines.append("- Random data is seeded with a fixed seed for reproducibility")
    lines.append("- Use `--help` for all available options")
    return "\n".join(lines)


def _generate_edge_cases(models: list[dict], api_specs: list[dict]) -> str:
    """Generate edge case scenarios for seed data."""
    lines = ["# Edge Cases", ""]
    lines.append("## General Edge Cases")
    lines.append("- Empty/null required fields")
    lines.append("- Maximum length strings (varchar boundaries)")
    lines.append("- Duplicate unique constraints")
    lines.append("- Foreign key violations")
    lines.append("- Date/time boundary values (epoch, far future)")
    lines.append("- Special characters in strings (SQL injection prevention)")
    lines.append("- Unicode characters (emoji, RTL text)")
    lines.append("- Zero and negative numeric values")
    lines.append("- Very large numbers (overflow)")
    lines.append("- Empty lists/arrays")
    lines.append("- Null JSON fields")
    lines.append("")

    if models:
        lines.append("## Model-Specific Edge Cases")
        for model in models[:10]:
            lines.append(f"### {model['name']}")
            lines.append("- **Default**: Minimal required fields")
            lines.append("- **Null fields**: Test nullable columns")
            lines.append("- **Max length**: Boundary test on varchar fields")
            if model.get("fields"):
                for field in model["fields"][:5]:
                    if field["name"] in ("id", "pk"):
                        continue
                    lines.append(f"- **{field['name']}**: Test {field.get('type', '?')} type limits")
            lines.append("")
    return "\n".join(lines)


def _generate_schema_md(models: list[dict], api_specs: list[dict]) -> str:
    """Generate data model reference document."""
    lines = ["# Data Model Reference", ""]
    if models:
        for model in models:
            lines.append(f"## {model['name']}")
            lines.append(f"- **File**: `{model.get('file', 'unknown')}`")
            if model.get("fields"):
                lines.append("")
                lines.append("| Field | Type |")
                lines.append("|-------|------|")
                for field in model["fields"]:
                    lines.append(f"| {field['name']} | {field.get('type', '?')} |")
            lines.append("")
    if api_specs:
        lines.append("## API Endpoints")
        lines.append("")
        lines.append("| Method | Path | File |")
        lines.append("|--------|------|------|")
        for spec in api_specs:
            lines.append(f"| {spec['method']} | `{spec['path']}` | `{spec.get('file', '?')}` |")
        lines.append("")
    lines.append("---")
    lines.append("*Generated by Loop Engineering SEED_DATA phase*")
    return "\n".join(lines)
