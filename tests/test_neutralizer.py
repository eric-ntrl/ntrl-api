# tests/test_neutralizer.py
"""
Unit tests for neutralization service.
"""

import pytest
from app.services.neutralizer import (
    MockNeutralizerProvider,
    NeutralizationResult,
    TransparencySpan,
    DetailFullResult,
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
        assert result.feed_title == "City council approves new budget"

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
        assert "shocking" not in result.feed_title.lower()

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
        assert "slams" not in result.feed_title.lower()

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
        assert "breaking" not in result.feed_title.lower()

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

        assert result.feed_summary is not None
        assert len(result.feed_summary) > 0

    def test_detail_fields_are_none_in_mock(self):
        """Test that detail fields are None in mock provider (generated in future phases)."""
        result = self.provider.neutralize(
            title="Important event happens",
            description="Details about the important event.",
            body=None,
        )

        # Mock provider doesn't generate detail fields
        assert result.detail_title is None
        assert result.detail_brief is None
        assert result.detail_full is None


class TestNeutralizationDeterminism:
    """Test that neutralization is deterministic."""

    def test_same_input_same_output(self):
        """Test that the same input produces the same output."""
        provider = MockNeutralizerProvider()

        title = "SHOCKING: Senator slams critics in furious response"

        result1 = provider.neutralize(title=title, description=None, body=None)
        result2 = provider.neutralize(title=title, description=None, body=None)

        assert result1.feed_title == result2.feed_title
        assert result1.has_manipulative_content == result2.has_manipulative_content
        assert len(result1.spans) == len(result2.spans)

        for s1, s2 in zip(result1.spans, result2.spans):
            assert s1.start_char == s2.start_char
            assert s1.end_char == s2.end_char
            assert s1.original_text == s2.original_text
            assert s1.reason == s2.reason


class TestDetailFullNeutralization:
    """Tests for _neutralize_detail_full() method (Call 1: Filter & Track)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = MockNeutralizerProvider()

    def test_neutralize_detail_full_returns_correct_type(self):
        """Test that _neutralize_detail_full returns DetailFullResult."""
        body = "This is a test article with neutral content."
        result = self.provider._neutralize_detail_full(body)

        assert isinstance(result, DetailFullResult)
        assert isinstance(result.detail_full, str)
        assert isinstance(result.spans, list)

    def test_neutralize_detail_full_empty_body(self):
        """Test handling of empty body."""
        result = self.provider._neutralize_detail_full("")

        assert result.detail_full == ""
        assert result.spans == []

    def test_neutralize_detail_full_clean_content(self):
        """Test filtering content without manipulative language."""
        body = "The city council approved a new budget yesterday. The mayor said it would improve services."
        result = self.provider._neutralize_detail_full(body)

        assert result.detail_full == body  # No changes needed
        assert len(result.spans) == 0

    def test_neutralize_detail_full_with_urgency(self):
        """Test filtering urgency language from body."""
        body = "BREAKING: The senator announced new legislation today."
        result = self.provider._neutralize_detail_full(body)

        assert "breaking" not in result.detail_full.lower()
        assert len(result.spans) > 0
        assert any(s.reason == SpanReason.URGENCY_INFLATION for s in result.spans)

    def test_neutralize_detail_full_with_emotional_triggers(self):
        """Test filtering emotional trigger words from body."""
        body = "The president slams critics in a furious response to the report."
        result = self.provider._neutralize_detail_full(body)

        assert "slams" not in result.detail_full.lower()
        assert len(result.spans) > 0
        assert any(s.reason == SpanReason.EMOTIONAL_TRIGGER for s in result.spans)

    def test_neutralize_detail_full_spans_valid(self):
        """Test that returned spans are valid TransparencySpan objects."""
        body = "SHOCKING: Senator slams critics in breaking news."
        result = self.provider._neutralize_detail_full(body)

        for span in result.spans:
            assert isinstance(span, TransparencySpan)
            assert span.field == "body"
            assert span.start_char >= 0
            assert span.end_char <= len(body)
            assert span.start_char < span.end_char
            assert isinstance(span.action, SpanAction)
            assert isinstance(span.reason, SpanReason)

    def test_neutralize_detail_full_preserves_quotes(self):
        """Test that quotes are preserved in filtered article."""
        body = 'The senator said, "This is an important decision for our future."'
        result = self.provider._neutralize_detail_full(body)

        assert '"This is an important decision for our future."' in result.detail_full

    def test_neutralize_detail_full_determinism(self):
        """Test that _neutralize_detail_full is deterministic."""
        body = "BREAKING: Senator slams critics in shocking response to urgent crisis."

        result1 = self.provider._neutralize_detail_full(body)
        result2 = self.provider._neutralize_detail_full(body)

        assert result1.detail_full == result2.detail_full
        assert len(result1.spans) == len(result2.spans)

        for s1, s2 in zip(result1.spans, result2.spans):
            assert s1.start_char == s2.start_char
            assert s1.end_char == s2.end_char
            assert s1.original_text == s2.original_text
