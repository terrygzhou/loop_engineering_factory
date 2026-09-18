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
import re
import subprocess
import time
from pathlib import Path

import httpx
from langgraph.types import interrupt

from config.loader import config as _cfg
from graph.ui_bridge import SkillTimer
from tools.audit_logger import AuditLog
from tools.llm import invoke_skill
from tools.loader import build_skill_registry
from tools.stream_writer import safe_stream_writer


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
            artifacts["arckit_data_model"] = json.dumps(
                arckit_ctx.data_model, indent=2
            )
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


# ── Helpers ──


def _generate_interview_questions(
    project_name: str, project_description: str, skill_content: str = ""
) -> list:
    """Generate domain-specific interview questions from the project description.

    Uses the interview-me skill (when available) as the structured question
    framework, then tailors each category to the project domain via LLM.
    Falls back to generic questions if description is too short or LLM fails.
    """
    generic_questions = [
        {
            "key": "core_behavior",
            "label": "Core Behavior",
            "prompt": "What does this feature do? What are the primary user actions?",
        },
        {
            "key": "data_model",
            "label": "Data Model",
            "prompt": "What entities and fields are involved? Any relationships between them?",
        },
        {
            "key": "api_surface",
            "label": "API Surface",
            "prompt": "What endpoints, HTTP methods, and auth requirements do you need?",
        },
        {
            "key": "integration",
            "label": "Integration",
            "prompt": "Does this integrate with external services, databases, or third-party APIs?",
        },
        {
            "key": "ui_template",
            "label": "UI",
            "prompt": "Any specific UI requirements, templates, or styling preferences?",
        },
        {
            "key": "validation",
            "label": "Validation",
            "prompt": "What input validation rules or data integrity constraints apply?",
        },
        {
            "key": "edge_cases",
            "label": "Edge Cases",
            "prompt": "Are there known edge cases, error paths, or failure modes to handle?",
        },
        {
            "key": "non_functional",
            "label": "Non-Functional",
            "prompt": "Any performance, security, or monitoring requirements?",
        },
    ]

    # If description is too short, just use generic questions
    if len(project_description.strip()) < 20:
        return generic_questions

    # Build LLM prompt — grounded in the skill's interview framework
    skill_framework = ""
    if skill_content:
        skill_framework = (
            f"The following skill defines the interview framework. Use its "
            f"categories (Core Behavior, Data Model, API Surface, Integration, "
            f"Validation, UI/Template, Deployment, Edge Cases, Non-Functional) "
            f"as the structure, then tailor each question to this project's domain.\n\n"
            f"Interview framework:\n{skill_content}\n\n"
        )

    prompt = (
        f"You are designing an interview for a new software project.\n\n"
        f"{skill_framework}"
        f"Project: {project_name}\n"
        f"Description: {project_description}\n\n"
        f"Generate 6-8 interview questions that cover the key categories above, "
        f"but make each question specific to this project's domain.\n"
        f"For example, if the project mentions Google Calendar integration,\n"
        f"ask about OAuth scopes, sync direction, conflict resolution, etc.\n\n"
        f"Output ONLY a JSON array of question objects with this structure:\n"
        f'[{{"key": "area_name", "label": "Display Label", "prompt": "The specific question?"}}, ...]\n\n'
        f"Rules:\n"
        f"- Use the 'key' field as a short snake_case identifier (e.g. calendar_sync)\n"
        f"- Map each question to one of the framework categories above\n"
        f"- Make each question specific to the project, not generic\n"
        f"- Include at least one question about data model, integration/APIs, and user workflow\n"
        f"- Keep labels to 2-4 words\n"
        f"- Output only the JSON array, nothing else"
    )

    try:
        from tools.llm import invoke_skill

        result = invoke_skill(
            "You are an expert software requirements interviewer.",
            prompt,
            "",
            llm=None,
        )
        # Parse the JSON array from LLM output
        json_match = re.search(r"\[.*\]", result, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            if isinstance(parsed, list) and len(parsed) >= 3:
                # Ensure each question has required fields
                cleaned = []
                for q in parsed:
                    if isinstance(q, dict) and q.get("key") and q.get("prompt"):
                        cleaned.append(
                            {
                                "key": q["key"],
                                "label": q.get(
                                    "label", q["key"].replace("_", " ").title()
                                ),
                                "prompt": q["prompt"],
                            }
                        )
                if cleaned:
                    return cleaned
    except Exception as e:
        logging.getLogger("discover").warning(
            "Interview question generation failed: %s", e
        )

    # Fall back to generic questions with project context
    return [
        {
            "key": "core_behavior",
            "label": "Core Behavior",
            "prompt": f"For '{project_name}', what are the primary user actions and workflows?",
        },
        {
            "key": "data_model",
            "label": "Data Model",
            "prompt": "What entities does this project manage? What fields and relationships?",
        },
        {
            "key": "integration",
            "label": "Integration",
            "prompt": "The description mentions specific services — which external APIs or databases need integration?",
        },
        {
            "key": "api_surface",
            "label": "API Surface",
            "prompt": "What REST endpoints or GraphQL queries should this expose?",
        },
        {
            "key": "auth_security",
            "label": "Auth & Security",
            "prompt": "Does this require authentication, authorization, or data encryption?",
        },
        {
            "key": "ui_template",
            "label": "UI",
            "prompt": "What does the user interface look like? Any existing design system or templates?",
        },
        {
            "key": "edge_cases",
            "label": "Edge Cases",
            "prompt": "What are the trickiest scenarios or failure modes for this project?",
        },
        {
            "key": "deployment",
            "label": "Deployment",
            "prompt": "Any Docker, infrastructure, or hosting requirements?",
        },
    ]


def _collect_plain_docs(context_folder: str) -> list:
    """Collect plain (non-ArcKit) document files under `context_folder`.

    Returns up to 20 files, each truncated to a total budget, so the
    extraction prompt stays bounded. Excludes files whose names match the
    ArcKit canonical pattern (those belong to the auto-populate path) and
    common code/build directories.
    """
    import re as _re

    base = Path(context_folder)
    if not base.is_dir():
        return []
    arckit_re = _re.compile(r"^ARC-\d{3}-")
    skip_dirs = {"node_modules", ".git", "__pycache__", ".venv", "venv"}
    out: list[Path] = []
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in {
            ".md",
            ".txt",
            ".adoc",
            ".yaml",
            ".yml",
        }:
            continue
        if arckit_re.match(p.name):
            continue
        if skip_dirs & set(p.parts):
            continue
        out.append(p)
        if len(out) >= 20:
            break
    return out


_DOC_PREFILL_MAX_CHARS = 40_000


def _extract_doc_prefill(
    context_folder: str,
    project_name: str,
    project_description: str,
    interview_questions: list,
    skill_content: str,
) -> tuple[dict | None, str | None]:
    """Extract interview answers from plain documents in `context_folder`.

    Returns (seed_dict_or_None, note_or_None). `seed_dict` maps question key
    → answer text for categories the docs already cover. On no docs, LLM
    fatal, or unparseable output, returns (None, None) so the caller keeps
    today's full-interview behavior unchanged.
    """
    files = _collect_plain_docs(context_folder)
    if not files:
        return None, None

    chunks: list[str] = []
    total = 0
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        if not text.strip():
            continue
        room = _DOC_PREFILL_MAX_CHARS - total
        if room <= 0:
            break
        text = text[:room]
        chunks.append(f"### {f.name}\n{text}")
        total += len(text)
    if not chunks:
        return None, None

    doc_text = "\n\n".join(chunks)
    cat_keys = [q["key"] for q in interview_questions] or [
        "core_behavior",
        "data_model",
        "api_surface",
        "integration",
        "ui_template",
        "validation",
        "edge_cases",
        "non_functional",
    ]
    framework = ""
    if skill_content:
        framework = (
            f"The interview framework defines these categories: "
            f"{', '.join(cat_keys)}.\n\n"
        )
    prompt = (
        f"You are extracting interview answers from existing project documents "
        f"so the user is not re-asked about information the docs already state.\n\n"
        f"{framework}"
        f"Project: {project_name}\nDescription: {project_description}\n\n"
        f"Documents:\n{doc_text}\n\n"
        f"Output ONLY a JSON object with this shape:\n"
        f'{{"seed": {{"<category>": "<answer from docs>", ...}}, '
        f'"unanswered": ["<category>", ...]}}\n\n'
        f"Rules:\n"
        f"- Only fill a category in `seed` if the documents clearly state it.\n"
        f"- Keep each answer to 1-3 sentences, quoted or summarized from the docs.\n"
        f"- List every category not answered by the docs in `unanswered`.\n"
        f"- Use these category keys: {', '.join(cat_keys)}.\n"
        f"- Output only the JSON object, nothing else."
    )
    try:
        result = invoke_skill(
            "You are an expert requirements extractor.",
            prompt,
            "",
            llm=None,
        )
    except Exception as e:  # noqa: BLE001
        logging.getLogger("discover").warning(
            "Doc prefill extraction failed: %s", e
        )
        return None, None
    if not result:
        return None, None
    try:
        m = re.search(r"\{.*\}", result, re.DOTALL)
        if not m:
            return None, None
        parsed = json.loads(m.group())
        seed = parsed.get("seed") or {}
        if not isinstance(seed, dict) or not seed:
            return None, None
        seed = {k: str(v) for k, v in seed.items() if str(v).strip()}
        if not seed:
            return None, None
        note = (
            f"{len(files)} document(s) under the context folder pre-filled "
            f"{len(seed)} interview answer(s). Confirm or correct below; "
            f"unanswered categories remain as questions."
        )
        return seed, note
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logging.getLogger("discover").warning(
            "Doc prefill output unparseable: %s", e
        )
        return None, None


def _scan_codebase(context_folder: str, project_name: str, project_folder: str) -> dict:
    if context_folder and Path(context_folder).is_dir():
        project_type = _detect_project_type(context_folder)
        return {
            "project_path": project_folder,
            "project_name": project_name,
            "project_type": project_type,
            "tree": _inventory_tree(context_folder),
            "routes": _discover_routes(context_folder, project_type),
            "models": _discover_models(context_folder, project_type),
            "templates": _discover_templates(context_folder, project_type),
            "dependencies": _discover_dependencies(context_folder),
            "git": _get_git_status(context_folder),
            "docker": _get_docker_status(context_folder),
            "specs": _discover_specs(context_folder),
        }
    return {
        "project_path": project_folder,
        "project_name": project_name,
        "project_type": "greenfield",
        "tree": {},
        "routes": [],
        "models": [],
        "templates": [],
        "dependencies": {},
        "git": {"branch": "greenfield"},
        "docker": {"services": []},
        "specs": {},
    }


def _generate_requirement_via_fabric(
    project_name,
    project_description,
    interview_notes,
    context,
    project_folder,
    state: dict | None = None,
):
    skills = build_skill_registry(_cfg.workflow.skill_registry_path)
    fabric_skill = skills.get("fabric-prompts", {})

    # Wire coding-principles as context-aware refinement
    principles_skill = skills.get("coding-principles", {})
    principles_context = ""
    if principles_skill and project_description and state:
        principles_prompt = (
            f"Given this project context, extract relevant coding principles:\n"
            f"Project: {project_name}\n"
            f"Description: {project_description}\n"
            f"Type: {context.get('project_type', 'greenfield')}\n\n"
            "Output key technical principles and conventions that should guide implementation."
        )
        timer = SkillTimer("coding-principles")
        principles_context = (
            invoke_skill(principles_skill["content"], principles_prompt, "", llm=None)
            or ""
        )
        timer.complete()
        principles_context = f"\n\n## Coding Principles\n{principles_context[:1000]}\n"

    if fabric_skill:
        fabric_prompt = (
            f"Generate a structured discovery report for DEFINE phase.\n\n"
            f"Project: {project_name}\nDescription: {project_description}\n"
            f"Interview notes:\n{interview_notes}\n"
            f"{principles_context}\n\n"
            f"Output: Markdown with sections: Project Overview, Core Behavior, "
            f"Data Model, API Surface, Integration Requirements, Non-Functional, Edge Cases, Constraints"
        )
        fabric_timer = SkillTimer("fabric-prompts")
        result = invoke_skill(fabric_skill["content"], fabric_prompt, "", llm=None)
        fabric_timer.complete()
        if not result:
            # LLM fatal (None) — degrade to the deterministic template
            return _generate_requirement_template(
                project_name,
                project_description,
                interview_notes,
                context,
                project_folder,
            )
        md = result.strip()
        if md.startswith("```"):
            md = re.sub(r"^```[a-z]*\n", "", md).rstrip("`")
            if md.endswith("\n```"):
                md = md[:-4]
        return md
    return _generate_requirement_template(
        project_name, project_description, interview_notes, context, project_folder
    )


def _generate_requirement_template(
    project_name, project_description, interview_notes, context, project_folder
):
    return (
        f"# {project_name} — Discovery Report\n\n"
        f"## Project Overview\n{project_description or '(none)'}\n\n"
        f"## Core Behavior\n{interview_notes.split(chr(10))[0] if interview_notes else '(none)'}\n\n"
        f"## Data Model\n- (from context or interview)\n\n"
        f"## API Surface\n- (to be determined)\n\n"
        f"## Non-Functional\n- (from interview)\n\n"
        f"## Edge Cases\n- (to be determined)\n\n"
        f"## Constraints\n- `{project_folder}`\n- {context.get('project_type', 'greenfield')}\n"
    )


def _load_improve_telemetry(state, project_name):
    try:
        from config.loader import config as _cfg

        _live_path = Path(_cfg.paths.storage_dir) / "live.json"
        if not _live_path.exists():
            return None
        telemetry = json.loads(_live_path.read_text())
        from config.loader import config as _cfg

        url = telemetry.get("product_url", _cfg.services.product.url)
        health = telemetry.get("health_endpoint", "/health")
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"{url.rstrip('/')}/{health.lstrip('/')}")
                telemetry["health_status"] = resp.status_code
                telemetry["healthy"] = 200 <= resp.status_code < 400
        except (httpx.RequestError, OSError):
            telemetry["healthy"] = False
        deployed = telemetry.get("project_path", "")
        if deployed and Path(deployed).is_dir():
            return telemetry
        return None
    except Exception:
        return None


