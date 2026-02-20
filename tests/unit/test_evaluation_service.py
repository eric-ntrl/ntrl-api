"""Tests for evaluation_service.py — focus on JSON parsing edge cases."""

import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from app.services.evaluation_service import EvaluationService


@pytest.fixture
def eval_service():
    """Create an EvaluationService bypassing __init__."""
    svc = EvaluationService.__new__(EvaluationService)
    svc.teacher_model = "claude-sonnet-4-6"
    svc._total_input_tokens = 0
    svc._total_output_tokens = 0
    svc._token_lock = threading.Lock()
    return svc


def _mock_anthropic_response(text: str):
    """Build a mock Anthropic Messages response."""
    mock_content = MagicMock()
    mock_content.text = text

    mock_usage = MagicMock()
    mock_usage.input_tokens = 100
    mock_usage.output_tokens = 50

    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_response.usage = mock_usage
    return mock_response


class TestCallTeacherAnthropic:
    """Tests for _call_teacher_anthropic JSON parsing."""

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_clean_json(self, eval_service):
        """Direct JSON parse succeeds."""
        payload = {"domain_correct": True, "score": 8.5}
        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_anthropic_response(json.dumps(payload))
            result = eval_service._call_teacher_anthropic("system", "user")
        assert result == payload

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_json_with_trailing_text(self, eval_service):
        """JSON followed by trailing commentary."""
        payload = {"score": 7.0, "reasoning": "Good neutralization"}
        text = json.dumps(payload) + "\n\nI hope this helps!"
        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_anthropic_response(text)
            result = eval_service._call_teacher_anthropic("system", "user")
        assert result == payload

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_json_with_leading_text(self, eval_service):
        """Text before the JSON object."""
        payload = {"score": 8.0}
        text = "Here is my evaluation:\n\n" + json.dumps(payload)
        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_anthropic_response(text)
            result = eval_service._call_teacher_anthropic("system", "user")
        assert result == payload

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_multiple_json_objects_takes_first(self, eval_service):
        """Multiple JSON objects — should return the first valid one.

        This is the exact bug that caused 'Extra data: line 10 column 1'
        in staging. The old greedy regex matched from first { to last },
        which included both objects and failed json.loads().
        """
        first = {"score": 7.5, "domain_correct": True}
        second = {"extra": "metadata", "note": "ignore this"}
        text = json.dumps(first, indent=2) + "\n\n" + json.dumps(second)
        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_anthropic_response(text)
            result = eval_service._call_teacher_anthropic("system", "user")
        assert result == first

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_no_json_raises(self, eval_service):
        """No JSON at all should raise ValueError."""
        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_anthropic_response(
                "I cannot evaluate this article."
            )
            with pytest.raises(ValueError, match="No valid JSON found"):
                eval_service._call_teacher_anthropic("system", "user")

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"})
    def test_json_with_nested_braces(self, eval_service):
        """Nested JSON objects should parse correctly."""
        payload = {
            "score": 8.0,
            "details": {"neutralization": 8.5, "classification": 7.5},
        }
        text = "Result:\n" + json.dumps(payload)
        with patch("anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = _mock_anthropic_response(text)
            result = eval_service._call_teacher_anthropic("system", "user")
        assert result == payload
