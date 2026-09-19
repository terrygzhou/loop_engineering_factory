"""
DISCOVER node: Accept project description, collect user input via interview,
generate discovery artifact for DEFINE phase.

Single async node with TWO sequential interrupt() calls:
  1. project_setup — project name + description + context folder
  2. interview — detailed requirements questions

Both interrupts fire from the same node context, avoiding LangGraph's
post-resume interrupt suppression (LangGraph 1.x: interrupt() in a
downstream node after resume does not yield __interrupt__).

When the context folder holds plain (non-ArcKit) documents, the interview
interrupt payload is pre-filled with answers extracted from those docs so
the user is not re-asked about information the docs already state; the
human still confirms. No docs / LLM fatal → payload is byte-identical to
the pre-prefill behavior. See `tests/test_discover_docs_prefill.py`.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

from langgraph.types import interrupt

from config.loader import config as _cfg
from tools.audit_logger import AuditLog
from tools.loader import build_skill_registry
from tools.stream_writer import safe_stream_writer

from graph.nodes.discover_scan import _collect_plain_docs  # noqa: F401
from graph.nodes.discover_scan import _detect_framework  # noqa: F401
from graph.nodes.discover_scan import _detect_project_type  # noqa: F401
from graph.nodes.discover_scan import _discover_dependencies  # noqa: F401
from graph.nodes.discover_scan import _discover_models  # noqa: F401
from graph.nodes.discover_scan import _discover_routes  # noqa: F401
from graph.nodes.discover_scan import _discover_specs  # noqa: F401
from graph.nodes.discover_scan import _discover_templates  # noqa: F401
from graph.nodes.discover_scan import _get_docker_status  # noqa: F401
from graph.nodes.discover_scan import _get_git_status  # noqa: F401
from graph.nodes.discover_scan import _inventory_tree  # noqa: F401
from graph.nodes.discover_scan import _scan_codebase  # noqa: F401

# Re-exports used by discover_interview sibling; test monkeypatch targets
# ("graph.nodes.discover.SkillTimer") must resolve through this module.
from graph.ui_bridge import SkillTimer  # noqa: F401

# Re-exports for the seam-split sibling modules (node-module-seams spec S9).
from graph.nodes.discover_prefill import _DOC_PREFILL_MAX_CHARS  # noqa: F401
from graph.nodes.discover_prefill import _extract_doc_prefill  # noqa: F401
from graph.nodes.discover_interview import _build_context  # noqa: F401
from graph.nodes.discover_interview import _generate_interview_questions  # noqa: F401
from graph.nodes.discover_interview import (  # noqa: F401
    _generate_requirement_template,
    _generate_requirement_via_fabric,
)
from graph.nodes.discover_interview import _load_improve_telemetry  # noqa: F401
from graph.nodes.discover_interview import _refine_idea  # noqa: F401

# Re-export invoke_skill at module level so existing test monkeypatch
# targets ("graph.nodes.discover.invoke_skill") still resolve. The actual
# call site now lives in discover_interview._generate_interview_questions.
from tools.llm import invoke_skill  # noqa: F401


async def discover_node(state: dict) -> dict:
    writer = safe_stream_writer()  # fallback for tests/CLI

    # ── State override wins if explicitly set; None = use config fallback ──
    override = state.get("auto_approve_override")
    auto_approve = override if override is not None else _cfg.workflow.auto_approve
    force_hil = bool(state.get("force_hil"))

    # E12: DISCOVER owns its HIL counter. Count the HIL pauses that complete
    # in this node execution (setup and/or interview) and write the running
    # total into the returned artifacts delta on every resume. The node
    # re-runs from the top on each resume, so a pause "completes" when its
    # interrupt() returns a value instead of suspending.
    hil_pauses_completed = 0

    # ── ArcKit artefact ingestion (EYW-171 data contract, EYW-181) ──
    # Pre-interrupt phase (§8): scan context_folder for ArcKit artefacts
    # (ADMP/REQ/STKE/OAAL/PRIN). When valid artefacts exist, project_setup +
    # interview_notes are auto-populated (§4.1) and both interrupts are
    # skipped — in every interactive run, including forced-HIL runs driven
    # by the Web bridge (arckit-web-ingestion). Only auto_approve (headless
    # stub path) keeps skipping the scan. No valid artefacts → fall through
    # to the HIL gates / generic interview fallback (§6.2 NO_ARTIFACTS).
    arckit_ctx = None
    # Explicit operator-supplied artefact list (Option 1+2): when present it
    # replaces glob discovery for this run; a HIL setup answer can add to it.
    arckit_files = [
        str(p).strip() for p in (state.get("arckit_artifacts") or []) if str(p).strip()
    ]
    if not auto_approve:
        try:
            from tools.arckit_loader import load_arckit_artifacts

            arckit_ctx = load_arckit_artifacts(
                state.get("context_folder") or "", files=arckit_files or None
            )
        except Exception as e:  # noqa: BLE001 — ingestion must never break DISCOVER
            logging.getLogger("discover").warning("ArcKit artefact scan failed: %s", e)
            arckit_ctx = None
    arckit_autopop = bool(arckit_ctx is not None and arckit_ctx.has_valid_artifacts)

    # ── 1. Project setup (interrupt #1) ──
    if auto_approve:
        project_name = state.get("project_name") or "Untitled"
        project_description = state.get("project_description", "")
        context_folder = state.get("context_folder", "")
    elif arckit_autopop and arckit_ctx is not None:
        # EYW-171 §1.1: ADMP → REQ precedence; state values (explicit inputs)
        # win over artefact-derived values.
        project_name = (
            state.get("project_name") or arckit_ctx.project_name or "Untitled"
        )
        project_description = (
            state.get("project_description") or arckit_ctx.project_description
        )
        context_folder = state.get("context_folder") or arckit_ctx.context_folder_hint
        writer(
            {
                "type": "progress",
                "phase": "DISCOVER",
                "step": "progress",
                "detail": f"  → ArcKit artefacts detected (project {arckit_ctx.project_id or '?'}): auto-populating setup + interview (EYW-171)",
                "ts": time.time(),
            }
        )
    elif state.get("discover_setup_done"):
        # Already collected on a previous run — skip setup interrupt
        project_name = state["project_name"]
        project_description = state.get("project_description", "")
        context_folder = state.get("context_folder", "")
    elif force_hil or not state.get("project_name"):
        setup = interrupt(
            {
                "type": "project_setup",
                "fields": [
                    {"key": "project_name", "label": "Project name", "required": True},
                    {
                        "key": "project_description",
                        "label": "Project description",
                        "required": True,
                    },
                    {
                        "key": "context_folder",
                        "label": "Existing codebase path (leave empty for greenfield)",
                        "required": False,
                    },
                    {
                        "key": "arckit_artifacts",
                        "label": "ArcKit artefact paths (one per line, optional)",
                        "required": False,
                    },
                ],
            }
        )
        # LangGraph may wrap resume payload in a list
        if isinstance(setup, list):
            setup = setup[0] if setup else {}
        # E12: setup HIL pause completed in this execution.
        hil_pauses_completed += 1
        project_name = setup.get("project_name", "")
        project_description = setup.get("project_description", "")
        context_folder = setup.get("context_folder", "")
        # HIL setup answer may supply the explicit artefact list (newline-
        # separated). Re-scan so auto-population + audit reflect it (§8).
        raw_artifacts = setup.get("arckit_artifacts") or ""
        artifact_lines = (
            raw_artifacts
            if isinstance(raw_artifacts, list)
            else str(raw_artifacts).splitlines()
        )
        arckit_files = [str(ln).strip() for ln in artifact_lines if str(ln).strip()]
        if arckit_files:
            try:
                from tools.arckit_loader import load_arckit_artifacts

                arckit_ctx = load_arckit_artifacts(context_folder, files=arckit_files)
            except Exception as e:  # noqa: BLE001 — ingestion must never break DISCOVER
                logging.getLogger("discover").warning(
                    "ArcKit artefact list load failed: %s", e
                )
                arckit_ctx = None
            arckit_autopop = bool(
                arckit_ctx is not None and arckit_ctx.has_valid_artifacts
            )
    else:
        project_name = state.get("project_name", "Untitled")
        project_description = state.get("project_description", "")
        context_folder = state.get("context_folder", "")

    # ── Derive project_folder ──
    project_folder = state.get("project_folder", "")
    if not project_folder:
        workspace = _cfg.paths.workspace_dir
        project_folder = os.path.join(workspace, project_name)

    # ── Improve mode: override with live deployment ──
    if state.get("improve_mode"):
        telemetry = _load_improve_telemetry(state, project_name)
        if telemetry:
            deployed_path = telemetry["project_path"]
            context_folder = deployed_path
            project_folder = deployed_path
            project_dir = Path(project_folder)
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / "specs").mkdir(parents=True, exist_ok=True)
            (project_dir / "build").mkdir(parents=True, exist_ok=True)
            (project_dir / "build" / "diagrams").mkdir(parents=True, exist_ok=True)
            return {
                "project_name": project_name,
                "project_description": project_description,
                "context_folder": context_folder,
                "project_folder": project_folder,
                "project_path": project_folder,
                "phase": "DISCOVER",
                "next_phase": "DEFINE",
                "discover_setup_done": True,
                "artifacts": {"improve_telemetry": json.dumps(telemetry, indent=2)},
            }

    # ── Create project directories ──
    project_dir = Path(project_folder)
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "specs").mkdir(parents=True, exist_ok=True)
    (project_dir / "build").mkdir(parents=True, exist_ok=True)
    (project_dir / "build" / "diagrams").mkdir(parents=True, exist_ok=True)

    # ── 2. Interview (interrupt #2) — same node, same checkpoint context ──
    if auto_approve:
        interview_notes = (
            f"Auto-generated interview for '{project_name}':\n"
            f"Description: {project_description}\n"
            f"Core behavior: Standard CRUD operations\n"
            f"API surface: RESTful endpoints\n"
        )
    elif state.get("discover_interview_done") or state.get("interview_notes"):
        interview_notes = state.get("interview_notes", "")
    elif arckit_autopop and arckit_ctx is not None:
        # EYW-171 §4.2: deterministic synthesis from the scanned artefacts —
        # no LLM call, no human interrupt.
        from tools.arckit_loader import synthesize_interview_notes

        interview_notes = synthesize_interview_notes(arckit_ctx)
    else:
        skills = build_skill_registry(_cfg.workflow.skill_registry_path)
        interview_skill = skills.get("interview-me", {})

        # Generate tailored questions from the project description, guided by the skill
        # (Run in thread to avoid blocking the event loop inside async node)
        interview_questions = await asyncio.to_thread(
            _generate_interview_questions,
            project_name,
            project_description,
            interview_skill.get("content", ""),
        )
        interview_prompts = (
            f"You are interviewing the user about their project: '{project_name}'.\n"
            f"Description: {project_description}\n\n"
            f"Ask the following questions. Tailor your follow-ups to their domain.\n"
            f"If a question is not applicable, skip it.\n\n"
        )

        # Doc pre-fill: when the context folder holds plain documents, extract
        # answers the docs already contain so the human is not re-asked about
        # them. The interrupt still fires — the human confirms the pre-filled
        # answers and answers the gaps. LLM fatal / no docs → no prefill key
        # (today's behavior, byte-identical).
        prefill, prefill_note = await asyncio.to_thread(
            _extract_doc_prefill,
            context_folder,
            project_name,
            project_description,
            interview_questions,
            interview_skill.get("content", ""),
        )
        interrupt_payload = {
            "type": "interview",
            "phase": "DISCOVER",
            "project_description": project_description,
            "instructions": interview_prompts if interview_skill else None,
            "questions": interview_questions,
        }
        if prefill:
            interrupt_payload["prefill"] = prefill
            interrupt_payload["questions"] = [
                q for q in interview_questions if q["key"] not in prefill
            ]
            interrupt_payload["note"] = prefill_note

        answers = interrupt(interrupt_payload)
        # E12: interview HIL pause completed in this execution.
        hil_pauses_completed += 1
        # LangGraph 1.x: if interrupt() is suppressed on resume (returns None),
        # auto-skip the interview and continue with empty notes.
        if answers is None:
            interview_notes = f"Auto-generated interview (suppressed):\nDescription: {project_description}\n"
        elif isinstance(answers, list):
            # LangGraph may wrap resume payload in a list
            answers = answers[0] if answers else {}
            interview_notes = answers.get("interview_notes", "")
        else:
            interview_notes = answers.get("interview_notes", "")

    # ── Scan existing codebase ──
    audit = AuditLog(state.get("cycle_id", "0"), state.get("trace_id"))
    audit.log_node_input(
        "DISCOVER",
        {
            "context_folder": state.get("context_folder", ""),
            "project_name": state.get("project_name", ""),
        },
    )
    context = _scan_codebase(context_folder, project_name, project_folder)

    # ── Idea refinement: sharpen interview notes into actionable concept ──
    idea_refinement = await asyncio.to_thread(
        _refine_idea, interview_notes, project_name, project_description, context, state
    )

    # ── Context engineering: build focused project context ──
    engineered_context = await asyncio.to_thread(
        _build_context,
        interview_notes,
        project_name,
        project_description,
        context,
        state,
    )

    # ── Generate discovery artifact ──
    requirement_md = await asyncio.to_thread(
        _generate_requirement_via_fabric,
        project_name=project_name,
        project_description=project_description,
        interview_notes=interview_notes,
        context=context,
        project_folder=project_folder,
        state=state,
    )

    req_path = project_dir / "requirement.md"
    req_path.write_text(requirement_md)

    # ── Return partial updates (reducers merge via _dict_merge) ──
    artifacts = {
        "idea_refinement": idea_refinement,
        "engineered_context": engineered_context,
        "project_context": json.dumps(context, indent=2, default=str),
        "requirement_md": requirement_md,
        "requirement_path": str(req_path),
        "interview_notes": interview_notes,
        "diagrams": {},
        "diagram_pngs": {},
    }
    # E12: DISCOVER owns discover_hil_count — write the running total into
    # this node's returned artifacts delta. Read the persisted value back
    # from state (the dispatching code reads it from state["artifacts"]);
    # add the pauses completed in this execution. When no HIL pause fired
    # (auto_approve / arckit autopop / already-done), hil_pauses_completed
    # is 0 and the persisted value passes through unchanged.
    persisted_hil_count = int(
        (state.get("artifacts") or {}).get("discover_hil_count", 0) or 0
    )
    artifacts["discover_hil_count"] = persisted_hil_count + hil_pauses_completed
    if arckit_ctx is not None:
        # EYW-171 §6.4 / §7: provenance audit + OAAL handoff to PLAN/BUILD
        artifacts["discover_artifact_audit"] = json.dumps(arckit_ctx.audit, indent=2)
        if arckit_ctx.sprint_map:
            artifacts["oaal_sprint_map"] = json.dumps(arckit_ctx.sprint_map, indent=2)
        # Tier-2 OAPR handoff (arckit-tier2-ingestion): backlog + D1–D10
        # open questions feed DEFINE/PLAN prompts and the ARCH_REVIEW gate.
        if arckit_ctx.product_backlog:
            artifacts["arckit_product_backlog"] = json.dumps(
                arckit_ctx.product_backlog, indent=2
            )
        if arckit_ctx.open_questions:
            artifacts["arckit_open_questions"] = json.dumps(
                arckit_ctx.open_questions, indent=2
            )
        # Tier-2 P1: strategy waves handoff (OASTR §4 wins, TRANS §1 fallback)
        if arckit_ctx.strategy_waves:
            artifacts["arckit_strategy_waves"] = json.dumps(
                arckit_ctx.strategy_waves, indent=2
            )
        # W3 arckit-build-context: advisory build-context carry-forward —
        # written only when the corresponding valid artefact exists; absent
        # artefacts leave the key unset (never sentinel values).
        if arckit_ctx.data_model:
            artifacts["arckit_data_model"] = json.dumps(arckit_ctx.data_model, indent=2)
        if arckit_ctx.integration_standards:
            artifacts["arckit_integration_standards"] = json.dumps(
                arckit_ctx.integration_standards, indent=2
            )
        if arckit_ctx.security_controls:
            artifacts["arckit_security_controls"] = json.dumps(
                arckit_ctx.security_controls, indent=2
            )
        if arckit_ctx.nfr_constraints:
            artifacts["arckit_nfr_constraints"] = json.dumps(
                arckit_ctx.nfr_constraints, indent=2
            )

    audit.log_node_output(
        "DISCOVER",
        {
            "requirement_path": str(req_path),
            "project_context_size": len(artifacts["project_context"]),
            "idea_refinement_size": len(idea_refinement),
            "engineered_context_size": len(engineered_context),
            "interview_notes_collected": bool(interview_notes),
        },
    )

    result = {
        "project_name": project_name,
        "project_description": project_description,
        "context_folder": context_folder,
        "project_folder": project_folder,
        "project_path": project_folder,
        "interview_notes": interview_notes,
        "discover_setup_done": True,
        "discover_interview_done": True,
        "artifacts": artifacts,
        "phase": "DISCOVER",
        "next_phase": "DEFINE",
        "diagrams": {},
        "diagram_status": "pending",
    }
    if arckit_files:
        # Persist the active explicit list so later phases / resume runs see
        # the authoritative ingestion source (Option 1+2).
        result["arckit_artifacts"] = arckit_files
    return result
