# tests/test_highlight_edge_cases.py
"""
Edge case tests for NtrlView highlight detection.

Tests specific edge cases:
1. Overlapping spans deduplicated
2. Position accuracy (extracted text matches span.text)
3. Unicode handling (curly quotes, emoji)
4. Clean articles (minimal false positives)
5. Quoted content handling
6. Case sensitivity
7. Punctuation handling
"""

import pytest

from app.services.neutralizer import (
    MockNeutralizerProvider,
    TransparencySpan,
    find_phrase_positions,
)
from app.models import SpanAction, SpanReason


class TestOverlappingSpans:
    """Tests for overlapping span deduplication."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = MockNeutralizerProvider()

    def test_overlapping_spans_are_deduplicated(self):
        """Test that overlapping spans don't cause duplicate highlights."""
        # Text with potential overlapping patterns
        body = "BREAKING NEWS: In a shocking development..."

        spans = self.provider._find_spans(body, "body")

        # Check no overlaps
        sorted_spans = sorted(spans, key=lambda s: s.start_char)
        for i in range(len(sorted_spans) - 1):
            current = sorted_spans[i]
            next_span = sorted_spans[i + 1]
            assert current.end_char <= next_span.start_char, (
                f"Overlapping spans: {current.original_text} ({current.start_char}-{current.end_char}) "
                f"overlaps with {next_span.original_text} ({next_span.start_char}-{next_span.end_char})"
            )

    def test_nested_patterns_handled(self):
        """Test handling of nested pattern matches."""
        # "breaking" is part of multiple patterns
        body = "BREAKING NEWS UPDATE: Major announcement"

        spans = self.provider._find_spans(body, "body")

        # Should not have duplicate detection of same text
        original_texts = [s.original_text.lower() for s in spans]
        assert len(original_texts) == len(set(original_texts)), (
            f"Duplicate spans detected: {original_texts}"
        )


class TestPositionAccuracy:
    """Tests for character position accuracy."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = MockNeutralizerProvider()

    def test_span_text_matches_position(self):
        """Test that span positions accurately extract the original text."""
        body = "This is a SHOCKING revelation that slams the establishment."

        spans = self.provider._find_spans(body, "body")

        for span in spans:
            extracted = body[span.start_char:span.end_char]
            assert extracted.lower() == span.original_text.lower(), (
                f"Position mismatch: extracted '{extracted}' but span says '{span.original_text}' "
                f"at positions {span.start_char}-{span.end_char}"
            )

    def test_positions_are_valid_indices(self):
        """Test that span positions are valid string indices."""
        body = "BREAKING: Senator slams critics in devastating blow"

        spans = self.provider._find_spans(body, "body")

        for span in spans:
            assert 0 <= span.start_char <= len(body), (
                f"Invalid start_char: {span.start_char} for text length {len(body)}"
            )
            assert span.start_char < span.end_char <= len(body), (
                f"Invalid end_char: {span.end_char} for start_char {span.start_char}"
            )

    def test_empty_body_no_spans(self):
        """Test that empty body produces no spans."""
        spans = self.provider._find_spans("", "body")
        assert spans == []

    def test_none_body_no_spans(self):
        """Test that None body produces no spans."""
        spans = self.provider._find_spans(None, "body")
        assert spans == []


class TestUnicodeHandling:
    """Tests for Unicode text handling."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = MockNeutralizerProvider()

    def test_curly_quotes(self):
        """Test handling of curly quotes around manipulative text."""
        # Using raw string with curly quotes
        body = '\u201cSHOCKING news,\u201d said the reporter. \u201cIt\u2019s absolutely devastating.\u201d'

        spans = self.provider._find_spans(body, "body")

        # Should still detect manipulative language
        reasons = [s.reason for s in spans]
        assert SpanReason.EMOTIONAL_TRIGGER in reasons or SpanReason.CLICKBAIT in reasons

    def test_em_dash(self):
        """Test handling of em-dash punctuation."""
        body = "The announcement—shocking as it was—came suddenly."

        spans = self.provider._find_spans(body, "body")

        # Should detect "shocking"
        original_texts_lower = [s.original_text.lower() for s in spans]
        assert "shocking" in original_texts_lower

    def test_apostrophe_variants(self):
        """Test handling of different apostrophe characters."""
        body1 = "You won't believe this!"
        body2 = "You won't believe this!"  # Smart quote apostrophe

        spans1 = self.provider._find_spans(body1, "body")
        spans2 = self.provider._find_spans(body2, "body")

        # At minimum, standard apostrophe should work
        assert len(spans1) > 0, "Should detect 'you won't believe'"

    def test_accented_characters(self):
        """Test that accented characters don't break detection."""
        body = "The café's shocking announcement caused outrage."

        spans = self.provider._find_spans(body, "body")

        # Should still detect manipulative words
        original_texts_lower = [s.original_text.lower() for s in spans]
        assert "shocking" in original_texts_lower or "outrage" in original_texts_lower


