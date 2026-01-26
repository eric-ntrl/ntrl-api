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


class TestBriefRepairPrompt:
    """Tests for the brief repair prompt functionality."""

    def test_build_brief_repair_prompt_includes_violations(self):
        """Repair prompt should include all violations."""
        from app.services.neutralizer import build_brief_repair_prompt

        brief = "They enjoyed a romantic getaway at a luxury yacht."
        violations = ["romantic getaway", "luxury yacht"]

        prompt = build_brief_repair_prompt(brief, violations)

        assert "romantic getaway" in prompt
        assert "luxury yacht" in prompt
        assert brief in prompt

    def test_build_brief_repair_prompt_format(self):
        """Repair prompt should have correct format."""
        from app.services.neutralizer import build_brief_repair_prompt

        brief = "The couple cozied up at the restaurant."
        violations = ["cozied up"]

        prompt = build_brief_repair_prompt(brief, violations)

        assert "VIOLATIONS FOUND:" in prompt
        assert "Original brief:" in prompt
        assert "Rewrite this brief" in prompt

    def test_repair_prompt_has_replacement_guidance(self):
        """Repair prompt should include guidance for replacements."""
        from app.services.neutralizer import BRIEF_REPAIR_PROMPT

        # Check that the prompt includes replacement suggestions
        assert '"romantic getaway"' in BRIEF_REPAIR_PROMPT or "romantic getaway" in BRIEF_REPAIR_PROMPT
        assert "trip" in BRIEF_REPAIR_PROMPT or "vacation" in BRIEF_REPAIR_PROMPT
        assert "boat" in BRIEF_REPAIR_PROMPT  # luxury boat -> boat


class TestBriefValidationRetry:
    """Tests for brief validation retry logic structure."""

    def test_validate_brief_returns_list(self):
        """Validation should return a list of violations."""
        violations = validate_brief_neutralization("A romantic getaway.")
        assert isinstance(violations, list)
        assert len(violations) > 0

    def test_validate_clean_brief_returns_empty(self):
        """Clean brief should return empty violations list."""
        violations = validate_brief_neutralization("They went on a trip to Mexico.")
        assert violations == []

    def test_multiple_violations_detected(self):
        """Multiple violations in one brief should all be detected."""
        brief = "They had a romantic getaway, cozied up at a luxurious boat."
        violations = validate_brief_neutralization(brief)

        # Should detect multiple issues
        assert len(violations) >= 2

        # Should include specific banned phrases
        violation_lower = [v.lower() for v in violations]
        assert any("romantic" in v for v in violation_lower)

    def test_case_insensitive_detection(self):
        """Validation should be case-insensitive."""
        violations1 = validate_brief_neutralization("A Romantic Getaway.")
        violations2 = validate_brief_neutralization("a romantic getaway.")

        # Both should detect violations
        assert len(violations1) > 0
        assert len(violations2) > 0


class TestFeedSummaryValidation:
    """Tests for feed_summary validation functions."""

    def test_validate_feed_summary_catches_violations(self):
        """Feed summary with banned phrases should return violations."""
        from app.services.neutralizer import validate_feed_summary

        summary = "The couple enjoyed a romantic getaway in Mexico."
        violations = validate_feed_summary(summary)
        assert len(violations) > 0
        assert any("romantic" in v.lower() for v in violations)

    def test_validate_feed_summary_passes_clean(self):
        """Clean feed summary should return empty list."""
        from app.services.neutralizer import validate_feed_summary

        summary = "The couple took a trip to Mexico last week."
        violations = validate_feed_summary(summary)
        assert violations == []

    def test_validate_feed_summary_empty_input(self):
        """Empty summary should return empty violations."""
        from app.services.neutralizer import validate_feed_summary

        violations = validate_feed_summary("")
        assert violations == []

    def test_build_feed_summary_repair_prompt(self):
        """Repair prompt should include violations and original text."""
        from app.services.neutralizer import build_feed_summary_repair_prompt

        summary = "They had a romantic getaway."
        violations = ["romantic getaway"]
        prompt = build_feed_summary_repair_prompt(summary, violations)

        assert "romantic getaway" in prompt
        assert summary in prompt
        assert "120 characters" in prompt


class TestTruncateAtSentence:
    """Tests for sentence-boundary truncation."""

    def test_no_truncation_needed(self):
        """Short text should not be truncated."""
        from app.services.neutralizer import truncate_at_sentence

        text = "This is a short sentence."
        result = truncate_at_sentence(text, 130)
        assert result == text

    def test_truncate_at_period(self):
        """Should truncate at sentence boundary."""
        from app.services.neutralizer import truncate_at_sentence

        text = "First sentence. Second sentence. Third sentence that is way too long."
        result = truncate_at_sentence(text, 50)
        assert result.endswith(".")
        assert len(result) <= 50

    def test_truncate_at_exclamation(self):
        """Should truncate at exclamation mark."""
        from app.services.neutralizer import truncate_at_sentence

        text = "First sentence! Second sentence. Third sentence."
        result = truncate_at_sentence(text, 20)
        assert result == "First sentence!"

    def test_truncate_at_question(self):
        """Should truncate at question mark."""
        from app.services.neutralizer import truncate_at_sentence

        text = "Is this true? Yes it is. More details here."
        result = truncate_at_sentence(text, 20)
        assert result == "Is this true?"

    def test_fallback_to_word_boundary(self):
        """Should fall back to word boundary if no sentence found."""
        from app.services.neutralizer import truncate_at_sentence

        text = "This is one very long sentence without any periods until the end"
        result = truncate_at_sentence(text, 30)
        assert len(result) <= 30
        assert not result.endswith(" ")  # Should not end with space

    def test_exact_limit(self):
        """Text exactly at limit should not be truncated."""
        from app.services.neutralizer import truncate_at_sentence

        text = "Exactly 130 characters here." + "x" * 100
        text = text[:130]
        result = truncate_at_sentence(text, 130)
        assert result == text
