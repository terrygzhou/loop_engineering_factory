"""Doc-prefill concern for the DISCOVER node (seam split S9).

Pure helper moved here so `discover.py` keeps only the node entry point,
the two HIL `interrupt()` calls, and the LLM-orchestration core.
Re-exported from `graph/nodes/discover.py` so existing test imports keep
resolving.

`invoke_skill` is resolved via `graph.nodes.discover` at call time so that
test monkeypatch targets ("graph.nodes.discover.invoke_skill") keep working
even though the LLM call now lives in this sibling module.
"""

import json
import logging
import re

from graph.nodes.discover_scan import _collect_plain_docs

logger = logging.getLogger("discover")

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
        import graph.nodes.discover as _disc_mod

        result = _disc_mod.invoke_skill(
            "You are an expert requirements extractor.",
            prompt,
            "",
            llm=None,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Doc prefill extraction failed: %s", e)
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
        logger.warning("Doc prefill output unparseable: %s", e)
        return None, None
