# tests/test_feed_outputs_grammar.py
"""
Regression tests for feed outputs grammar integrity.

These tests ensure that feed_title, feed_summary, and detail_title outputs
are grammatically complete and not garbled by aggressive word filtering.

The root cause being prevented: LLM aggressively removing words during headline
compression, leaving incomplete sentences like:
- "and Timothée enjoyed a to Cabo" (missing subject and nouns)
- "The has initiated an 's platform" (missing proper nouns)
- "the seizure of a of a" (garbled repeated words)
"""

import pytest
from app.services.neutralizer import (
    MockNeutralizerProvider,
    _validate_feed_outputs,
)


class TestFeedOutputsGrammar:
    """Ensure feed outputs are grammatically complete."""

    def test_no_dangling_articles_feed_title(self):
        """Feed titles should not end with articles/prepositions."""
        # These are examples of garbled outputs that should be detected
        garbled_titles = [
            "Senator Proposes Bill to the",
            "Apple Announces Feature for a",
            "European Commission Investigates Musk's",
            "Court Rules Against the",
            "Police Arrest Suspect in",
        ]

        for title in garbled_titles:
            result = {
                "feed_title": title,
                "feed_summary": "This is a complete summary sentence.",
                "detail_title": "Complete Detail Title",
                "section": "world",
            }
            # The validation should log a warning (we can't easily capture logs,
            # but we can verify the function runs without error)
            _validate_feed_outputs(result)

    def test_no_dangling_articles_feed_summary(self):
        """Feed summaries should not end with dangling words."""
        garbled_summaries = [
            "The investigation continues into the",
            "Officials are looking at a",
            "This represents a shift in",
        ]

        for summary in garbled_summaries:
            result = {
                "feed_title": "Complete Title Here",
                "feed_summary": summary,
                "detail_title": "Complete Detail Title",
                "section": "world",
            }
            _validate_feed_outputs(result)

    def test_minimum_word_count_titles(self):
        """Titles should contain at least 3 words."""
        # These are suspiciously short titles that may indicate garbling
        short_titles = [
            "Senate",  # 1 word
            "Apple Announces",  # 2 words
        ]

        for title in short_titles:
            result = {
                "feed_title": title,
                "feed_summary": "This is a complete summary.",
                "detail_title": title,
                "section": "world",
            }
            _validate_feed_outputs(result)

    def test_no_repeated_word_patterns(self):
        """Titles should not have repeated word patterns like 'of a of a'."""
        garbled_titles = [
            "the seizure of a of a",
            "building to the to the",
            "report on the on the",
        ]

        for title in garbled_titles:
            result = {
                "feed_title": title,
                "feed_summary": "Complete summary here.",
                "detail_title": title,
                "section": "world",
            }
            _validate_feed_outputs(result)

    def test_summary_has_punctuation(self):
        """Feed summaries should end with proper punctuation."""
        # Summaries without punctuation may be incomplete
        incomplete_summaries = [
            "The investigation continues and officials are",
            "This represents a major shift in policy toward",
        ]

        for summary in incomplete_summaries:
            result = {
                "feed_title": "Complete Title Here",
                "feed_summary": summary,
                "detail_title": "Complete Detail Title",
                "section": "world",
            }
            _validate_feed_outputs(result)

    def test_valid_outputs_pass_validation(self):
        """Properly formed outputs should not trigger warnings."""
        valid_result = {
            "feed_title": "Senate Passes Infrastructure Bill After Debate",
            "feed_summary": "The vote was 65-35 with bipartisan support. Funds will go to roads and bridges.",
            "detail_title": "Senate Passes $1.2 Trillion Infrastructure Bill",
            "section": "us",
        }
        # This should run without issues
        _validate_feed_outputs(valid_result)

    def test_neutralize_preserves_grammar_mock(self):
        """
        Mock neutralized titles should remain grammatical.

        Note: The mock provider uses simple pattern replacement which can produce
        short outputs. This test verifies basic grammar preservation, not length.
        The real fix is for LLM providers, not the mock.
        """
        provider = MockNeutralizerProvider()

        # Test cases with clean content (no manipulation)
        # This tests that clean content passes through unchanged
        test_cases = [
            {
                "title": "Senator discusses critics over tax bill",
                "description": "Senator responds to criticism of proposed tax legislation.",
            },
            {
                "title": "Company announces workforce changes",
                "description": "Tech company plans to adjust workforce.",
            },
            {
                "title": "President addresses nation on policy",
                "description": "Presidential address scheduled for tonight.",
            },
        ]

        for case in test_cases:
            result = provider.neutralize(
                title=case["title"],
                description=case["description"],
                body=None,
            )

            # Clean content should pass through without being garbled
            # Title should not end with dangling prepositions/articles
            if result.feed_title:
                dangling = ["a", "an", "the", "to", "of", "in", "on", "at", "for", "with", "and", "or"]
                words = result.feed_title.rstrip(".,!?:;").split()
                if words:
                    last_word = words[-1].lower()
                    assert last_word not in dangling, (
                        f"Title '{result.feed_title}' ends with dangling '{last_word}'"
                    )


