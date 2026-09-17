"""E5 — structured prompt-diff contract for ``apply_prompt_diff``.

``apply_prompt_diff`` in ``feedback/diff_engine.py`` SHALL:
- accept the structured diff shape ``{"section": <name>, "key":
  "template_body", "op": "replace", "value": <new text>}`` — the
  same shape REFLECT already emits for config diffs (Decision 4);
- keep the legacy ``diffs["changes"]`` list input shape accepted
  (each ``change`` is routed through the structured path, backward
  compatible with existing REFLECT call sites);
- locate the target template with a quote-aware regex (triple-quoted
  body, even when it contains ``"`` characters);
- build the replacement by escaping the value (backslash-safe,
  quote-safe, newline-safe);
- validate the candidate file with ``compile()`` BEFORE writing to
  disk — a non-compiling replacement leaves the original file
  byte-identical.

Spec delta: openspec/changes/2026-09-18-counter-footgun-fixes/specs/
pattern-memory/spec.md (Decision 4, structured prompt-diff contract).
"""

from __future__ import annotations

import pytest


# ── Test scaffolding: a fake config/prompt_templates.py ──────────


@pytest.fixture
def prompt_templates_file(tmp_path, monkeypatch):
    """Create a temporary ``config/prompt_templates.py`` in tmp_path
    and point the diff engine at it via the ``_template_file_path``
    monkeypatch.

    Returns ``(tmp_path, template_path)`` so tests can read back the
    file contents.
    """
    import feedback.diff_engine as diff_mod

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    template_path = config_dir / "prompt_templates.py"
    template_path.write_text(
        '"""Prompt templates for skill prompts."""\n'
        "\n"
        "interview_me = "
        '"""Ask the user about the project goals, scope, and target audience.\n'
        "Follow up on the data model and API surface.\n"
        'Do not invent requirements — only record what the user says."""\n'
        "\n"
        "spec_generation = "
        '"""Write a markdown specification.\n'
        'Section: "Use cases" — list them one per bullet.\n'
        "End with an acceptance-test block.\"\"\"\n"
    )
    monkeypatch.setattr(
        diff_mod,
        "_template_file_path",
        lambda: str(template_path),
    )
    return tmp_path, template_path


def _exec_template(path):
    """Execute the template file and return the namespace."""
    ns = {}
    with open(path) as f:
        exec(compile(f.read(), str(path), "exec"), ns)
    return ns


# ── 2.1a — structured diff with quotes + newlines applies safely ─


def test_structured_diff_with_quotes_and_newlines_applies(prompt_templates_file):
    """A structured diff whose ``value`` contains double-quote
    characters and newlines rewrites the template in
    ``config/prompt_templates.py``; the file still compiles and the
    new value is preserved exactly when the file is executed."""
    import feedback.diff_engine as diff_mod

    tmp_path, template_path = prompt_templates_file

    new_text = (
        "Improved interview: ask about goals AND constraints.\n"
        'Handle "quoted" user input safely.\n'
        "Second line with a backslash C:\\temp\\path.\n"
        "Triple-quote sequence embedded: " + chr(34) * 3 + " end."
    )
    diffs = {
        "section": "interview_me",
        "key": "template_body",
        "op": "replace",
        "value": new_text,
    }

    ok = diff_mod.apply_prompt_diff("interview_me", diffs)

    assert ok is True
    # The file compiles.
    ns = _exec_template(template_path)
    # The new value is preserved exactly.
    assert ns["interview_me"] == new_text


# ── 2.1b — value containing """ cannot break out of the assignment ─


def test_value_with_triple_quote_sequence_cannot_break_out(prompt_templates_file):
    """A value containing a triple-quote sequence cannot terminate
    the triple-quoted assignment early.  The value is escaped so
    the file still compiles — the classic break-out case is safe."""
    import feedback.diff_engine as diff_mod

    tmp_path, template_path = prompt_templates_file

    # Pre-seed a template body that itself contains a double-quote
    # character — a naive regex cannot even match this.
    template_path.write_text(
        '"""Prompt templates for skill prompts."""\n'
        "\n"
        "spec_generation = "
        '"""Write a markdown specification.\n'
        'Section: "Use cases" — list them one per bullet.\n'
        "End with an acceptance-test block.\"\"\"\n"
    )

    # Value that contains a triple-quote sequence — the classic
    # break-out case.  Without escaping, this would terminate the
    # new triple-quoted assignment and produce a syntax error.
    new_text = "A line\nNext line with " + chr(34) * 3 + " inside.\nFinal line."
    diffs = {
        "section": "spec_generation",
        "key": "template_body",
        "op": "replace",
        "value": new_text,
    }

    ok = diff_mod.apply_prompt_diff("spec_generation", diffs)

    assert ok is True
    # The file still compiles — the value did not break out of the
    # triple-quoted assignment.
    ns = _exec_template(template_path)
    # The new value is preserved exactly.
    assert ns["spec_generation"] == new_text


# ── 2.1c — non-compiling replacement leaves the original untouched ─