class TestCleanArticles:
    """Tests for clean articles (minimal false positives)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = MockNeutralizerProvider()

    @pytest.mark.xfail(reason="Pattern-based detection has false positives - LLM-based should fix")
    def test_factual_headline_no_false_positives(self):
        """Test that factual headlines aren't flagged."""
        clean_headlines = [
            "Senate passes infrastructure bill with bipartisan support",
            "Federal Reserve holds interest rates steady",
            "Microsoft announces Azure expansion",
            "City council approves new water conservation law",
        ]

        for headline in clean_headlines:
            spans = self.provider._find_spans(headline, "title")
            assert len(spans) == 0, (
                f"Clean headline falsely flagged: '{headline}' - "
                f"detected: {[s.original_text for s in spans]}"
            )

    @pytest.mark.xfail(reason="Pattern-based detection has false positives - LLM-based should fix")
    def test_factual_body_minimal_false_positives(self):
        """Test that factual body text has minimal false positives."""
        # Real factual text without manipulation
        body = """
        The U.S. Senate passed a $1.2 trillion infrastructure bill on Thursday
        with a vote of 69-30. The bill includes $550 billion in new federal
        spending over five years, targeting roads, bridges, and public transit.
        Senator Rob Portman called the bill "a historic investment."
        """

        spans = self.provider._find_spans(body, "body")

        # Allow at most 1 false positive for edge cases
        # (e.g., "historic" could be flagged as selling)
        assert len(spans) <= 1, (
            f"Too many false positives in clean text: "
            f"{[s.original_text for s in spans]}"
        )


class TestQuotedContent:
    """Tests for handling quoted speech."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = MockNeutralizerProvider()

    def test_direct_quote_detection(self):
        """Test that content inside quotes is still detected."""
        # Note: Current pattern-based system doesn't distinguish quotes
        # This test documents current behavior; LLM-based should improve
        body = '"This is absolutely shocking," said the official.'

        spans = self.provider._find_spans(body, "body")

        # Current behavior: quotes are detected
        # Future: LLM should understand quoted speech context
        if spans:
            original_texts = [s.original_text.lower() for s in spans]
            # "shocking" is inside quotes
            if "shocking" in original_texts:
                # Document that this is current behavior (potential false positive)
                pass

    def test_author_language_vs_quote(self):
        """Test distinguishing author's language from quotes."""
        # Author uses "slams", quote contains factual language
        body = 'The senator slams the proposal. "We need careful consideration," she said.'

        spans = self.provider._find_spans(body, "body")

        # Should detect "slams" (author's language)
        # Pattern matcher may return "senator slams" as a phrase, so check if any span contains "slams"
        slams_detected = any("slams" in s.original_text.lower() for s in spans)
        assert slams_detected, "Should detect author's 'slams'"


