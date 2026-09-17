"""W4 plan-sequence-view: use-case extraction, per-use-case sequence views,
and the BUILD prompt diagram section.

Specs: openspec/changes/plan-sequence-view/specs/{plan-architecture-diagrams,
build-delegation}/spec.md
"""

import json
import types
from pathlib import Path
from unittest.mock import patch


def _diagram_state(tmp_path, artifacts):
    return {
        "phase": "PLAN",
        "project_name": "demo",
        "project_folder": str(tmp_path),
        "project_path": str(tmp_path),
        "metrics": __import__("graph.state", fromlist=["CycleMetrics"]).CycleMetrics(),
        "artifacts": artifacts,
        "cycle_id": "0",
        "trace_id": "t",
    }


_SPEC_250 = ("Project specification. " * 25)  # >200 chars to pass the guard


# ── Task 1.1/1.2 — use-case extraction ─────────────────────────────


def test_use_cases_from_nfr_key():
    from graph.nodes.plan import _extract_use_cases

    nfr = json.dumps(
        {
            "use_cases": ["Book a table", "View menu", "Pay online"],
            "user_count": 50,
        }
    )
    arts = {
        "arckit_nfr_constraints": nfr,
        "interview_notes": "User story: totally different",
        "spec_refined": "As a guest I want X",
    }
    assert _extract_use_cases(arts) == ["Book a table", "View menu", "Pay online"]


def test_use_cases_fallback_interview_spec_heuristic():
    from graph.nodes.plan import _extract_use_cases

    arts = {
        "interview_notes": "User story: Reserve a room\nunrelated line",
        "spec_refined": "noise\nAs a customer I want to pay online\nmore noise",
    }
    ucs = _extract_use_cases(arts)
    assert "Reserve a room" in ucs
    assert "As a customer I want to pay online" in ucs
    assert "unrelated line" not in ucs


def test_no_use_cases_when_no_sources():
    from graph.nodes.plan import _extract_use_cases

    assert _extract_use_cases({}) == []
    assert _extract_use_cases(
        {"interview_notes": "generic text", "spec_refined": "plain spec"}
    ) == []


def test_nfr_key_with_empty_use_cases_falls_back():
    from graph.nodes.plan import _extract_use_cases

    arts = {
        "arckit_nfr_constraints": json.dumps({"use_cases": []}),
        "interview_notes": "User flow: Track a parcel",
    }
    assert _extract_use_cases(arts) == ["Track a parcel"]


# ── Task 2.1-2.4 — per-use-case sequence generation ────────────────


def _mock_llm(marker="GENERATED"):
    """Async stand-in for invoke_skill_async; echoes the task text so tests
    can assert per-use-case calls happened."""

    async def fake(
        skill_content,
        task,
        context="",
        llm=None,
        max_prompt_chars=2000,
        workflow_id="",
        phase="",
    ):
        return f"{marker}: {task}"

    return fake


_NO_RESULT = object()


def _run_diagrams(tmp_path, artifacts, llm_result=_NO_RESULT):
    from graph.nodes.plan import _generate_all_diagrams

    if llm_result is _NO_RESULT:
        fake = _mock_llm()
    else:

        async def fake(skill_content, task, context="", llm=None,
                       max_prompt_chars=2000, workflow_id="", phase=""):
            return llm_result

    with patch("graph.nodes.plan.invoke_skill_async", fake), patch(
        "graph.nodes.plan.safe_stream_writer", lambda: (lambda x: None)
    ):
        return _generate_all_diagrams({}, _diagram_state(tmp_path, artifacts))


def test_three_use_cases_give_three_sequence_views(tmp_path):
    arts = {
        "spec_refined": _SPEC_250,
        "arckit_nfr_constraints": json.dumps(
            {"use_cases": ["Book a table", "View menu", "Pay online"]}
        ),
    }
    diagrams = _run_diagrams(tmp_path, arts)
    assert set(diagrams) == {
        "component",
        "data flow",
        "deployment",
        "sequence_book-a-table",
        "sequence_view-menu",
        "sequence_pay-online",
    }
    # generic "sequence" view is the no-use-case fallback only
    assert "sequence" not in diagrams
    uc_file = (tmp_path / "build" / "diagrams" / "sequence-book-a-table.mmd")
    assert "Book a table" in uc_file.read_text()
    # the LLM task mentioned the specific use case
    assert "sequence" in diagrams["sequence_pay-online"] and "Pay online" in Path(
        diagrams["sequence_pay-online"]
    ).read_text()


def test_zero_use_cases_keeps_today_output(tmp_path):
    arts = {"spec_refined": _SPEC_250, "interview_notes": "no stories here"}
    diagrams = _run_diagrams(tmp_path, arts)
    assert set(diagrams) == {"component", "sequence", "data flow", "deployment"}


def test_thin_context_guard_still_emits_placeholder_set(tmp_path):
    """0 use cases + context < 200 chars → today's guard branch (4 views, placeholders)."""
    arts = {"spec_refined": "tiny", "interview_notes": "short"}
    diagrams = _run_diagrams(tmp_path, arts)
    assert set(diagrams) == {"component", "sequence", "data flow", "deployment"}
    for path in diagrams.values():
        assert "Insufficient context" in Path(path).read_text()


