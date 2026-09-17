from tools.loader import build_skill_registry


def test_pre_commit_review_present_and_old_name_absent():
    registry = build_skill_registry()
    assert "pre-commit-review" in registry
    assert "requesting-code-review" not in registry


def test_code_review_and_quality_merged_away():
    registry = build_skill_registry()
    assert "code-review-and-quality" not in registry
    assert "pre-commit-review" in registry