def _detect_project_type(project_path: str) -> str:
    """Detect framework type from package dependencies."""
    if not project_path:
        return "unknown"
    pm = Path(project_path)
    if (pm / "pyproject.toml").exists():
        return "python"
    if (pm / "package.json").exists():
        return "node"
    if (pm / "Cargo.toml").exists():
        return "rust"
    if (pm / "go.mod").exists():
        return "go"
    if (pm / "Gemfile").exists():
        return "ruby"
    return "unknown"


def _inventory_tree(context_folder: str, max_depth: int = 3):
    """Walk the project tree up to max_depth."""
    base = Path(context_folder)
    tree: dict = {}
    if not base.is_dir():
        return tree
    for entry in sorted(base.iterdir()):
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        if entry.is_dir():
            sub = {}
            if max_depth > 1:
                for sub_entry in sorted(entry.iterdir())[:20]:
                    if not sub_entry.name.startswith("."):
                        sub[sub_entry.name] = {
                            "type": "dir" if sub_entry.is_dir() else "file"
                        }
            tree[entry.name] = {"type": "dir", "children": sub}
        else:
            tree[entry.name] = {"type": "file"}
    return tree


def _detect_framework(project_path: str):
    """Detect framework from pyproject.toml or package.json deps."""
    base = Path(project_path)
    if (base / "pyproject.toml").exists():
        import toml

        try:
            data = toml.loads((base / "pyproject.toml").read_text())
            deps = data.get("project", {}).get("dependencies", [])
            dd = " ".join(deps).lower()
            if "django" in dd:
                return "django"
            if "fastapi" in dd:
                return "fastapi"
            if "flask" in dd:
                return "flask"
            if "httpx" in dd:
                return "fastapi"
            return "python"
        except Exception:
            return "python"
    if (base / "package.json").exists():
        import json

        try:
            pkg = json.loads((base / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            dd = " ".join(deps.keys()).lower()
            if "next" in dd:
                return "nextjs"
            if "react" in dd:
                return "react"
            return "node"
        except Exception:
            return "node"
    return "unknown"


def _discover_routes(context_folder: str, project_type: str) -> list:
    """Extract route definitions from backends."""
    routes: list = []
    if not context_folder or not Path(context_folder).is_dir():
        return routes
    if project_type == "fastapi":
        for f in Path(context_folder).rglob("*.py"):
            text = f.read_text()
            for m in re.finditer(
                r'@(?:router|app)\.(?:get|post|put|delete|patch)\s*\(\s*[\'"]([^\'"]+)',
                text,
            ):
                routes.append(
                    {
                        "method": "auto",
                        "path": m.group(1),
                        "file": str(f.relative_to(context_folder)),
                    }
                )
    elif project_type == "django":
        for f in Path(context_folder).rglob("urls.py"):
            text = f.read_text()
            for m in re.finditer(r"path\s*\(\s*['\"]?([^'\",)]+)", text):
                routes.append(
                    {
                        "method": "auto",
                        "path": m.group(1),
                        "file": str(f.relative_to(context_folder)),
                    }
                )
    elif project_type in ("nextjs", "react"):
        for f in Path(context_folder).rglob("page.tsx"):
            routes.append(
                {
                    "method": "GET",
                    "path": f"/{f.relative_to(context_folder).parent}",
                    "file": str(f.relative_to(context_folder)),
                }
            )
    return routes


def _discover_models(context_folder: str, project_type: str) -> list:
    """Extract model definitions from backends."""
    models: list = []
    if not context_folder or not Path(context_folder).is_dir():
        return models
    if project_type == "django":
        for f in Path(context_folder).rglob("models.py"):
            for m in re.finditer(r"class\s+(\w+)\(models\.", f.read_text()):
                models.append(m.group(1))
    elif project_type == "fastapi":
        for f in Path(context_folder).rglob("*.py"):
            for m in re.finditer(r"class\s+(\w+)\(BaseModel\)", f.read_text()):
                models.append(m.group(1))
    return models


def _discover_templates(context_folder: str, project_type: str) -> list:
    """List Jinja2 or JSX template paths."""
    templates: list = []
    if not context_folder or not Path(context_folder).is_dir():
        return templates
    ext = (
        ".html"
        if project_type in ("django", "flask")
        else (".tsx" if project_type in ("nextjs", "react") else ".jinja2")
    )
    for f in Path(context_folder).rglob(f"*{ext}"):
        templates.append(str(f.relative_to(context_folder)))
    return templates


def _discover_dependencies(context_folder: str) -> dict:
    """Return known dependencies from lock/config files."""
    deps = {}
    base = Path(context_folder)
    if (base / "requirements.txt").exists():
        deps["requirements"] = [
            dep.strip()
            for dep in base.joinpath("requirements.txt").read_text().splitlines()
            if dep.strip() and not dep.startswith("#")
        ]
    if (base / "pyproject.toml").exists():
        import toml

        try:
            data = toml.loads((base / "pyproject.toml").read_text())
            deps["pyproject"] = data.get("project", {}).get("dependencies", [])
        except Exception:
            pass
    if (base / "package.json").exists():
        import json

        try:
            pkg = json.loads((base / "package.json").read_text())
            deps["npm"] = list(
                {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}.keys()
            )
        except Exception:
            pass
    return deps


def _get_git_status(context_folder: str) -> dict:
    """Return git branch and dirty status."""
    try:
        result = subprocess.run(
            ["git", "-C", context_folder, "status", "--porcelain", "--branch"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = result.stdout.strip().split("\n")
        branch = lines[0].replace("## ", "").split("...")[0] if lines else "unknown"
        dirty = len([line for line in lines if line.strip()]) > 1
        return {"branch": branch, "dirty": dirty}
    except (subprocess.SubprocessError, FileNotFoundError):
        return {"branch": "unknown", "dirty": False}


def _get_docker_status(context_folder: str) -> dict:
    """Check for docker-compose.yaml or Dockerfile."""
    base = Path(context_folder)
    return {
        "services": ["app"],
        "has_dockerfile": any(base.glob("Dockerfile*")),
        "has_compose": any(base.glob("docker-compose.*")),
    }


def _discover_specs(context_folder: str) -> dict:
    """Find specification documents."""
    base = Path(context_folder)
    specs = {}
    for pattern in ["**/*.md", "**/*.yaml", "**/*.yml", "**/*.json"]:
        for f in base.glob(pattern):
            if (
                "spec" in f.stem.lower()
                or "requirement" in f.stem.lower()
                or "readme" in f.stem.lower()
            ):
                specs[f.name] = {
                    "size": f.stat().st_size,
                    "path": str(f.relative_to(context_folder)),
                }
    return specs


def _refine_idea(
    interview_notes, project_name, project_description, context, state=None
):
    """Sharpen interview notes into a focused concept for DEFINE."""
    skills = build_skill_registry(_cfg.workflow.skill_registry_path)
    refine_skill = skills.get("idea-refine", {})
    if not refine_skill or not interview_notes:
        return (
            "No refinement available (missing interview notes "
            "or idea-refine skill)."
        )

    prompt = (
        f"Refine these interview notes into a sharp, actionable concept for the DEFINE phase.\n\n"
        f"Project: {project_name}\nDescription: {project_description}\n"
        f"Interview Notes:\n{interview_notes}\n\n"
        f"Output: A concise tech + UX concept (2-3 sentences) highlighting core innovation,"
        f" key trade-offs, and the most important design decision."
    )
    timer = SkillTimer("idea-refine")
    result = invoke_skill(refine_skill["content"], prompt, "", llm=None)
    timer.complete()
    return result or ""


def _build_context(
    interview_notes, project_name, project_description, context, state=None
):
    """Engineer focused project context for DEFINE phase."""
    return json.dumps(
        {
            "project_name": project_name,
            "description": project_description[:500],
            "type": context.get("project_type", "greenfield"),
            "interview_focus": interview_notes[:1000] if interview_notes else "",
            "tree_summary": {k: v["type"] for k, v in context.get("tree", {}).items()},
            "dependencies": context.get("dependencies", {}),
            "specs": context.get("specs", {}),
        },
        indent=2,
    )
