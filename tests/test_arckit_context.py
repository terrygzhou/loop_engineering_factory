"""skill-map-arckit-fit task 2: the shared ArcKit advisory-block helper
(``tools/arckit_context.py``) and its PLAN consumption.

- ``arckit_advisory_block`` returns "" when no advisory keys are set,
  one ``## <KEY_NAME>`` section per key present (fixed order), total capped
  at ``max_chars``.
- PLAN feeds the block into its ``context_parts`` via the shared helper —
  byte-identical prompt context when no ArcKit advisory keys are set.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from tools.arckit_context import ARCKIT_ADVISORY_KEYS, arckit_advisory_block


def _base_state(**artifacts) -> dict:
    from tests.test_llm_failure_robustness import _base_state

    return _base_state("PLAN", **artifacts)


BACKLOG = json.dumps(
    [
        {"id": "P1", "title": "Login flow", "size": "M"},
        {"id": "P2", "title": "Payments", "size": "L"},
    ]
)


def test_block_empty_when_no_keys():
    assert arckit_advisory_block({}) == ""
    # keys present but empty must not emit sections
    assert (
        arckit_advisory_block(
            {k: "" for k in ARCKIT_ADVISORY_KEYS},
        )
        == ""
    )


def test_block_includes_backlog_when_set():
    block = arckit_advisory_block({"arckit_product_backlog": BACKLOG})
    assert "## arckit_product_backlog" in block
    assert BACKLOG in block


def test_block_caps_at_max_chars():
    big = "x" * 10000
    block = arckit_advisory_block(
        {"arckit_product_backlog": big},
        max_chars=4000,
    )
    assert len(block) <= 4000
    # cap still applies when many keys are set: total output stays bounded
    multi = {k: "y" * 5000 for k in ARCKIT_ADVISORY_KEYS}
    block_multi = arckit_advisory_block(multi, max_chars=4000)
    assert len(block_multi) <= 4000


def _patch_plan(monkeypatch, recorded: list):
    import graph.nodes.plan as plan_mod

    monkeypatch.setattr(plan_mod, "safe_stream_writer", lambda: lambda x: None)
    monkeypatch.setattr(
        plan_mod,
        "build_skill_registry",
        lambda *a, **k: {
            "planning-and-task-breakdown": {"content": "c"},
            "doubt-driven-development": {"content": "c"},
        },
    )
    monkeypatch.setattr(
        plan_mod, "invoke_skill", lambda *a, **k: _skill_recorder(recorded)(a, k)
    )

    async def _noop_async(*a, **k):
        return None

    monkeypatch.setattr(plan_mod, "invoke_skill_async", _noop_async)
    monkeypatch.setattr(plan_mod, "AuditLog", MagicMock())
    monkeypatch.setattr(plan_mod, "get_chroma_client", lambda *a, **k: None)


def _skill_recorder(recorded: list):
    """Record the first skill invocation (planning) context."""
    state = {"done": False}

    def _recorder(args, kwargs):
        if not state["done"]:
            state["done"] = True
            recorded.append(args[2] if len(args) > 2 else (kwargs.get("context") or ""))
        return "PLAN-OK"

    return _recorder


def test_plan_prompt_includes_backlog_when_set(tmp_path, monkeypatch):
    import graph.nodes.plan as plan_mod

    s = _base_state(
        spec_refined="S" * 250,
        interview_notes="notes",
        arckit_product_backlog=BACKLOG,
    )
    s["project_path"] = str(tmp_path)
    s["project_folder"] = str(tmp_path)

    recorded: list = []
    _patch_plan(monkeypatch, recorded)

    out = plan_mod.plan_node(s)
    assert out["phase"] == "PLAN"
    assert recorded, "planning skill must still be invoked"
    assert "## arckit_product_backlog" in recorded[0]
    assert "Login flow" in recorded[0]


def test_plan_prompt_unchanged_when_absent(tmp_path, monkeypatch):
    """No ArcKit advisory keys -> planning context byte-identical to the
    pre-change build (spec + interview + rejection feedback only)."""
    import graph.nodes.plan as plan_mod

    s = _base_state(spec_refined="S" * 250, interview_notes="notes")
    s["project_path"] = str(tmp_path)
    s["project_folder"] = str(tmp_path)

    recorded: list = []
    _patch_plan(monkeypatch, recorded)

    plan_mod.plan_node(s)
    assert recorded
    context = recorded[0]

    # Byte-identical to the pre-change context: same parts (spec +
    # interview), same "\n\n" join, no advisory part appended.
    # prepare_context_for_llm renders a single context dict as
    # "## context\n<content>" — replicate that in the expected string.
    pre_change = "## context\n" + "\n\n".join(
        ["S" * 250, "Interview notes:\nnotes"]
    )
    assert context == pre_change
    # no advisory markers leaked
    for key in ARCKIT_ADVISORY_KEYS:
        assert f"## {key}" not in context
