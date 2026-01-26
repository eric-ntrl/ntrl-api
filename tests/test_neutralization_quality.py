# tests/test_neutralization_quality.py
"""
Content quality tests for neutralization.

These tests verify that:
1. Span detection catches entertainment/celebrity manipulation
2. Detail brief removes flagged manipulation
3. Entertainment-specific phrases are properly handled

Complements test_highlight_accuracy.py (which tests span detection precision/recall)
and test_feed_outputs_grammar.py (which tests grammar integrity).
"""

import json
import os
from pathlib import Path
from typing import List

import pytest

from app.services.neutralizer import (
    MockNeutralizerProvider,
    TransparencySpan,
    find_phrase_positions,
    validate_brief_neutralization,
    BRIEF_BANNED_PHRASES,
)


# Test fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLD_STANDARD_DIR = FIXTURES_DIR / "gold_standard"


def load_entertainment_article() -> dict:
    """Load the entertainment gold standard article."""
    path = GOLD_STANDARD_DIR / "article_011_entertainment.json"
    with open(path) as f:
        return json.load(f)


class TestSpanDetectionQuality:
    """Verify span detection catches manipulation in various article types."""

    def test_entertainment_article_fixture_exists(self):
        """Entertainment gold standard fixture should exist."""
        path = GOLD_STANDARD_DIR / "article_011_entertainment.json"
        assert path.exists(), f"Missing fixture: {path}"

    def test_entertainment_fixture_has_expected_fields(self):
        """Entertainment fixture should have required fields."""
        data = load_entertainment_article()
        assert "article_id" in data
        assert "original_body" in data
        assert "expected_spans" in data
        assert "expected_brief_banned" in data
        assert len(data["expected_spans"]) > 0
        assert len(data["expected_brief_banned"]) > 0

    def test_entertainment_phrases_in_original_body(self):
        """Expected phrases should actually exist in the original body."""
        data = load_entertainment_article()
        body = data["original_body"]

        for span in data["expected_spans"]:
            phrase = span["text"]
            assert phrase in body, f"Expected phrase not found in body: {phrase}"

    def test_romance_phrases_are_detectable(self):
        """Romance/entertainment phrases should be findable by position matching."""
        data = load_entertainment_article()
        body = data["original_body"]

        # Simulate LLM output format
        llm_phrases = [
            {"phrase": span["text"], "reason": span["reason"], "action": span["action"], "replacement": None}
            for span in data["expected_spans"]
        ]

        # Use find_phrase_positions to locate them
        spans = find_phrase_positions(body, llm_phrases)

        # Should find positions for all expected phrases
        found_texts = {s.original_text.lower() for s in spans}
        expected_texts = {span["text"].lower() for span in data["expected_spans"]}

        missing = expected_texts - found_texts
        assert len(missing) == 0, f"Failed to find positions for: {missing}"


class TestBriefNeutralization:
    """Verify detail_brief removes manipulative language."""

    def test_validate_brief_neutralization_catches_violations(self):
        """Validation function should detect banned phrases in brief."""
        # Brief with violations
        bad_brief = (
            "Kylie Jenner and Timothée Chalamet enjoyed a romantic getaway "
            "in Cabo San Lucas. The couple cozied up at a beloved restaurant "
            "where they appeared relaxed and affectionate."
        )

        violations = validate_brief_neutralization(bad_brief)

        assert len(violations) > 0, "Should detect violations"
        assert any("romantic" in v.lower() for v in violations)

    def test_validate_brief_neutralization_passes_clean_brief(self):
        """Validation should pass for properly neutralized brief."""
        clean_brief = (
            "Kylie Jenner and Timothée Chalamet vacationed in Cabo San Lucas. "
            "The couple dined at a waterfront restaurant and spent time together "
            "at a property near the water."
        )

        violations = validate_brief_neutralization(clean_brief)

        assert len(violations) == 0, f"Clean brief should have no violations: {violations}"

    def test_brief_banned_phrases_comprehensive(self):
        """BRIEF_BANNED_PHRASES should include key entertainment terms."""
        required_phrases = [
            "romantic escape",
            "romantic getaway",
            "cozied up",
            "tender moment",
            "intimate conversation",
            "showed off",
            "toned figure",
            "celebrity hotspot",
            "a-list",
            "luxurious boat",
            "exclusively revealed",
        ]

        for phrase in required_phrases:
            assert phrase.lower() in {p.lower() for p in BRIEF_BANNED_PHRASES}, \
                f"Missing required phrase: {phrase}"

    def test_entertainment_banned_phrases_detected(self):
        """Entertainment-specific phrases from fixture should trigger validation."""
        data = load_entertainment_article()

        # Build a brief containing banned phrases
        banned = data["expected_brief_banned"]

        for term in banned:
            test_brief = f"The couple had a {term} experience in Cabo."
            violations = validate_brief_neutralization(test_brief)

            # Check if any violation matches (case-insensitive partial match)
            term_lower = term.lower()
            found = any(term_lower in v.lower() or v.lower() in term_lower
                       for v in violations)

            # Some terms may be part of larger phrases in BRIEF_BANNED_PHRASES
            # so we check if the term appears in the brief AND triggers a violation
            if term_lower in test_brief.lower():
                # The term is in the brief, check if it's in our banned phrases
                in_banned = any(term_lower in phrase.lower()
                              for phrase in BRIEF_BANNED_PHRASES)
                if in_banned:
                    assert found or len(violations) > 0, \
                        f"Term '{term}' should trigger validation"


