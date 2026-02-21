"""
Unit tests for domain_mapper service.

Tests the deterministic domain + geography -> feed_category mapping function.
Covers direct mappings, geography-dependent mappings, edge cases, and input normalization.
"""

from app.services.domain_mapper import map_domain_to_feed_category


class TestDomainMapperDirectMappings:
    """Tests for geography-independent direct domain mappings."""

    def test_global_affairs_maps_to_world(self):
        """Global affairs domain maps to world feed category."""
        result = map_domain_to_feed_category("global_affairs")
        assert result == "world"

    def test_economy_macroeconomics_maps_to_business(self):
        """Economy/macroeconomics domain maps to business feed category."""
        result = map_domain_to_feed_category("economy_macroeconomics")
        assert result == "business"

    def test_health_medicine_maps_to_health(self):
        """Health/medicine domain maps to health feed category."""
        result = map_domain_to_feed_category("health_medicine")
        assert result == "health"

    def test_technology_maps_to_technology(self):
        """Technology domain maps to technology feed category."""
        result = map_domain_to_feed_category("technology")
        assert result == "technology"

    def test_sports_competition_maps_to_sports(self):
        """Sports/competition domain maps to sports feed category."""
        result = map_domain_to_feed_category("sports_competition")
        assert result == "sports"


class TestDomainMapperGeoDependentMappings:
    """Tests for geography-dependent domain mappings."""

    def test_governance_politics_us_maps_to_us(self):
        """Governance/politics with US geography maps to US feed category."""
        result = map_domain_to_feed_category("governance_politics", "us")
        assert result == "us"

    def test_governance_politics_international_maps_to_world(self):
        """Governance/politics with international geography maps to world."""
        result = map_domain_to_feed_category("governance_politics", "international")
        assert result == "world"

    def test_crime_public_safety_local_maps_to_local(self):
        """Crime/public safety with local geography maps to local feed category."""
        result = map_domain_to_feed_category("crime_public_safety", "local")
        assert result == "local"

    def test_incidents_disasters_international_maps_to_world(self):
        """Incidents/disasters with international geography maps to world."""
        result = map_domain_to_feed_category("incidents_disasters", "international")
        assert result == "world"

    def test_governance_politics_none_geography_defaults_to_us(self):
        """Governance/politics with None geography defaults to US mapping."""
        result = map_domain_to_feed_category("governance_politics", None)
        assert result == "us"


class TestDomainMapperEdgeCases:
    """Tests for edge cases and input normalization."""

    def test_unknown_domain_falls_back_to_world(self):
        """Unknown domain string falls back to world feed category."""
        result = map_domain_to_feed_category("foobar")
        assert result == "world"

    def test_case_insensitive_mapping(self):
        """Domain mapping is case-insensitive."""
        result = map_domain_to_feed_category("TECHNOLOGY")
        assert result == "technology"

    def test_whitespace_trimmed(self):
        """Leading and trailing whitespace is stripped before mapping."""
        result = map_domain_to_feed_category("  technology  ")
        assert result == "technology"

    def test_empty_domain_falls_back_to_world(self):
        """Empty string domain falls back to world feed category."""
        result = map_domain_to_feed_category("")
        assert result == "world"
