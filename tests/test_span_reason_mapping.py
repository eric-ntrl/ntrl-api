"""
Tests for span reason mapping to ensure all LLM-returned categories
are properly mapped to valid SpanReason enum values.
"""

import logging

from app.models import SpanReason
from app.services.neutralizer.spans import _parse_span_reason


class TestSpanReasonMapping:
    """Tests for _parse_span_reason function."""

    def test_8_canonical_categories_are_mapped(self):
        """The 8 canonical categories should map to their corresponding enum values."""
        canonical_mappings = {
            "clickbait": SpanReason.CLICKBAIT,
            "urgency_inflation": SpanReason.URGENCY_INFLATION,
            "emotional_trigger": SpanReason.EMOTIONAL_TRIGGER,
            "selling": SpanReason.SELLING,
            "agenda_signaling": SpanReason.AGENDA_SIGNALING,
            "rhetorical_framing": SpanReason.RHETORICAL_FRAMING,
            "editorial_voice": SpanReason.EDITORIAL_VOICE,
            "selective_quoting": SpanReason.SELECTIVE_QUOTING,
        }

        for category, expected_reason in canonical_mappings.items():
            result = _parse_span_reason(category)
            assert result == expected_reason, f"'{category}' should map to {expected_reason}"

    def test_prompt_categories_6_to_14_are_mapped(self):
        """Prompt categories 6-14 should map to valid SpanReason values (not default)."""
        prompt_categories = [
            "loaded_verbs",
            "loaded_idioms",
            "loaded_personal_descriptors",
            "hyperbolic_adjectives",
            "sports_event_hype",
            "entertainment_celebrity_hype",
            "agenda_framing",
        ]

        for category in prompt_categories:
            result = _parse_span_reason(category)
            assert result is not None, f"'{category}' should not return None"
            assert isinstance(result, SpanReason), f"'{category}' should return a SpanReason"

    def test_all_prompt_categories_return_valid_enum(self):
        """All categories from the span detection prompt should map to valid SpanReason."""
        all_prompt_categories = [
            # 7 canonical categories
            "urgency_inflation",
            "emotional_trigger",
            "clickbait",
            "selling",
            "agenda_signaling",
            "rhetorical_framing",
            "editorial_voice",
            # Prompt categories 6-14
            "loaded_verbs",
            "loaded_idioms",
            "loaded_personal_descriptors",
            "hyperbolic_adjectives",
            "sports_event_hype",
            "entertainment_celebrity_hype",
            "agenda_framing",
        ]

        for category in all_prompt_categories:
            result = _parse_span_reason(category)
            assert result is not None
            assert isinstance(result, SpanReason)

    def test_case_insensitivity(self):
        """Mapping should be case-insensitive."""
        test_cases = [
            ("CLICKBAIT", SpanReason.CLICKBAIT),
            ("Clickbait", SpanReason.CLICKBAIT),
            ("EMOTIONAL_TRIGGER", SpanReason.EMOTIONAL_TRIGGER),
            ("Emotional_Trigger", SpanReason.EMOTIONAL_TRIGGER),
            ("LOADED_VERBS", SpanReason.RHETORICAL_FRAMING),
        ]

        for input_str, expected in test_cases:
            result = _parse_span_reason(input_str)
            assert result == expected, f"'{input_str}' should map to {expected}"

    def test_unknown_reason_logs_warning(self, caplog):
        """Unknown reasons should log a warning."""
        with caplog.at_level(logging.WARNING):
            result = _parse_span_reason("unknown_category_xyz")

        assert result == SpanReason.RHETORICAL_FRAMING
        assert "Unknown reason" in caplog.text
        assert "unknown_category_xyz" in caplog.text

    def test_unknown_reason_defaults_to_rhetorical_framing(self):
        """Unknown reasons should default to RHETORICAL_FRAMING."""
        unknown_values = [
            "unknown",
            "not_a_category",
            "random_string",
            "",
        ]

        for value in unknown_values:
            if value:  # Skip empty string test (handled separately)
                result = _parse_span_reason(value)
                assert result == SpanReason.RHETORICAL_FRAMING

    def test_defensive_aliases_for_old_names(self):
        """Old/alternative category names should map correctly."""
        aliases = {
            "emotional_manipulation": SpanReason.EMOTIONAL_TRIGGER,
            "emotional": SpanReason.EMOTIONAL_TRIGGER,
            "urgency": SpanReason.URGENCY_INFLATION,
            "hype": SpanReason.SELLING,
            "selling_hype": SpanReason.SELLING,
            "framing": SpanReason.RHETORICAL_FRAMING,
            "selective_quote": SpanReason.SELECTIVE_QUOTING,
            "scare_quotes": SpanReason.SELECTIVE_QUOTING,
            "cherry_picked_quote": SpanReason.SELECTIVE_QUOTING,
        }

        for alias, expected in aliases.items():
            result = _parse_span_reason(alias)
            assert result == expected, f"Alias '{alias}' should map to {expected}"

    def test_specific_mappings_for_prompt_categories(self):
        """Verify specific mappings for prompt categories match expected enums."""
        specific_mappings = {
            # Category 6 & 12 (loaded verbs/idioms) -> rhetorical_framing
            "loaded_verbs": SpanReason.RHETORICAL_FRAMING,
            "loaded_idioms": SpanReason.RHETORICAL_FRAMING,
            # Category 10 & 11 (descriptors/adjectives) -> emotional_trigger
            "loaded_personal_descriptors": SpanReason.EMOTIONAL_TRIGGER,
            "hyperbolic_adjectives": SpanReason.EMOTIONAL_TRIGGER,
            # Category 9 & 13 (sports/celebrity hype) -> selling
            "sports_event_hype": SpanReason.SELLING,
            "entertainment_celebrity_hype": SpanReason.SELLING,
            # Category 8 (agenda framing) -> agenda_signaling
            "agenda_framing": SpanReason.AGENDA_SIGNALING,
        }

        for category, expected in specific_mappings.items():
            result = _parse_span_reason(category)
            assert result == expected, f"'{category}' should map to {expected}"


class TestSpanCategoryDiversity:
    """Tests to ensure span detection produces diverse categories."""

    def test_mapping_produces_diverse_outputs(self):
        """The mapping should be able to produce all 8 SpanReason values."""
        # Sample inputs that should produce each SpanReason
        inputs_by_category = {
            SpanReason.CLICKBAIT: "clickbait",
            SpanReason.URGENCY_INFLATION: "urgency_inflation",
            SpanReason.EMOTIONAL_TRIGGER: "emotional_trigger",
            SpanReason.SELLING: "selling",
            SpanReason.AGENDA_SIGNALING: "agenda_signaling",
            SpanReason.RHETORICAL_FRAMING: "rhetorical_framing",
            SpanReason.EDITORIAL_VOICE: "editorial_voice",
            SpanReason.SELECTIVE_QUOTING: "selective_quoting",
        }

        produced_reasons = set()
        for expected_reason, input_str in inputs_by_category.items():
            result = _parse_span_reason(input_str)
            produced_reasons.add(result)
            assert result == expected_reason

        # Verify all 8 reasons can be produced
        assert len(produced_reasons) == 8
        assert produced_reasons == set(SpanReason)
