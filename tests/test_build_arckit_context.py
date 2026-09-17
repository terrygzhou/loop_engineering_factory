"""W3 arckit-build-context (task 6.1-6.2): the OpenHands build prompt
includes advisory ArcKit sections ONLY for keys that are set; with no
ArcKit context the prompt is byte-identical to a pre-W3 run. The
build_report.json manifest contract (Decision 1) is unchanged."""

import json

from graph.nodes import openhands_build


def _build_state(**over):
    base = {
        "project_name": "demo",
        "project_path": "/tmp/demo",
        "artifacts": {"spec_refined": "spec", "tasks": "tasks"},
    }
    base.update(over)
    return base


ART_KEYS = (
    "arckit_data_model",
    "arckit_integration_standards",
    "arckit_security_controls",
    "arckit_nfr_constraints",
    "arckit_product_backlog",
    "arckit_strategy_waves",
    "arch_review_answers",
)

ART_VALUES = {
    "arckit_data_model": json.dumps({"entities": [{"entity": "Policy"}]}),
    "arckit_integration_standards": json.dumps(
        {"api_standards": [{"standard": "REST"}]}
    ),
    "arckit_security_controls": json.dumps({"pillars": [{"pillar": "Secure by design"}]}),
    "arckit_nfr_constraints": json.dumps({"use_cases": ["Check out"]}),
    "arckit_product_backlog": json.dumps([{"title": "First release"}]),
    "arckit_strategy_waves": json.dumps([{"wave": "Defend"}]),
    "arch_review_answers": json.dumps({"Q1": "A1"}),
}


class TestBuildPromptArckitSections:
    def test_all_keys_set_all_sections_present(self):
        arts = dict(ART_VALUES)
        prompt = openhands_build._build_prompt(_build_state(artifacts=arts))
        # 6 ArcKit advisory sections
        for header in (
            "DATA MODEL",
            "INTEGRATION STANDARDS",
            "SECURITY CONTROLS",
            "NFR CONSTRAINTS",
            "PRODUCT BACKLOG",
            "STRATEGY WAVES",
        ):
            assert header in prompt, f"section {header} missing"
        # content survived
        assert "Policy" in prompt
        assert "REST" in prompt
        assert "Secure by design" in prompt
        assert "Check out" in prompt
        assert "First release" in prompt
        assert "Defend" in prompt
        # existing P0.5 section still there
        assert "REVIEW SUPPLEMENTS" in prompt

    def test_each_key_independent(self):
        """6.2 on/off matrix: only the set key's section is emitted."""
        markers = {
            "arckit_data_model": "DATA MODEL",
            "arckit_integration_standards": "INTEGRATION STANDARDS",
            "arckit_security_controls": "SECURITY CONTROLS",
            "arckit_nfr_constraints": "NFR CONSTRAINTS",
            "arckit_product_backlog": "PRODUCT BACKLOG",
            "arckit_strategy_waves": "STRATEGY WAVES",
            "arch_review_answers": "REVIEW SUPPLEMENTS",
        }
        for key in ART_KEYS:
            arts = {key: ART_VALUES[key]}
            prompt = openhands_build._build_prompt(_build_state(artifacts=arts))
            for other, marker in markers.items():
                if other == key:
                    assert marker in prompt, f"{marker} missing for {key}"
                else:
                    assert marker not in prompt, (
                        f"{marker} leaked when only {key} set"
                    )

    def test_no_arckit_context_prompt_identical_to_baseline(self):
        """6.2: with no ArcKit key the prompt is byte-identical to a run
        with no ArcKit context at all (no empty sections, no markers)."""
        baseline = openhands_build._build_prompt(_build_state())
        assert "ARCKIT" not in baseline
        # a prompt built with explicitly empty-string keys must match too
        arts = {"spec_refined": "spec", "tasks": "tasks"}
        for key in ART_KEYS:
            arts[key] = ""
        assert openhands_build._build_prompt(_build_state(artifacts=arts)) == baseline

    def test_manifest_contract_unchanged(self):
        """6.3: the machine-readable build_report.json contract survives in
        every prompt variant."""
        prompt = openhands_build._build_prompt(
            _build_state(artifacts=dict(ART_VALUES))
        )
        assert "build_report.json" in prompt
        assert '"status": "pass" | "fail" | "partial"' in prompt

    def test_sections_capped_per_prompt_char_limit(self):
        arts = dict(ART_VALUES)
        arts["arckit_data_model"] = json.dumps({"entities": ["x" * 100_000]})
        prompt = openhands_build._build_prompt(_build_state(artifacts=arts))
        assert prompt.count("x") <= openhands_build.PROMPT_CHAR_LIMIT
