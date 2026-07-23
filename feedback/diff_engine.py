"""
Diff engine: analyze feedback and generate proposed skill config updates.
"""
import re
import json
import yaml



def generate_config_diffs(cycle_records: list, guardrails: dict, llm=None) -> dict:
    """
    Analyze cycle metrics and feedback to generate proposed config updates.
    Returns a dict with overall_assessment, changes, and risk_level.
    Falls back to empty changes in dry-run mode.
    """
    if not cycle_records:
        return {
            "overall_assessment": "No cycle records to analyze",
            "changes": [],
            "risk_level": "none",
        }

    # Dry-run mode: return placeholder without LLM
    if llm is None:
        print("  ⚠ Dry-run mode: skipping LLM-based config diff generation")
        return {
            "overall_assessment": "Dry-run mode — no config changes proposed",
            "changes": [],
            "risk_level": "none",
        }

    # Aggregate key metrics across cycles
    total_revisions = sum(
        int(c.get("metrics", {}).get("review_revisions", 0))
        for c in cycle_records
    )
    total_findings = sum(
        int(c.get("metrics", {}).get("security_findings", 0))
        for c in cycle_records
    )
    avg_confidence = (
        sum(float(c.get("metrics", {}).get("spec_confidence", 0)) for c in cycle_records)
        / len(cycle_records)
    ) if cycle_records else 0

    # Build analysis prompt
    analysis_prompt = f"""Analyze the following development cycle metrics and propose config updates:

Metrics:
- Total review revisions: {total_revisions}
- Total security findings: {total_findings}
- Average spec confidence: {avg_confidence:.2f}

Guardrails:
{json.dumps(guardrails, indent=2, default=str)}

Propose specific skill config changes (max 3) that would improve outcomes.
For each change, specify:
- skill: which skill config to update
- change: what to change (e.g., threshold, trigger word, ordering)
- rationale: why this change helps
- risk_level: low/medium/high

Return JSON with:
{{
  "overall_assessment": "summary of findings",
  "changes": [
    {{"skill": "...", "change": "...", "rationale": "...", "risk_level": "low/medium/high"}}
  ],
  "risk_level": "overall risk level"
}}
"""

    try:
        from langchain_core.messages import SystemMessage, HumanMessage
        response = llm.invoke([
            SystemMessage(content="You are a meta-agent optimizing an AI development workflow. Output JSON only."),
            HumanMessage(content=analysis_prompt),
        ])
        # Parse JSON response
        try:
            result = json.loads(response.content)
            return result
        except (json.JSONDecodeError, KeyError):
            print(f"  ⚠ Could not parse LLM response as JSON")
            return {
                "overall_assessment": response.content[:200],
                "changes": [],
                "risk_level": "unknown",
            }
    except Exception as e:
        print(f"  ⚠ LLM invocation failed: {e}")
        return {
            "overall_assessment": f"Error: {e}",
            "changes": [],
            "risk_level": "error",
        }


def dry_run_validation(diffs: dict) -> bool:
    """
    Validate proposed changes against guardrails before human approval.
    Returns True if safe to proceed, False otherwise.
    """
    for change in diffs.get("changes", []):
        # Check for security-sensitive changes
        change_text = json.dumps(change).lower()
        for keyword in ["auth", "payment", "billing", "secret", "api_key"]:
            if keyword in change_text and change.get("risk_level") == "high":
                print(f"  ✗ Security-sensitive change blocked: {change.get('skill', 'unknown')}")
                return False
    return True


