"""
Regression tests for manipulation category coverage in span detection prompts.

Ensures that all 13 manipulation categories are present in:
- MANIPULATION_CATEGORIES (shared constant)
- HIGH_RECALL_USER_PROMPT (Pass 1)
- ADVERSARIAL_USER_PROMPT (Pass 2)

Also includes article-level regression tests for specific phrases that were
missed in production (Feb 2026 — NY Post articles).
"""

import pytest

from app.services.neutralizer import (
    ADVERSARIAL_USER_PROMPT,
    FALSE_POSITIVE_PHRASES,
    HIGH_RECALL_USER_PROMPT,
    MANIPULATION_CATEGORIES,
)

# ---------------------------------------------------------------------------
# Canonical category definitions with key terms each prompt MUST mention
# ---------------------------------------------------------------------------

EXPECTED_CATEGORIES = {
    "URGENCY INFLATION": ["BREAKING", "scrambling", "crisis"],
    "EMOTIONAL TRIGGERS": ["shocking", "devastating", "slams", "outraged"],
    "CLICKBAIT": ["You won't believe", "Here's what happened"],
    "SELLING/HYPE": ["game-changer", "groundbreaking", "whopping", "staggering"],
    "AGENDA SIGNALING": ["radical-left", "far-left", "extremist", "socialist"],
    "LOADED VERBS": ["admits", "claims", "concedes", "whined", "plotted"],
    "AGENDA FRAMING": ["controversial decision", "bombshell report"],
    "SPORTS/EVENT HYPE": ["brilliant", "phenomenal", "blockbuster"],
    "LOADED PERSONAL DESCRIPTORS": ["rabble-rouser", "agitator", "firebrand"],
    "HYPERBOLIC ADJECTIVES": ["punishing", "brutal", "incredible"],
    "LOADED IDIOMS": ["came under fire", "in the crosshairs", "sent shockwaves"],
    "ENTERTAINMENT HYPE": ["romantic escape", "luxury yacht", "A-list couple"],
    "EDITORIAL VOICE": ["we're glad", "naturally", "of course"],
}


class TestManipulationCategoriesConstant:
    """MANIPULATION_CATEGORIES shared constant contains all 13 categories."""

    @pytest.mark.parametrize("category", EXPECTED_CATEGORIES.keys())
    def test_category_present_in_shared_constant(self, category: str):
        assert category in MANIPULATION_CATEGORIES, (
            f"Category '{category}' missing from MANIPULATION_CATEGORIES constant. "
            f"All 13 categories must be present to prevent detection gaps."
        )

    @pytest.mark.parametrize(
        "category,terms",
        EXPECTED_CATEGORIES.items(),
        ids=EXPECTED_CATEGORIES.keys(),
    )
    def test_key_terms_in_shared_constant(self, category: str, terms: list[str]):
        lower = MANIPULATION_CATEGORIES.lower()
        for term in terms:
            assert term.lower() in lower, (
                f"Key term '{term}' for category '{category}' missing from MANIPULATION_CATEGORIES constant."
            )


class TestHighRecallPromptCoverage:
    """HIGH_RECALL_USER_PROMPT includes MANIPULATION_CATEGORIES via concatenation."""

    def test_categories_injected(self):
        """The high-recall prompt must reference the shared categories block."""
        # Since we use string concatenation, the resulting prompt should contain
        # the full MANIPULATION_CATEGORIES text
        full_prompt = HIGH_RECALL_USER_PROMPT
        for category in EXPECTED_CATEGORIES:
            assert category in full_prompt, (
                f"Category '{category}' missing from HIGH_RECALL_USER_PROMPT. "
                f"Ensure MANIPULATION_CATEGORIES is injected correctly."
            )

    @pytest.mark.parametrize(
        "category,terms",
        EXPECTED_CATEGORIES.items(),
        ids=EXPECTED_CATEGORIES.keys(),
    )
    def test_key_terms_in_high_recall(self, category: str, terms: list[str]):
        lower = HIGH_RECALL_USER_PROMPT.lower()
        for term in terms:
            assert term.lower() in lower, (
                f"Key term '{term}' for category '{category}' missing from HIGH_RECALL_USER_PROMPT."
            )


class TestAdversarialPromptCoverage:
    """ADVERSARIAL_USER_PROMPT includes MANIPULATION_CATEGORIES via concatenation."""

    def test_categories_injected(self):
        full_prompt = ADVERSARIAL_USER_PROMPT
        for category in EXPECTED_CATEGORIES:
            assert category in full_prompt, (
                f"Category '{category}' missing from ADVERSARIAL_USER_PROMPT. "
                f"Ensure MANIPULATION_CATEGORIES is injected correctly."
            )

    @pytest.mark.parametrize(
        "category,terms",
        EXPECTED_CATEGORIES.items(),
        ids=EXPECTED_CATEGORIES.keys(),
    )
    def test_key_terms_in_adversarial(self, category: str, terms: list[str]):
        lower = ADVERSARIAL_USER_PROMPT.lower()
        for term in terms:
            assert term.lower() in lower, (
                f"Key term '{term}' for category '{category}' missing from ADVERSARIAL_USER_PROMPT."
            )