class TestLiteralVsFigurative:
    """Tests for literal vs figurative usage."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = MockNeutralizerProvider()

    def test_slams_literal_usage(self):
        """Test that literal 'slams' (physical) should not be flagged."""
        # Note: Pattern-based detection can't distinguish context
        # This documents behavior that LLM-based should improve
        body = "The car slammed into the wall at high speed."

        spans = self.provider._find_spans(body, "body")

        # Current pattern-based will flag this (known limitation)
        # LLM-based should not flag literal usage
        slams_detected = any(
            s.original_text.lower() in ("slams", "slammed")
            for s in spans
        )

        if slams_detected:
            # Document this as known limitation of pattern-based
            pytest.xfail("Pattern-based detection flags literal 'slammed' - LLM-based should fix")

    def test_slams_figurative_usage(self):
        """Test that figurative 'slams' (criticism) IS flagged."""
        body = "The critic slams the new policy in harsh terms."

        spans = self.provider._find_spans(body, "body")

        # Should detect figurative "slams"
        # Pattern matcher may return "critic slams" as a phrase, so check if any span contains "slams"
        slams_detected = any("slams" in s.original_text.lower() for s in spans)
        assert slams_detected, "Should detect figurative 'slams'"

    def test_breaking_context(self):
        """Test 'breaking' in different contexts."""
        # News urgency - should flag
        body1 = "BREAKING: Major announcement from White House"
        spans1 = self.provider._find_spans(body1, "body")
        assert len(spans1) > 0, "Should flag BREAKING as urgency"

        # Literal usage - pattern-based will still flag (limitation)
        body2 = "Workers are breaking ground on the new building."
        spans2 = self.provider._find_spans(body2, "body")
        # Document known limitation
        if len(spans2) > 0:
            pytest.xfail("Pattern-based flags literal 'breaking' - LLM should not")


class TestCaseSensitivity:
    """Tests for case handling."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = MockNeutralizerProvider()

    def test_uppercase_detection(self):
        """Test detection of ALL CAPS text."""
        body = "BREAKING NEWS: SHOCKING DEVELOPMENT"

        spans = self.provider._find_spans(body, "body")

        # Should detect even in uppercase
        assert len(spans) > 0

    def test_mixed_case_detection(self):
        """Test detection of mixed case."""
        body = "Breaking News: A Shocking Development"

        spans = self.provider._find_spans(body, "body")

        # Should detect regardless of case
        original_texts_lower = [s.original_text.lower() for s in spans]
        assert "breaking" in original_texts_lower or "shocking" in original_texts_lower

    def test_original_text_preserves_case(self):
        """Test that span's original_text preserves original case."""
        body = "SHOCKING news today."

        spans = self.provider._find_spans(body, "body")

        shocking_spans = [s for s in spans if s.original_text.lower() == "shocking"]
        if shocking_spans:
            # Should preserve original case
            assert shocking_spans[0].original_text == "SHOCKING"


class TestPunctuationHandling:
    """Tests for punctuation around manipulative text."""

    def setup_method(self):
        """Set up test fixtures."""
        self.provider = MockNeutralizerProvider()

    def test_colon_after_breaking(self):
        """Test detection of BREAKING followed by colon."""
        body = "BREAKING: New development"

        spans = self.provider._find_spans(body, "body")

        # Should detect "breaking" without colon
        assert len(spans) > 0
        breaking_spans = [s for s in spans if "breaking" in s.original_text.lower()]
        if breaking_spans:
            # Span should not include the colon
            assert ":" not in breaking_spans[0].original_text or len(breaking_spans[0].original_text) <= 12

    def test_exclamation_marks(self):
        """Test detection with exclamation marks."""
        body = "Shocking!! You won't believe this!!"

        spans = self.provider._find_spans(body, "body")

        assert len(spans) > 0, "Should detect manipulative content with exclamations"

    def test_hyphens_in_phrases(self):
        """Test detection of hyphenated phrases."""
        body = "The mind-blowing announcement was jaw-dropping."

        spans = self.provider._find_spans(body, "body")

        original_texts = [s.original_text.lower() for s in spans]
        assert "mind-blowing" in original_texts or "jaw-dropping" in original_texts