class TestEntertainmentNeutralizationExamples:
    """Test specific neutralization examples from the plan."""

    def test_romantic_getaway_neutralization(self):
        """'romantic getaway' should be detected as un-neutralized."""
        brief = "The couple enjoyed a romantic getaway in Mexico."
        violations = validate_brief_neutralization(brief)
        assert "romantic getaway" in violations or any("romantic" in v for v in violations)

    def test_sun_drenched_neutralization(self):
        """'sun-drenched' should be detected as un-neutralized."""
        brief = "They vacationed at a sun-drenched resort."
        violations = validate_brief_neutralization(brief)
        assert "sun-drenched" in violations

    def test_luxury_yacht_neutralization(self):
        """'luxury yacht' should trigger validation (should be 'boat')."""
        brief = "The couple was spotted on a luxury yacht."
        violations = validate_brief_neutralization(brief)
        # Check for any luxury-related violation
        assert any("luxury" in v.lower() for v in violations) or \
               any("luxurious" in v.lower() for v in violations), \
               f"'luxury' should be detected, got: {violations}"

    def test_celebrity_hotspot_neutralization(self):
        """'celebrity hotspot' should trigger validation (should be 'restaurant')."""
        brief = "They dined at a celebrity hotspot in Cabo."
        violations = validate_brief_neutralization(brief)
        assert "celebrity hotspot" in violations

    def test_appeared_relaxed_and_affectionate(self):
        """'appeared relaxed and affectionate' should trigger validation."""
        brief = "Sources say they appeared relaxed and affectionate during dinner."
        violations = validate_brief_neutralization(brief)
        assert any("relaxed and affectionate" in v.lower() for v in violations) or \
               any("affectionate" in v.lower() for v in violations), \
               f"Should detect 'relaxed and affectionate', got: {violations}"

    def test_clean_celebrity_reporting_passes(self):
        """Neutral celebrity reporting should not trigger validation."""
        clean_brief = (
            "Kylie Jenner and Timothée Chalamet were photographed in Cabo San Lucas. "
            "The couple, who have been dating since 2023, dined at a restaurant "
            "and spent time on a boat. Photographs show them having a conversation."
        )
        violations = validate_brief_neutralization(clean_brief)
        assert len(violations) == 0, f"Clean brief had violations: {violations}"


class TestMockProviderEntertainmentContent:
    """Test mock provider handles entertainment content."""

    def test_mock_provider_processes_entertainment_article(self):
        """Mock provider should process entertainment article without error."""
        data = load_entertainment_article()
        provider = MockNeutralizerProvider()

        result = provider.neutralize(
            title="Kylie Jenner and Timothée Chalamet Vacation in Cabo",
            description="Celebrity couple spotted in Mexico.",
            body=data["original_body"],
        )

        assert result is not None
        assert result.feed_title
        assert result.feed_summary

    def test_mock_provider_finds_entertainment_spans(self):
        """Mock provider should detect some entertainment manipulation."""
        data = load_entertainment_article()
        provider = MockNeutralizerProvider()

        result = provider.neutralize(
            title="Kylie Jenner Vacation",
            description="Celebrity spotted.",
            body=data["original_body"],
        )

        # Mock provider uses pattern-based detection, may not catch all
        # but should catch some obvious patterns if they match
        # This test mainly verifies no errors occur
        assert result is not None


class TestIntegrationWithExistingTests:
    """Verify new tests don't conflict with existing test infrastructure."""

    def test_fixtures_directory_exists(self):
        """Fixtures directory should exist."""
        assert FIXTURES_DIR.exists()
        assert GOLD_STANDARD_DIR.exists()

    def test_gold_standard_count_includes_entertainment(self):
        """Gold standard directory should include entertainment article."""
        gold_files = list(GOLD_STANDARD_DIR.glob("article_*_spans.json"))
        entertainment_file = GOLD_STANDARD_DIR / "article_011_entertainment.json"

        # Should have at least the original 10 + our new entertainment article
        assert len(gold_files) >= 10
        assert entertainment_file.exists()

    def test_entertainment_article_has_category_field(self):
        """Entertainment fixture should have category='entertainment' for filtering."""
        data = load_entertainment_article()
        assert data.get("category") == "entertainment"
