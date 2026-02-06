# tests/unit/test_content_sanitizer.py
"""
Unit tests for content sanitizer utilities.

Covers:
- Truncation marker detection (has_truncation_markers)
- Truncation marker stripping (strip_truncation_markers)
- All marker variants: symbols, chars, characters
- Edge cases: None, empty, multiple markers, mid-body markers
"""

import pytest

from app.utils.content_sanitizer import (
    has_truncation_markers,
    strip_truncation_markers,
    TRUNCATION_PATTERN,
)


class TestHasTruncationMarkers:
    """Tests for has_truncation_markers()."""

    def test_detects_symbols_marker(self):
        assert has_truncation_markers("Article text...[1811 symbols]") is True

    def test_detects_chars_marker(self):
        assert has_truncation_markers("Article text...[234 chars]") is True

    def test_detects_characters_marker(self):
        assert has_truncation_markers("Article text...[500 characters]") is True

    def test_detects_singular_symbol(self):
        assert has_truncation_markers("Short...[1 symbol]") is True

    def test_detects_singular_char(self):
        assert has_truncation_markers("Short...[1 char]") is True

    def test_false_for_clean_text(self):
        assert has_truncation_markers("This is a normal article body.") is False

    def test_false_for_none(self):
        assert has_truncation_markers(None) is False

    def test_false_for_empty_string(self):
        assert has_truncation_markers("") is False

    def test_detects_mid_body_marker(self):
        body = "First paragraph...[500 symbols] Second paragraph continues here."
        assert has_truncation_markers(body) is True

    def test_detects_marker_with_extra_whitespace(self):
        assert has_truncation_markers("Text...[1811  symbols]") is True

    def test_detects_space_before_bracket(self):
        """Space between ... and [ should match (Perigon variant)."""
        assert has_truncation_markers("Article text... [358 symbols]") is True

    def test_detects_multiple_spaces_before_bracket(self):
        assert has_truncation_markers("Article text...  [358 symbols]") is True

    def test_false_for_similar_but_different_pattern(self):
        """Brackets without dots should not match."""
        assert has_truncation_markers("Article text [1811 symbols]") is False

    def test_false_for_dots_without_brackets(self):
        assert has_truncation_markers("Article text... continues here") is False


class TestStripTruncationMarkers:
    """Tests for strip_truncation_markers()."""

    def test_strips_symbols_marker(self):
        result = strip_truncation_markers("Article text...[1811 symbols]")
        assert result == "Article text"

    def test_strips_chars_marker(self):
        result = strip_truncation_markers("Article text...[234 chars]")
        assert result == "Article text"

    def test_strips_characters_marker(self):
        result = strip_truncation_markers("Article text...[500 characters]")
        assert result == "Article text"

    def test_preserves_normal_text(self):
        text = "This is a completely normal article body with no markers."
        assert strip_truncation_markers(text) == text

    def test_returns_none_for_none(self):
        assert strip_truncation_markers(None) is None

    def test_returns_empty_for_empty(self):
        assert strip_truncation_markers("") == ""

    def test_strips_multiple_markers(self):
        body = "First section...[200 symbols] and middle...[300 chars] end."
        result = strip_truncation_markers(body)
        assert result == "First section and middle end."

    def test_strips_mid_body_marker(self):
        body = "Start of article...[1811 symbols] rest continues here."
        result = strip_truncation_markers(body)
        assert result == "Start of article rest continues here."

    def test_strips_space_variant(self):
        result = strip_truncation_markers("Article text... [358 symbols]")
        assert result == "Article text"

    def test_strips_multiple_space_variant(self):
        result = strip_truncation_markers("Article text...  [358 symbols]")
        assert result == "Article text"

    def test_strips_and_rstrips_trailing_whitespace(self):
        body = "Article text...[1811 symbols]   "
        result = strip_truncation_markers(body)
        assert result == "Article text"