class TestFalsePositiveSafety:
    """Manipulative terms must NOT appear in FALSE_POSITIVE_PHRASES."""

    MANIPULATIVE_TERMS = [
        "radical-left",
        "far-left",
        "extremist",
        "rabble-rouser",
        "agitator",
        "whined",
        "plotted",
        "bombshell",
        "shockwaves",
        "militant",
        "socialist",
        "prowled",
        "snarled",
    ]

    @pytest.mark.parametrize("term", MANIPULATIVE_TERMS)
    def test_manipulative_term_not_in_false_positives(self, term: str):
        assert term.lower() not in {fp.lower() for fp in FALSE_POSITIVE_PHRASES}, (
            f"Manipulative term '{term}' must NOT be in FALSE_POSITIVE_PHRASES — "
            f"it would suppress valid span detections."
        )


class TestArticleRegressionFixtures:
    """
    Regression tests using phrases from the two articles that exposed the gap:
    - Article 1: "Nithya Raman" (NY Post) — agenda signaling
    - Article 2: "Anti-ICE Protests" (NY Post) — loaded verbs/descriptors
    """

    def test_radical_left_is_in_agenda_signaling(self):
        """'Radical-left' should be detectable via AGENDA SIGNALING category."""
        lower = MANIPULATION_CATEGORIES.lower()
        assert "radical-left" in lower

    def test_whined_is_in_loaded_verbs(self):
        """'whined' should be detectable via LOADED VERBS category."""
        lower = MANIPULATION_CATEGORIES.lower()
        assert "whined" in lower

    def test_rabble_rouser_is_in_loaded_descriptors(self):
        """'rabble-rouser' should be detectable via LOADED PERSONAL DESCRIPTORS."""
        lower = MANIPULATION_CATEGORIES.lower()
        assert "rabble-rouser" in lower

    def test_bombshell_is_in_agenda_framing(self):
        """'bombshell' should be detectable via AGENDA FRAMING category."""
        lower = MANIPULATION_CATEGORIES.lower()
        assert "bombshell" in lower

    def test_shockwaves_is_in_loaded_idioms(self):
        """'shockwaves' should be detectable via LOADED IDIOMS or EDITORIAL VOICE."""
        lower = MANIPULATION_CATEGORIES.lower()
        assert "shockwaves" in lower

    def test_plotted_is_in_loaded_verbs(self):
        """'plotted' should be detectable via LOADED VERBS category."""
        lower = MANIPULATION_CATEGORIES.lower()
        assert "plotted" in lower

    def test_far_left_is_in_agenda_signaling(self):
        """'far-left' should be detectable via AGENDA SIGNALING category."""
        lower = MANIPULATION_CATEGORIES.lower()
        assert "far-left" in lower

    def test_quoted_text_not_in_detection_categories(self):
        """
        Quoted text like 'armed thug kidnappers' should NOT be flagged.

        This is verified by the prompt instructions (NEVER FLAG QUOTED TEXT),
        not by the category list. We just confirm the exclusion language exists
        in the prompts.
        """
        assert "direct quotes" in HIGH_RECALL_USER_PROMPT.lower()
        assert "direct quotes" in ADVERSARIAL_USER_PROMPT.lower()


class TestSynthesisPromptCoverage:
    """DEFAULT_SYNTHESIS_DETAIL_FULL_PROMPT includes agenda signaling section."""

    def test_agenda_signaling_in_synthesis_prompt(self):
        from app.services.neutralizer import DEFAULT_SYNTHESIS_DETAIL_FULL_PROMPT

        lower = DEFAULT_SYNTHESIS_DETAIL_FULL_PROMPT.lower()
        assert "agenda signaling" in lower, (
            "AGENDA SIGNALING section missing from DEFAULT_SYNTHESIS_DETAIL_FULL_PROMPT. "
            "The synthesis model needs this to neutralize political labeling."
        )

    @pytest.mark.parametrize(
        "term",
        ["radical-left", "rabble-rouser", "whined", "bombshell", "shockwaves"],
    )
    def test_key_agenda_terms_in_synthesis_prompt(self, term: str):
        from app.services.neutralizer import DEFAULT_SYNTHESIS_DETAIL_FULL_PROMPT

        lower = DEFAULT_SYNTHESIS_DETAIL_FULL_PROMPT.lower()
        assert term.lower() in lower, (
            f"Term '{term}' missing from DEFAULT_SYNTHESIS_DETAIL_FULL_PROMPT. "
            f"The synthesis model must know to neutralize this term."
        )