def test_llvm_none_result_yields_placeholder_not_typeerror(tmp_path):
    arts = {
        "spec_refined": _SPEC_250,
        "arckit_nfr_constraints": json.dumps({"use_cases": ["Pay online"]}),
    }
    diagrams = _run_diagrams(tmp_path, arts, llm_result=None)
    seq_path = diagrams["sequence_pay-online"]
    assert "Insufficient context" in Path(seq_path).read_text()


def test_dry_run_marker_is_written_through(tmp_path):
    arts = {"spec_refined": _SPEC_250}
    diagrams = _run_diagrams(tmp_path, arts, llm_result="[DRY-RUN] diagram")
    for path in diagrams.values():
        assert Path(path).read_text().startswith("[DRY-RUN]")


def test_duplicate_slugs_are_disambiguated(tmp_path):
    arts = {
        "spec_refined": _SPEC_250,
        "arckit_nfr_constraints": json.dumps(
            {"use_cases": ["Pay online", "Pay online!"]}
        ),
    }
    diagrams = _run_diagrams(tmp_path, arts)
    assert "sequence_pay-online" in diagrams
    assert "sequence_pay-online-2" in diagrams


def test_png_pipeline_covers_new_keys(tmp_path):
    """_convert_diagrams_to_png iterates every diagram key (existing pipeline)."""
    pytest_mod = __import__("pytest")
    pytest_mod.importorskip("playwright")

    arts = {
        "spec_refined": _SPEC_250,
        "arckit_nfr_constraints": json.dumps({"use_cases": ["Pay online"]}),
    }
    diagrams = _run_diagrams(tmp_path, arts)

    fake = types.ModuleType("tools.convert_diagrams")
    fake.extract_mermaids = lambda text: ["sequenceDiagram\n  A->>B: hi"]
    fake.make_html = lambda block: tmp_path / "fake.html"

    class _FakePage:
        def __init__(self, out_dir):
            self.out_dir = out_dir
            self.calls = []

        async def goto(self, url):
            self.calls.append(url)

        async def wait_for_timeout(self, ms):
            pass

        async def screenshot(self, path, full_page=False):
            Path(path).write_text("png")

    class _FakeBrowser:
        def __init__(self, out_dir):
            self.page = _FakePage(out_dir)

        async def new_page(self, **kw):
            return self.page

        async def close(self):
            pass

    class _FakeCtx:
        def __init__(self, out_dir):
            self._out = out_dir

        async def __aenter__(self):
            out_dir = self._out

            class _PW:
                class chromium:
                    @staticmethod
                    async def launch(headless=True):
                        return _FakeBrowser(out_dir)

            return _PW()

        async def __aexit__(self, *a):
            return False

    def _fake_pw():
        return _FakeCtx(tmp_path)

    with patch("playwright.async_api.async_playwright", _fake_pw), patch.dict(
        "sys.modules", {"tools.convert_diagrams": fake}
    ):
        from graph.nodes.plan import _convert_diagrams_to_png

        pngs = _convert_diagrams_to_png(diagrams)
    assert "sequence_pay-online" in pngs
    assert Path(pngs["sequence_pay-online"]).exists()


# ── Task 3.1/3.2 — BUILD prompt diagram section ────────────────────


def _prompt(artifacts):
    from graph.nodes.openhands_build import _build_prompt

    return _build_prompt(
        {
            "project_name": "demo",
            "project_path": "/tmp/demo",
            "artifacts": artifacts,
            "cycle_id": "0",
            "trace_id": "t",
        }
    )


def test_prompt_unchanged_when_no_diagrams():
    base = _prompt({"spec_refined": "spec", "tasks": "tasks"})
    assert "ARCHITECTURE DIAGRAMS" not in base
    # W3 gotcha: baseline must stay free of the ARCKIT marker
    assert "ARCKIT" not in base


def test_prompt_includes_sequence_views_when_present(tmp_path):
    (tmp_path / "build").mkdir(parents=True, exist_ok=True)
    files = {
        "component": "graph TD\n  A-->B",
        "sequence_pay-online": "sequenceDiagram\n  User->>API: pay",
        "sequence_track-parcel": "sequenceDiagram\n  T->>S: track",
    }
    paths = {}
    for key, content in files.items():
        p = tmp_path / f"{key.replace('_', '-')}.mmd"
        p.write_text(content)
        paths[key] = str(p)
    prompt = _prompt(
        {"spec_refined": "spec", "tasks": "tasks", "diagrams": paths}
    )
    assert "ARCHITECTURE DIAGRAMS" in prompt
    assert "sequence_pay-online" in prompt
    assert "User->>API: pay" in prompt
    assert "sequence_track-parcel" in prompt


def test_prompt_diagram_section_only_lists_present_keys(tmp_path):
    (tmp_path / "build").mkdir(parents=True, exist_ok=True)
    p = tmp_path / "component-diagram.mmd"
    p.write_text("graph TD\n  A-->B")
    prompt = _prompt({"spec_refined": "spec", "tasks": "tasks", "diagrams": {"component": str(p)}})
    section = prompt.split("ARCHITECTURE DIAGRAMS", 1)[1]
    assert "component" in section
    assert "sequence_" not in section
    # prompt stable when diagram files are missing (unresolvable paths skipped)
    prompt2 = _prompt(
        {"spec_refined": "spec", "tasks": "tasks", "diagrams": {"component": "/no/such/file.mmd"}}
    )
    assert "ARCHITECTURE DIAGRAMS" not in prompt2
