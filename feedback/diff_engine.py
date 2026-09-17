"""
Diff engine: analyze feedback and generate proposed skill config updates.
"""

import json
import re

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
        int(c.get("metrics", {}).get("review_revisions", 0) or 0) for c in cycle_records
    )
    total_findings = sum(
        int(c.get("metrics", {}).get("security_findings", 0) or 0)
        for c in cycle_records
    )
    avg_confidence = (
        (
            sum(
                float(c.get("metrics", {}).get("spec_confidence", 0) or 0)
                for c in cycle_records
            )
            / len(cycle_records)
        )
        if cycle_records
        else 0
    )

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
        from langchain_core.messages import HumanMessage, SystemMessage

        response = llm.invoke(
            [
                SystemMessage(
                    content="You are a meta-agent optimizing an AI development workflow. Output JSON only."
                ),
                HumanMessage(content=analysis_prompt),
            ]
        )
        # Parse JSON response
        try:
            result = json.loads(response.content)
            return result
        except (json.JSONDecodeError, KeyError):
            print("  ⚠ Could not parse LLM response as JSON")
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
                print(
                    f"  ✗ Security-sensitive change blocked: {change.get('skill', 'unknown')}"
                )
                return False
    return True


def apply_yaml_diff(config_path: str, diffs: dict) -> bool:
    """
    Apply config diffs to a YAML file. Parses change descriptions for
    threshold updates, key additions/removals, and value modifications.
    Returns True on success.
    """
    # Handle prompt template updates (Python file).  The structured
    # shape ({section, key, op, value}) routes on the section name;
    # the legacy changes-list shape routes on the skill name.
    section = diffs.get("section", "")
    if section in ("interview_me", "spec_generation", "api_and_interface_design"):
        return apply_prompt_diff(section, diffs)
    for change in diffs.get("changes", []):
        skill_name = change.get("skill", "")
        if skill_name in ("interview_me", "spec_generation", "api_and_interface_design"):
            return apply_prompt_diff(skill_name, diffs)

    try:
        with open(config_path) as f:
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
                    r"threshold\s*(\w+)\s*(from|to)\s*([\d.]+)", change_desc.lower()
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
                    r"(?:add|new)\s+(\w+)\s*[=:]\s*([\d.\w]+)", change_desc.lower()
                )
                if add_match and not threshold_match:
                    key = add_match.group(1)
                    value = _parse_numeric(add_match.group(2))
                    if value is None:
                        value = add_match.group(2)
                    target[key] = value
                    print(f"     → {skill_name}: added {key} = {value}")

                # Parse removal: "remove X" or "delete X"
                rm_match = re.search(r"(?:remove|delete)\s+(\w+)", change_desc.lower())
                if rm_match and not threshold_match and not add_match:
                    key = rm_match.group(1)
                    if key in target:
                        del target[key]
                        print(f"     → {skill_name}: removed {key}")

                # Generic value change: "change X to Y" or "set X to Y"
                set_match = re.search(
                    r"(?:change|set|update)\s+(\w+)\s+to\s+([\d.\w]+)",
                    change_desc.lower(),
                )
                if set_match and not threshold_match and not add_match and not rm_match:
                    key = set_match.group(1)
                    value = _parse_numeric(set_match.group(2))
                    if value is None:
                        value = set_match.group(2)
                    target[key] = value
                    print(f"     → {skill_name}.{key} = {value}")

                # Fallback: just stamp the rationale
                target["_last_updated"] = (
                    f"{rationale} [{diffs.get('overall_assessment', '')}]"
                )
            else:
                # Scalar value — just update
                print(f"     → {skill_name}: skipping (non-dict config entry)")

        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        print(f"  ✓ Config diff applied to {config_path}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to apply config diff: {e}")
        import traceback

        traceback.print_exc()
        return False


def _template_file_path() -> str:
    """Return the absolute path to ``config/prompt_templates.py``.

    Indirected so tests can monkeypatch the location.
    """
    import os

    return os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "config", "prompt_templates.py"
    )


