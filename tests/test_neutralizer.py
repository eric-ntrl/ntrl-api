# tests/test_neutralizer.py
"""
Unit tests for neutralization service.
"""

import pytest
from app.services.neutralizer import (
    MockNeutralizerProvider,
    NeutralizationResult,
    TransparencySpan,
)
from app.models import SpanAction, SpanReason


class TestMockNeutralizerProvider:
    """Tests for the MockNeutralizerProvider."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = MockNeutralizerProvider()

    def test_provider_properties(self):
        """Test provider name and model."""
        assert self.provider.name == "mock"
        assert self.provider.model_name == "mock-v1"

    def test_neutralize_clean_content(self):
        """Test neutralizing content without manipulative language."""
        result = self.provider.neutralize(
            title="City council approves new budget",
            description="The council voted to approve the annual budget.",
            body=None,
        )

        assert isinstance(result, NeutralizationResult)
        assert result.has_manipulative_content == False
        assert len(result.spans) == 0
        assert result.neutral_headline == "City council approves new budget"

    def test_neutralize_clickbait(self):
        """Test neutralizing clickbait language."""
        result = self.provider.neutralize(
            title="SHOCKING: You won't believe what happened next!",
            description=None,
            body=None,
        )

        assert result.has_manipulative_content == True
        assert len(result.spans) > 0

        # Check that "shocking" was detected
        clickbait_spans = [s for s in result.spans if s.reason == SpanReason.CLICKBAIT]
        assert len(clickbait_spans) > 0

        # Check headline was neutralized (no "shocking")
        assert "shocking" not in result.neutral_headline.lower()

    def test_neutralize_emotional_triggers(self):
        """Test neutralizing emotional trigger words."""
        result = self.provider.neutralize(
            title="Senator slams critics in furious response",
            description=None,
            body=None,
        )

        assert result.has_manipulative_content == True

        # Check for emotional trigger detection
        emotional_spans = [s for s in result.spans if s.reason == SpanReason.EMOTIONAL_TRIGGER]
        assert len(emotional_spans) > 0

        # "slams" should be replaced with "criticizes"
        assert "slams" not in result.neutral_headline.lower()

    def test_neutralize_urgency_inflation(self):
        """Test neutralizing urgency language."""
        result = self.provider.neutralize(
            title="BREAKING: Major announcement happening now",
            description=None,
            body=None,
        )

        assert result.has_manipulative_content == True

        # Check for urgency detection
        urgency_spans = [s for s in result.spans if s.reason == SpanReason.URGENCY_INFLATION]
        assert len(urgency_spans) > 0

        # "breaking" should be removed
        assert "breaking" not in result.neutral_headline.lower()

    def test_span_positions_are_valid(self):
        """Test that span positions are valid."""
        title = "SHOCKING: Senator slams critics"
        result = self.provider.neutralize(title=title, description=None, body=None)

        for span in result.spans:
            # Positions should be within text bounds
            assert span.start_char >= 0
            assert span.end_char <= len(title)
            assert span.start_char < span.end_char

            # Original text should match position
            assert title[span.start_char:span.end_char].lower() == span.original_text.lower()

    def test_spans_do_not_overlap(self):
        """Test that spans don't overlap."""
        result = self.provider.neutralize(
            title="SHOCKING BREAKING NEWS: Furious senator slams critics",
            description=None,
            body=None,
        )

        spans = sorted(result.spans, key=lambda s: s.start_char)

        for i in range(len(spans) - 1):
            # Each span should end before the next one starts
            assert spans[i].end_char <= spans[i + 1].start_char

    def test_summary_generation(self):
        """Test that summary is generated."""
        result = self.provider.neutralize(
            title="Event occurs",
            description="A significant event occurred today with important implications.",
            body=None,
        )

        assert result.neutral_summary is not None
        assert len(result.neutral_summary) > 0

    def test_structured_parts(self):
        """Test that structured parts are generated."""
        result = self.provider.neutralize(
            title="Important event happens",
            description="Details about the important event.",
            body=None,
        )

        # What happened should be set
        assert result.what_happened is not None

        # What is uncertain should always be set (default message)
        assert result.what_is_uncertain is not None


class TestNeutralizationDeterminism:
    """Test that neutralization is deterministic."""

    def test_same_input_same_output(self):
        """Test that the same input produces the same output."""
        provider = MockNeutralizerProvider()

        title = "SHOCKING: Senator slams critics in furious response"

        result1 = provider.neutralize(title=title, description=None, body=None)
        result2 = provider.neutralize(title=title, description=None, body=None)

        assert result1.neutral_headline == result2.neutral_headline
        assert result1.has_manipulative_content == result2.has_manipulative_content
        assert len(result1.spans) == len(result2.spans)

        for s1, s2 in zip(result1.spans, result2.spans):
            assert s1.start_char == s2.start_char
            assert s1.end_char == s2.end_char
            assert s1.original_text == s2.original_text
            assert s1.reason == s2.reason
