# tests/test_deduper.py
"""
Unit tests for deduplication service.
"""

import pytest
from app.services.deduper import Deduper


class TestDeduper:
    """Tests for the Deduper service."""

    def test_normalize_text(self):
        """Test text normalization."""
        deduper = Deduper()

        # Basic normalization
        assert deduper.normalize_text("Hello World!") == "hello world"
        assert deduper.normalize_text("  Multiple   Spaces  ") == "multiple spaces"
        assert deduper.normalize_text("UPPERCASE") == "uppercase"

        # Punctuation removal
        assert deduper.normalize_text("Hello, World!") == "hello world"
        assert deduper.normalize_text("What's up?") == "whats up"

        # Empty/None handling
        assert deduper.normalize_text("") == ""
        assert deduper.normalize_text(None) == ""

    def test_hash_url(self):
        """Test URL hashing."""
        deduper = Deduper()

        # Same URL should produce same hash
        hash1 = deduper.hash_url("https://example.com/article/1")
        hash2 = deduper.hash_url("https://example.com/article/1")
        assert hash1 == hash2

        # Different URLs should produce different hashes
        hash3 = deduper.hash_url("https://example.com/article/2")
        assert hash1 != hash3

        # Hash should be 64 chars (SHA256 hex)
        assert len(hash1) == 64

    def test_hash_title(self):
        """Test title hashing (normalizes before hashing)."""
        deduper = Deduper()

        # Same title with different formatting should match
        hash1 = deduper.hash_title("Breaking: Major Event Happens!")
        hash2 = deduper.hash_title("BREAKING: MAJOR EVENT HAPPENS")
        assert hash1 == hash2

        # Different titles should not match
        hash3 = deduper.hash_title("Different headline entirely")
        assert hash1 != hash3

    def test_jaccard_similarity(self):
        """Test Jaccard similarity calculation."""
        deduper = Deduper()

        # Identical texts
        sim = deduper.jaccard_similarity("hello world", "hello world")
        assert sim == 1.0

        # Completely different
        sim = deduper.jaccard_similarity("hello world", "foo bar baz")
        assert sim == 0.0

        # Partial overlap
        sim = deduper.jaccard_similarity("hello world foo", "hello world bar")
        # "hello", "world" shared; "foo" and "bar" unique
        # Intersection: 2, Union: 4 -> 0.5
        assert sim == 0.5

        # Empty strings
        sim = deduper.jaccard_similarity("", "hello")
        assert sim == 0.0

    def test_similarity_threshold(self):
        """Test that similar titles are detected."""
        deduper = Deduper()

        # Very similar headlines (same story, different sources)
        title1 = "President announces new economic policy"
        title2 = "President announces new economic plan"

        sim = deduper.jaccard_similarity(title1, title2)
        # Should be above threshold (0.85)
        assert sim >= 0.8

        # Different stories
        title3 = "Weather forecast shows rain tomorrow"
        sim2 = deduper.jaccard_similarity(title1, title3)
        assert sim2 < 0.5