def apply_yaml_diff(config_path: str, diffs: dict) -> bool:
    """
    Apply config diffs to a YAML file. Parses change descriptions for
    threshold updates, key additions/removals, and value modifications.
    Returns True on success.
    """
    # Handle prompt template updates (Python file)
    for change in diffs.get("changes", []):
        skill_name = change.get("skill", "")
        if skill_name in ("interview_me", "spec_generation", "api_and_interface_design"):
            return apply_prompt_diff(skill_name, diffs)

    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f) or {}

        for change in diffs.get("changes", []):
            skill_name = change.get("skill", "")
            change_desc = change.get("change", "")
            rationale = change.get("rationale", "")

            # Find the target key in config (top-level or nested)
            target = _find_config_target(config, skill_name)

            if target is None:
                print(f"  ⚠ Config key '{skill_name}' not found — skipping")
                continue

            if isinstance(target, dict):
                # Parse threshold changes: "threshold X from A to B" or "threshold > X"
                threshold_match = re.search(
                    r'threshold\s*(\w+)\s*(from|to)\s*([\d.]+)',
                    change_desc.lower()
                )
                if threshold_match:
                    key = threshold_match.group(1)
                    value = _parse_numeric(threshold_match.group(3))
                    if key in target:
                        old_val = target[key]
                        target[key] = value
                        print(f"     → {skill_name}.{key}: {old_val} → {value}")

                # Parse key addition: "add X = Y" or "new X: Y"
                add_match = re.search(
                    r'(?:add|new)\s+(\w+)\s*[=:]\s*([\d.\w]+)',
                    change_desc.lower()
                )
                if add_match and not threshold_match:
                    key = add_match.group(1)
                    value = _parse_numeric(add_match.group(2))
                    if value is None:
                        value = add_match.group(2)
                    target[key] = value
                    print(f"     → {skill_name}: added {key} = {value}")

                # Parse removal: "remove X" or "delete X"
                rm_match = re.search(r'(?:remove|delete)\s+(\w+)', change_desc.lower())
                if rm_match and not threshold_match and not add_match:
                    key = rm_match.group(1)
                    if key in target:
                        del target[key]
                        print(f"     → {skill_name}: removed {key}")

                # Generic value change: "change X to Y" or "set X to Y"
                set_match = re.search(r'(?:change|set|update)\s+(\w+)\s+to\s+([\d.\w]+)',
                                      change_desc.lower())
                if set_match and not threshold_match and not add_match and not rm_match:
                    key = set_match.group(1)
                    value = _parse_numeric(set_match.group(2))
                    if value is None:
                        value = set_match.group(2)
                    target[key] = value
                    print(f"     → {skill_name}.{key} = {value}")

                # Fallback: just stamp the rationale
                target["_last_updated"] = f"{rationale} [{diffs.get('overall_assessment', '')}]"
            else:
                # Scalar value — just update
                print(f"     → {skill_name}: skipping (non-dict config entry)")

        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        print(f"  ✓ Config diff applied to {config_path}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to apply config diff: {e}")
        import traceback
        traceback.print_exc()
        return False


def apply_prompt_diff(template_name: str, diffs: dict) -> bool:
    """
    Apply prompt template diffs from REFLECT analysis.
    Reads config/prompt_templates.py, finds the target template,
    and applies the LLM-suggested changes.
    Returns True on success.
    """
    import importlib
    import inspect
    import os

    try:
        template_file = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                     "config", "prompt_templates.py")
        with open(template_file, "r") as f:
            content = f.read()

        # Find the target template in the file
        pattern = rf'({template_name}\s*=\s*"""[^\"]*""")'
        match = re.search(pattern, content, re.DOTALL)
        if not match:
            print(f"  ✗ Template '{template_name}' not found in {template_file}")
            return False

        current_template = match.group(1)
        for change in diffs.get("changes", []):
            if change.get("skill") == template_name:
                change_desc = change.get("change", "")
                rationale = change.get("rationale", "")
                # Replace the template content with the LLM's improved version
                # The change description should contain the revised prompt text
                new_template = f'{template_name} = """{change_desc}"""'
                content = content.replace(current_template, new_template)
                print(f"     → {template_name}: updated ({rationale})")

        with open(template_file, "w") as f:
            f.write(content)
        print(f"  ✓ Prompt diff applied to {template_file}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to apply prompt diff: {e}")
        import traceback
        traceback.print_exc()
        return False


def _find_config_target(config: dict, skill_name: str):
    """Find a config entry by name — search top-level and one level deep."""
    if skill_name in config:
        return config[skill_name]
    for key, val in config.items():
        if isinstance(val, dict) and skill_name in val:
            return val[skill_name]
    return None


def _parse_numeric(value: str):
    """Try to parse a string as int or float. Returns None if not numeric."""
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return None
