"""Tests for service/evaluator.py — LLM-as-judge, JSON parsing, edge cases."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestEvalResult:
    """Test EvalResult dataclass."""

    def test_creation(self):
        from service.evaluator import EvalResult
        result = EvalResult(name="spec_quality", score=0.85, rationale="Good spec")
        assert result.name == "spec_quality"
        assert result.score == 0.85

    def test_to_attributes(self):
        from service.evaluator import EvalResult
        result = EvalResult(
            name="build_quality", score=0.72,
            dimensions={"code_quality": 0.8, "security": 0.6},
            duration_s=1.5, model="test-model",
            rationale="Decent build",
        )
        attrs = result.to_attributes()
        assert attrs["eval.name"] == "build_quality"
        assert attrs["eval.score"] == 0.72
        assert attrs["eval.dim.code_quality"] == 0.8
        assert attrs["eval.dim.security"] == 0.6
        assert attrs["eval.duration_s"] == 1.5

    def test_empty_dimensions(self):
        from service.evaluator import EvalResult
        result = EvalResult(name="x", score=0.5, dimensions={})
        attrs = result.to_attributes()
        assert "eval.dim." not in str(attrs)


class TestParseJson:
    """Test _parse_json — JSON extraction from LLM responses."""

    def test_plain_json(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        raw = json.dumps({"score": 0.9, "rationale": "good", "dimensions": {"x": 0.8}})
        result = evaluator._parse_json(raw)
        assert result["score"] == 0.9

    def test_markdown_code_fence(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        raw = '```json\n{"score": 0.85, "rationale": "ok"}\n```'
        result = evaluator._parse_json(raw)
        assert result["score"] == 0.85

    def test_markdown_code_fence_no_lang(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        raw = '```\n{"score": 0.7, "rationale": "meh"}\n```'
        result = evaluator._parse_json(raw)
        assert result["score"] == 0.7

    def test_brace_fallback(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        raw = "Some text before\n{score: 0.5} not valid json but has braces\nmore text"
        result = evaluator._parse_json(raw)
        assert result == {"score": 0.0, "rationale": raw[:500], "dimensions": {}}

    def test_valid_brace_fallback(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        raw = "Here is the result:\n{\"score\": 0.6, \"rationale\": \"ok\"}\nDone."
        result = evaluator._parse_json(raw)
        assert result["score"] == 0.6

    def test_completely_garbage(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        raw = "no json at all, just random text"
        result = evaluator._parse_json(raw)
        assert result["score"] == 0.0
        assert "dimensions" in result

    def test_whitespace_only(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        raw = "   \n\t  "
        result = evaluator._parse_json(raw)
        assert result["score"] == 0.0

    def test_multiline_json(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        raw = json.dumps({"score": 0.9, "rationale": "good\nwith newlines", "dimensions": {"a": 1.0}}, indent=2)
        result = evaluator._parse_json(raw)
        assert result["score"] == 0.9


class TestEvaluatorUnavailability:
    """Test evaluator behavior when LLM is unavailable."""

    def test_no_url_returns_zero_score(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator(llm_base_url="", llm_model="")
        result = evaluator.eval_spec("some spec")
        assert result.score == 0.0
        assert result.name == "spec_quality"

    def test_no_model_returns_zero_score(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator(llm_base_url="http://x", llm_model="")
        result = evaluator.eval_spec("some spec")
        assert result.score == 0.0

    def test_available_with_both(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator(llm_base_url="http://x", llm_model="m")
        assert evaluator._available

    def test_not_available_missing_url(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator(llm_model="m")
        assert not evaluator._available


class TestEvaluatorEvals:
    """Test each eval method creates correct result names."""

    def test_eval_spec_name(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        result = evaluator.eval_spec("test spec")
        assert result.name == "spec_quality"

    def test_eval_plan_name(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        result = evaluator.eval_plan("test plan")
        assert result.name == "plan_score"

    def test_eval_review_name(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        result = evaluator.eval_review("test review")
        assert result.name == "review_score"

    def test_eval_build_name(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        result = evaluator.eval_build("test build artifacts")
        assert result.name == "build_quality"

    def test_eval_ship_name(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator()
        result = evaluator.eval_ship("test ship artifacts")
        assert result.name == "ship_quality"


class TestEvaluatorJudge:
    """Test _judge HTTP call and error handling."""

    def test_http_error_captured(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator(llm_base_url="http://test", llm_model="m")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        with patch("httpx.post", return_value=mock_response):
            result = evaluator._judge("test_eval", "prompt", key="val")
            assert result.score == 0.0
            assert "500" in result.rationale

    def test_http_exception_captured(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator(llm_base_url="http://test", llm_model="m")
        with patch("httpx.post", side_effect=Exception("connection refused")):
            result = evaluator._judge("test_eval", "prompt", key="val")
            assert result.score == 0.0
            assert "connection refused" in result.rationale

    def test_successful_call(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator(llm_base_url="http://test", llm_model="m")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"score": 0.9, "rationale": "great", "dimensions": {}}'}}]
        }
        with patch("httpx.post", return_value=mock_response):
            result = evaluator._judge("test_eval", "prompt", key="val")
            assert result.score == 0.9
            assert result.rationale == "great"


class TestPrompts:
    """Test prompt templates render correctly."""

    def test_spec_prompt_renders(self):
        from service.evaluator import SPEC_QUALITY_PROMPT
        rendered = SPEC_QUALITY_PROMPT.format(spec_text="My spec text")
        assert "My spec text" in rendered
        assert "domain_fit" in rendered

    def test_plan_prompt_renders(self):
        from service.evaluator import PLAN_SCORE_PROMPT
        rendered = PLAN_SCORE_PROMPT.format(spec_ref="ref", plan_text="plan")
        assert "plan" in rendered
        assert "coverage" in rendered

    def test_build_prompt_renders(self):
        from service.evaluator import BUILD_QUALITY_PROMPT
        rendered = BUILD_QUALITY_PROMPT.format(spec_ref="ref", build_artifacts="artifacts")
        assert "artifacts" in rendered
        assert "code_quality" in rendered

    def test_ship_prompt_renders(self):
        from service.evaluator import SHIP_QUALITY_PROMPT
        rendered = SHIP_QUALITY_PROMPT.format(spec_ref="ref", ship_artifacts="configs")
        assert "configs" in rendered
        assert "config_completeness" in rendered

    def test_review_prompt_renders(self):
        from service.evaluator import REVIEW_SCORE_PROMPT
        rendered = REVIEW_SCORE_PROMPT.format(spec_context="ctx", review_text="review")
        assert "review" in rendered
        assert "thoroughness" in rendered


class TestOtelRecording:
    """Test OTel span recording."""

    def test_no_tracer_skips(self):
        from service.evaluator import Evaluator
        evaluator = Evaluator(tracer=None)
        from service.evaluator import EvalResult
        result = EvalResult(name="test", score=0.5)
        evaluator._record_to_otel(result)  # should not raise

    def test_tracer_not_configured_skips(self):
        from service.evaluator import Evaluator
        tracer = MagicMock()
        tracer.is_configured.return_value = False
        evaluator = Evaluator(tracer=tracer)
        from service.evaluator import EvalResult
        result = EvalResult(name="test", score=0.5)
        evaluator._record_to_otel(result)  # should not raise


class TestInitEvaluator:
    """Test init_evaluator singleton."""

    def test_init_creates_singleton(self):
        import service.evaluator as ev
        old = ev.evaluator
        try:
            ev.init_evaluator("http://test", "model", MagicMock())
            assert ev.evaluator is not None
            assert ev.evaluator.llm_base_url == "http://test"
            assert ev.evaluator.llm_model == "model"
        finally:
            ev.evaluator = old