def _escape_template_body(value: str) -> str:
    """Escape value so it is safe inside a triple-quoted assignment
    in a .py source file.

    Escapes backslashes first (order matters: an escaped backslash
    must not re-escape the quote escapes that follow), then
    double-quotes.  Newlines are left literal (triple-quoted
    strings allow raw newlines, and they are the most readable form).

    The result is always safe to splice into a triple-quoted
    assignment.  Even a value containing a literal triple-quote
    sequence cannot terminate the assignment early, because every
    quote character in the value is escaped.
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _quote_aware_template_regex(template_name: str) -> re.Pattern:
    """Build a quote-aware regex that matches the existing
    triple-quoted assignment for ``template_name`` in
    ``config/prompt_templates.py``.

    The body may contain double-quote characters — the previous
    naive character-class body was broken for real templates.
    This match uses a non-greedy body up to the closing
    triple-quote, with ``re.DOTALL`` so newlines in the body
    are handled.
    """
    return re.compile(
        r"(?P<match>" + re.escape(template_name)
        + r"\s*=\s*\"\"\".*?\"\"\")",
        re.DOTALL,
    )


def _extract_structured_value(diffs: dict, template_name: str) -> str | None:
    """Extract the new template body from ``diffs``.

    Accepts two shapes (in priority order):
    1. **Structured** — ``{"section": <template_name>,
       "key": "template_body", "op": "replace",
       "value": <new text>}`` (Decision 4, the W3 shape already
       used for config diffs).  The ``section`` must name the
       target template.
    2. **Legacy** — ``{"changes": [{"skill": <template_name>,
       "change": <new text>, "rationale": ..., ...}, ...]}``.
       Each change is routed through the structured path.  This
       shape is preserved for backward compatibility with existing
       REFLECT call sites.

    Returns the new body text, or ``None`` if no matching value is
    present.
    """
    # Structured shape — same shape REFLECT emits for config diffs.
    if (
        diffs.get("section")
        and diffs.get("key") == "template_body"
        and diffs.get("op") == "replace"
        and "value" in diffs
        and diffs.get("section") == template_name
    ):
        return diffs.get("value")

    # Legacy ``changes`` list shape — route each entry through the
    # structured path.  Only the entry whose ``skill`` matches
    # ``template_name`` is applied.
    for change in diffs.get("changes", []):
        if change.get("skill") == template_name:
            return change.get("change", "")

    return None


def apply_prompt_diff(template_name: str, diffs: dict) -> bool:
    """
    Apply prompt template diffs from REFLECT analysis.
    Reads config/prompt_templates.py, finds the target template,
    and applies the structured (or legacy-routed) new body.
    Returns True on success.
    """
    import logging

    log = logging.getLogger(__name__)
    try:
        template_file = _template_file_path()
        with open(template_file) as f:
            content = f.read()

        new_value = _extract_structured_value(diffs, template_name)
        if new_value is None:
            print(f"  ✗ No template_body value for '{template_name}' in diffs")
            log.warning(
                "apply_prompt_diff: no template_body value for %r in diffs",
                template_name,
            )
            return False

        # Quote-aware regex: matches the existing triple-quoted
        # body even when it contains double-quote characters.
        pattern = _quote_aware_template_regex(template_name)
        match = pattern.search(content)
        if not match:
            print(f"  ✗ Template '{template_name}' not found in {template_file}")
            log.warning(
                "apply_prompt_diff: template %r not found in %s",
                template_name,
                template_file,
            )
            return False

        current_template = match.group(1)

        # Build the replacement by escaping the value (triple-quote-
        # safe: backslashes first, then double-quotes; raw newlines
        # are preserved inside the triple-quoted literal).
        escaped_value = _escape_template_body(new_value)
        new_template = f'{template_name} = """{escaped_value}"""'
        candidate = content.replace(current_template, new_template, 1)

        # Validate the candidate BEFORE writing to disk — a
        # non-compiling replacement leaves the original file
        # byte-identical (spec scenario "Bad replacement is
        # rejected"; the rejection is logged, not raised).
        try:
            compile(candidate, template_file, "exec")
        except SyntaxError as e:
            print(
                f"  ✗ Prompt diff for '{template_name}' rejected — "
                f"candidate file does not compile: {e}"
            )
            log.warning(
                "apply_prompt_diff: candidate for %r rejected by compile(): %s",
                template_name,
                e,
            )
            return False

        with open(template_file, "w") as f:
            f.write(candidate)
        print(f"  ✓ Prompt diff applied to {template_file}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to apply prompt diff: {e}")
        log.exception("apply_prompt_diff: failed to apply diff for %r", template_name)
        return False


def _find_config_target(config: dict, skill_name: str):
    """Find a config entry by name — search top-level and one level deep."""
    if skill_name in config:
        return config[skill_name]
    for val in config.values():
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