def test_non_compiling_replacement_leaves_file_unchanged(
    prompt_templates_file, monkeypatch
):
    """A composed replacement that does not compile leaves the
    original ``config/prompt_templates.py`` byte-identical — the
    write only happens after ``compile()`` succeeds."""
    import feedback.diff_engine as diff_mod

    tmp_path, template_path = prompt_templates_file
    original = template_path.read_bytes()

    def _bad_escape(v):
        # Return a value that, when wrapped in triple-quotes,
        # produces an unterminated string.
        return chr(34) * 3 + " unterminated " + chr(34)

    monkeypatch.setattr(diff_mod, "_escape_template_body", _bad_escape)

    diffs = {
        "section": "interview_me",
        "key": "template_body",
        "op": "replace",
        "value": "anything",
    }
    ok = diff_mod.apply_prompt_diff("interview_me", diffs)
    assert ok is False
    assert template_path.read_bytes() == original


# ── Legacy ``changes`` list shape is still accepted (backward compat) ─


def test_legacy_changes_list_still_accepted(prompt_templates_file):
    """The legacy ``diffs["changes"]`` list shape is still accepted;
    each change is routed through the structured path.  This
    preserves backward compatibility with existing REFLECT call
    sites."""
    import feedback.diff_engine as diff_mod

    tmp_path, template_path = prompt_templates_file

    # Legacy shape: a ``changes`` list where each entry has ``skill``
    # (template name) + ``change`` (new body text) + ``rationale``.
    new_body = "Legacy-style new interview prompt.\nSecond line.\n"
    diffs = {
        "overall_assessment": "test",
        "changes": [
            {
                "skill": "interview_me",
                "change": new_body,
                "rationale": "improved interview",
                "risk_level": "low",
            }
        ],
    }

    ok = diff_mod.apply_prompt_diff("interview_me", diffs)

    assert ok is True
    ns = _exec_template(template_path)
    assert ns["interview_me"] == new_body


def test_unknown_template_returns_false(prompt_templates_file):
    """If the target template does not exist in the file,
    ``apply_prompt_diff`` returns False and the file is untouched."""
    import feedback.diff_engine as diff_mod

    tmp_path, template_path = prompt_templates_file
    original = template_path.read_bytes()

    diffs = {
        "section": "nonexistent_template",
        "key": "template_body",
        "op": "replace",
        "value": "new body",
    }

    ok = diff_mod.apply_prompt_diff("nonexistent_template", diffs)

    assert ok is False
    assert template_path.read_bytes() == original


def test_missing_file_returns_false(tmp_path, monkeypatch):
    """If the template file does not exist, ``apply_prompt_diff``
    returns False (no crash, no partial write)."""
    import feedback.diff_engine as diff_mod

    monkeypatch.setattr(
        diff_mod,
        "_template_file_path",
        lambda: str(tmp_path / "no_such_file.py"),
    )
    diffs = {
        "section": "interview_me",
        "key": "template_body",
        "op": "replace",
        "value": "x",
    }
    ok = diff_mod.apply_prompt_diff("interview_me", diffs)
    assert ok is False


def test_apply_yaml_diff_routes_prompt_templates_to_apply_prompt_diff(
    prompt_templates_file, tmp_path
):
    """``apply_yaml_diff`` keeps its existing behaviour of routing
    prompt-template skill names to ``apply_prompt_diff`` — verify
    that this routing still works and the prompt diff is applied via
    the structured path."""
    import feedback.diff_engine as diff_mod

    _, template_path = prompt_templates_file

    # A yaml path (any file) — apply_yaml_diff is called with it,
    # but the routing to apply_prompt_diff short-circuits before
    # touching the yaml.
    yaml_path = tmp_path / "guardrails.yaml"
    yaml_path.write_text("interview_me:\n  threshold: 0.5\n")

    # Legacy shape with a prompt-template skill name.
    new_body = "Structured new body line one.\nLine two.\n"
    diffs = {
        "overall_assessment": "test",
        "changes": [
            {
                "skill": "interview_me",
                "change": new_body,
                "rationale": "improved",
                "risk_level": "low",
            }
        ],
    }

    ok = diff_mod.apply_yaml_diff(str(yaml_path), diffs)

    assert ok is True
    ns = _exec_template(template_path)
    assert ns["interview_me"] == new_body


def test_structured_diff_no_match_in_changes_returns_false(prompt_templates_file):
    """If the structured diff's ``section`` does not match
    ``template_name``, or no value is present, ``apply_prompt_diff``
    returns False and the file is untouched."""
    import feedback.diff_engine as diff_mod

    tmp_path, template_path = prompt_templates_file
    original = template_path.read_bytes()

    # Structured shape with wrong section — no match.
    diffs = {
        "section": "some_other_template",
        "key": "template_body",
        "op": "replace",
        "value": "new body",
    }
    ok = diff_mod.apply_prompt_diff("interview_me", diffs)
    assert ok is False
    assert template_path.read_bytes() == original
