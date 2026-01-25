# tests/test_taxonomy.py
"""
Unit tests for the NTRL Canonical Manipulation Taxonomy.
"""

import pytest
from app.taxonomy import (
    MANIPULATION_TAXONOMY,
    ManipulationCategory,
    ManipulationType,
    SpanAction,
    ArticleSegment,
    SEGMENT_MULTIPLIERS,
    CATEGORY_NAMES,
    get_type,
    get_types_by_category,
    get_types_by_severity,
    get_types_with_patterns,
    get_all_type_ids,
    validate_type_id,
    TAXONOMY_VERSION,
    TOTAL_TYPES,
    COUNTS_BY_CATEGORY,
)


class TestTaxonomyStructure:
    """Tests for taxonomy structure and integrity."""

    def test_taxonomy_not_empty(self):
        """Taxonomy should contain manipulation types."""
        assert len(MANIPULATION_TAXONOMY) > 0
        assert TOTAL_TYPES > 80  # Should have 80+ types per spec

    def test_all_categories_present(self):
        """All 6 categories (A-F) should have types."""
        categories_found = set()
        for type_id in MANIPULATION_TAXONOMY:
            categories_found.add(type_id[0])

        expected = {"A", "B", "C", "D", "E", "F"}
        assert categories_found == expected

    def test_type_id_format(self):
        """All type IDs should follow X.Y.Z format."""
        for type_id in MANIPULATION_TAXONOMY:
            parts = type_id.split(".")
            assert len(parts) == 3, f"Invalid type_id format: {type_id}"
            assert parts[0] in "ABCDEF", f"Invalid category: {type_id}"
            assert parts[1].isdigit(), f"Invalid L2: {type_id}"
            assert parts[2].isdigit() or parts[2] == "10", f"Invalid L3: {type_id}"

    def test_type_has_required_fields(self):
        """Each type should have all required fields populated."""
        for type_id, manip_type in MANIPULATION_TAXONOMY.items():
            assert manip_type.type_id == type_id
            assert manip_type.category in ManipulationCategory
            assert manip_type.l2_name, f"Missing l2_name: {type_id}"
            assert manip_type.l3_name, f"Missing l3_name: {type_id}"
            assert manip_type.label, f"Missing label: {type_id}"
            assert manip_type.description, f"Missing description: {type_id}"
            assert 1 <= manip_type.default_severity <= 5, f"Invalid severity: {type_id}"
            assert manip_type.default_action in SpanAction

    def test_category_names_complete(self):
        """All categories should have human-readable names."""
        for cat in ManipulationCategory:
            assert cat in CATEGORY_NAMES
            assert len(CATEGORY_NAMES[cat]) > 0


class TestTaxonomyHelpers:
    """Tests for taxonomy helper functions."""

    def test_get_type_exists(self):
        """get_type should return type for valid ID."""
        t = get_type("A.1.1")
        assert t is not None
        assert t.type_id == "A.1.1"
        assert t.label == "Curiosity gap"

    def test_get_type_not_exists(self):
        """get_type should return None for invalid ID."""
        t = get_type("Z.9.9")
        assert t is None

    def test_get_types_by_category(self):
        """get_types_by_category should return correct types."""
        attention_types = get_types_by_category(ManipulationCategory.ATTENTION_ENGAGEMENT)
        assert len(attention_types) > 0
        for t in attention_types:
            assert t.category == ManipulationCategory.ATTENTION_ENGAGEMENT
            assert t.type_id.startswith("A.")

    def test_get_types_by_severity(self):
        """get_types_by_severity should filter correctly."""
        high_severity = get_types_by_severity(4)
        assert len(high_severity) > 0
        for t in high_severity:
            assert t.default_severity >= 4

    def test_get_types_with_patterns(self):
        """get_types_with_patterns should return types with lexical patterns."""
        types_with_patterns = get_types_with_patterns()
        assert len(types_with_patterns) > 30  # Should have many patterns
        for t in types_with_patterns:
            assert len(t.lexical_patterns) > 0

    def test_get_all_type_ids(self):
        """get_all_type_ids should return all IDs."""
        ids = get_all_type_ids()
        assert len(ids) == TOTAL_TYPES
        assert "A.1.1" in ids
        assert "F.4.2" in ids

    def test_validate_type_id(self):
        """validate_type_id should check existence."""
        assert validate_type_id("A.1.1") is True
        assert validate_type_id("Z.9.9") is False


class TestSpecificTypes:
    """Tests for specific manipulation types from the spec."""

    def test_urgency_inflation(self):
        """A.2.1 Urgency inflation should have BREAKING pattern."""
        t = get_type("A.2.1")
        assert t is not None
        assert "urgency" in t.label.lower()
        assert any("BREAKING" in p for p in t.lexical_patterns)
        assert t.default_action == SpanAction.REMOVE

    def test_rage_verbs(self):
        """B.2.2 Rage verbs should have slams/blasts patterns."""
        t = get_type("B.2.2")
        assert t is not None
        assert "rage" in t.label.lower()
        assert any("slams" in p for p in t.lexical_patterns)
        assert any("blasts" in p for p in t.lexical_patterns)
        assert t.default_action == SpanAction.REPLACE

    def test_fear_appeal(self):
        """B.1.1 Fear appeal should be high severity."""
        t = get_type("B.1.1")
        assert t is not None
        assert t.default_severity >= 4
        assert t.category == ManipulationCategory.EMOTIONAL_AFFECTIVE

    def test_dehumanization(self):
        """D.1.4 Dehumanization should be highest severity."""
        t = get_type("D.1.4")
        assert t is not None
        assert t.default_severity == 5
        assert any("vermin" in p for p in t.lexical_patterns)

    def test_call_to_action(self):
        """F.3.2 Call-to-action should be removed."""
        t = get_type("F.3.2")
        assert t is not None
        assert t.default_action == SpanAction.REMOVE
        assert any("petition" in p for p in t.lexical_patterns)


class TestSegmentMultipliers:
    """Tests for segment severity multipliers."""

    def test_title_has_highest_multiplier(self):
        """Title should have highest severity multiplier."""
        assert SEGMENT_MULTIPLIERS[ArticleSegment.TITLE] == 1.5
        for segment, mult in SEGMENT_MULTIPLIERS.items():
            if segment != ArticleSegment.TITLE:
                assert mult <= SEGMENT_MULTIPLIERS[ArticleSegment.TITLE]

    def test_quote_has_lowest_multiplier(self):
        """Pullquote should have lowest multiplier (content preserved)."""
        assert SEGMENT_MULTIPLIERS[ArticleSegment.PULLQUOTE] == 0.6
        for segment, mult in SEGMENT_MULTIPLIERS.items():
            if segment != ArticleSegment.PULLQUOTE:
                assert mult >= SEGMENT_MULTIPLIERS[ArticleSegment.PULLQUOTE]


class TestTaxonomyStatistics:
    """Tests for taxonomy statistics."""

    def test_counts_by_category_sum(self):
        """Category counts should sum to total types."""
        total = sum(COUNTS_BY_CATEGORY.values())
        assert total == TOTAL_TYPES

    def test_version_format(self):
        """Taxonomy version should be valid."""
        assert TAXONOMY_VERSION == "1.0"