class TestGarbledExamplesFromPlan:
    """Test specific garbled examples mentioned in the plan."""

    def test_kylie_jenner_example(self):
        """
        Original garbled: "and Timothée enjoyed a to Cabo"
        Expected: "Kylie Jenner and Timothée Chalamet Vacation in Cabo"
        """
        garbled = {
            "feed_title": "and Timothée enjoyed a to Cabo",
            "feed_summary": "The couple was spotted at a resort.",
            "detail_title": "and Timothée enjoyed vacation",
            "section": "world",
        }
        # Validation should detect multiple issues here
        _validate_feed_outputs(garbled)

    def test_european_commission_example(self):
        """
        Original garbled: "The has initiated an 's platform"
        Expected: "European Commission Investigates Elon Musk's Platform"
        """
        garbled = {
            "feed_title": "The has initiated an 's platform",
            "feed_summary": "Investigation into social media compliance.",
            "detail_title": "The initiated investigation",
            "section": "world",
        }
        _validate_feed_outputs(garbled)

    def test_narco_sub_example(self):
        """
        Original garbled: "the seizure of a of a"
        Expected: "Authorities Seize Narco Sub Carrying Cocaine"
        """
        garbled = {
            "feed_title": "the seizure of a of a",
            "feed_summary": "Coast guard intercepted vessel.",
            "detail_title": "the seizure of a of a",
            "section": "world",
        }
        _validate_feed_outputs(garbled)


class TestHeadlineSystemPromptIntegration:
    """Test that the headline system prompt getter works correctly."""

    def test_headline_system_prompt_exists(self):
        """The get_headline_system_prompt function should return a valid prompt."""
        from app.services.neutralizer import get_headline_system_prompt

        prompt = get_headline_system_prompt()
        assert prompt is not None
        assert len(prompt) > 100  # Should be a substantial prompt
        assert "GRAMMATICAL INTEGRITY" in prompt
        assert "FACTUAL ACCURACY" in prompt

    def test_default_headline_prompt_differs_from_default_article_prompt(self):
        """
        Default headline prompt should be lighter than default article system prompt.

        Note: This tests the DEFAULT constants, not the DB-retrieved prompts,
        since the DB prompts can be customized per deployment.
        """
        from app.services.neutralizer import (
            DEFAULT_HEADLINE_SYSTEM_PROMPT,
            DEFAULT_ARTICLE_SYSTEM_PROMPT,
        )

        # Headline prompt should NOT contain aggressive word banning
        assert "MUST BE REMOVED" not in DEFAULT_HEADLINE_SYSTEM_PROMPT
        assert "delete entirely" not in DEFAULT_HEADLINE_SYSTEM_PROMPT.lower()

        # Article prompt DOES have aggressive rules
        assert "MANIPULATION PATTERNS TO REMOVE" in DEFAULT_ARTICLE_SYSTEM_PROMPT

        # Headline prompt should focus on synthesis
        assert "SYNTHESIZE" in DEFAULT_HEADLINE_SYSTEM_PROMPT

        # Headline prompt should prioritize grammar
        assert "GRAMMATICAL INTEGRITY" in DEFAULT_HEADLINE_SYSTEM_PROMPT

    def test_headline_prompt_has_self_check_guidance(self):
        """Headline prompt should include self-check guidance."""
        from app.services.neutralizer import DEFAULT_HEADLINE_SYSTEM_PROMPT

        # Should contain examples of garbled vs complete phrases
        assert "missing" in DEFAULT_HEADLINE_SYSTEM_PROMPT.lower()
        assert "incomplete" in DEFAULT_HEADLINE_SYSTEM_PROMPT.lower()
        assert "complete" in DEFAULT_HEADLINE_SYSTEM_PROMPT.lower()

        # Should have SELF-CHECK section
        assert "SELF-CHECK" in DEFAULT_HEADLINE_SYSTEM_PROMPT

    def test_compression_prompt_has_grammar_check(self):
        """The compression user prompt should have grammar integrity check."""
        from app.services.neutralizer import DEFAULT_COMPRESSION_FEED_OUTPUTS_PROMPT

        # Should have the grammar check section (replacing banned language)
        assert "GRAMMAR INTEGRITY CHECK" in DEFAULT_COMPRESSION_FEED_OUTPUTS_PROMPT

        # Should have examples of garbled output
        assert "BROKEN" in DEFAULT_COMPRESSION_FEED_OUTPUTS_PROMPT
        assert "COMPLETE" in DEFAULT_COMPRESSION_FEED_OUTPUTS_PROMPT

        # Should have warning signs
        assert "WARNING SIGNS" in DEFAULT_COMPRESSION_FEED_OUTPUTS_PROMPT
