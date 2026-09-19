"""OpenHands agent prompt builder (seam split S7)."""

import json
import logging
from pathlib import Path

from graph.nodes.openhands_client import PROMPT_CHAR_LIMIT

logger = logging.getLogger(__name__)


# -- Prompt construction ----------------------------------------------
def _build_prompt(state: dict) -> str:
    """
    Construct the task prompt for the OpenHands agent.

    Pulls spec_refined and tasks from artifacts, truncates to avoid
    context overflow. Includes project_path for workspace alignment.
    """
    artifacts = state.get("artifacts", {})
    spec = (artifacts.get("spec_refined") or "")[:PROMPT_CHAR_LIMIT]
    tasks = (artifacts.get("tasks") or "")[:PROMPT_CHAR_LIMIT]
    project_path = state.get("project_path", "")
    project_name = state.get("project_name", "unknown")

    # Load solution.md if available (from PLAN phase)
    solution_md = artifacts.get("solution_md", "")
    if not solution_md and artifacts.get("solution_path"):
        try:
            import pathlib

            solution_md = pathlib.Path(artifacts["solution_path"]).read_text()
        except Exception:
            logger.debug("solution_path read failed", exc_info=True)

    # P0.5 (arckit-tier2-ingestion): human answers captured at the
    # ARCH_REVIEW gate surface as advisory "Review supplements". Absent /
    # empty key -> byte-identical prompt to before this change.
    review_answers = artifacts.get("arch_review_answers") or ""
    supplements = ""
    if review_answers:
        supplements = (
            "\nREVIEW SUPPLEMENTS (human answers captured at ARCH_REVIEW "
            "- advisory; treat as authoritative guidance where they answer "
            "open design questions):\n" + review_answers[:PROMPT_CHAR_LIMIT]
        )

    # W3 arckit-build-context: advisory ArcKit build-context sections,
    # emitted ONLY for keys that are set; when none is set the prompt is
    # byte-identical to a run with no ArcKit context. Advisory
    # (non-routing) context — the build_report.json manifest contract
    # (Decision 1) and the BUILD retry budget are unchanged.
    arckit_sections = []
    for key, header in (
        ("arckit_product_backlog", "PRODUCT BACKLOG"),
        ("arckit_strategy_waves", "STRATEGY WAVES"),
        ("arckit_data_model", "DATA MODEL"),
        ("arckit_integration_standards", "INTEGRATION STANDARDS"),
        ("arckit_security_controls", "SECURITY CONTROLS"),
        ("arckit_nfr_constraints", "NFR CONSTRAINTS"),
    ):
        raw = artifacts.get(key)
        if raw:
            arckit_sections.append(
                f"\nARCKIT {header} (advisory context - conform where "
                f"feasible):\n{str(raw)[:PROMPT_CHAR_LIMIT]}"
            )
    arckit_context = "".join(arckit_sections)

    # W4 plan-sequence-view: advisory architecture diagram views (the 4 base
    # views + any sequence_* use-case views). Emitted only for keys that are
    # present AND whose files are readable; when no diagrams are present the
    # prompt is byte-identical to the pre-change prompt. Deliberately no
    # "ARCKIT" marker in this section (W3 baseline tests assert its absence).
    diagram_blocks: list[str] = []
    diagrams = artifacts.get("diagrams")
    if isinstance(diagrams, dict):
        for key in sorted(diagrams):
            try:
                content = Path(str(diagrams.get(key))).read_text()[:PROMPT_CHAR_LIMIT]
            except (OSError, TypeError):
                continue
            diagram_blocks.append(f"### {key}\n{content}")
    diagram_context = ""
    if diagram_blocks:
        diagram_context = (
            "\nARCHITECTURE DIAGRAMS (reference views - advisory):"
            + "".join("\n" + block for block in diagram_blocks)
        )

    # W5 verify-acceptance-criteria: failing acceptance tests from the most
    # recent VERIFY run surface as retry guidance (advisory context).
    # Absent / empty / no-failures -> byte-identical prompt to before.
    failing_acceptance: list[dict] = []
    raw_results = artifacts.get("acceptance_results")
    if raw_results:
        try:
            results = (
                json.loads(raw_results) if isinstance(raw_results, str) else raw_results
            )
            if isinstance(results, dict):
                failing_acceptance = [
                    rec
                    for rec in results.values()
                    if isinstance(rec, dict) and rec.get("passed") is False
                ]
        except (ValueError, TypeError):
            failing_acceptance = []
    acceptance_context = ""
    if failing_acceptance:
        lines = [
            f"- {rec.get('id', '?')}: check `{rec.get('check', '')}` — "
            f"expect: {rec.get('expect', '')}"
            for rec in failing_acceptance
        ]
        acceptance_context = (
            "\nACCEPTANCE TEST FAILURES (retry - make these pass):\n" + "\n".join(lines)
        )

    return f"""You are a senior software engineer building a project end-to-end.

PROJECT: {project_name}
WORKSPACE: {project_path}
BUILD_REPORT_PATH: {project_path}/build_report.json

INSTRUCTIONS:
1. Generate the complete source code for the project
2. Create unit tests for each module
3. Write configuration files (docker-compose, requirements.txt, etc.)
4. Run the tests and fix any failures
5. Write a seed script for database initialization
6. Perform a security review of the generated code
7. For any user-facing UI (web pages, dashboards, forms, components), apply production-grade frontend engineering: accessible (WCAG 2.1 AA), responsive, semantic HTML, and visually polished — not a generic "AI-generated" look. Honor the spec's UI & User Experience section (screens, flows, design constraints) when present.

MANDATORY MACHINE-READABLE RESULT:
When you finish, you MUST write a file named build_report.json in the project
root containing ONLY valid JSON with this exact shape:
    {{
      "status": "pass" | "fail" | "partial",
      "test_results": "human-readable summary of test run",
      "files": ["relative/path/to/file", ...],
      "errors": ["first error if any", ...]
    }}
- "status" is "pass" only if tests run and all pass; "fail" if the build or
  tests cannot complete; "partial" if code exists but some tests fail.
- This file is parsed by the orchestrator and is the source of truth for
  whether the build succeeded. Keep it valid JSON; do not add commentary.

OUTPUT FORMAT:
For each file, output in this format:
=== FILE: relative/path/to/file.py ===
```python
<complete file contents>
```

After generating all files, run tests and report:
- Which tests passed/failed
- Any errors encountered
- Files created/modified

SPECIFICATION:
{spec}

TASKS:
{tasks}
{supplements}{arckit_context}{diagram_context}{acceptance_context}
"""
