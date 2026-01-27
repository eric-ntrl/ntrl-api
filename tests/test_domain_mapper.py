# tests/test_domain_mapper.py
"""
Tests for domain_mapper: deterministic domain + geography -> feed_category mapping.

Covers:
- All 15 direct (geography-independent) domain mappings
- All 5 geography-dependent domain mappings with each geography value
- Unknown domains and geographies
- Input normalization (case, whitespace)
"""

import pytest

from app.services.domain_mapper import (
    map_domain_to_feed_category,
    DIRECT_MAPPINGS,
    GEO_DEPENDENT_MAPPINGS,
)
from app.models import Domain, FeedCategory


# ---------------------------------------------------------------------------
# Test: Direct (geography-independent) mappings
# ---------------------------------------------------------------------------

class TestDirectMappings:
    """All 15 geography-independent domain -> feed_category mappings."""

    def test_global_affairs_maps_to_world(self):
        assert map_domain_to_feed_category(Domain.GLOBAL_AFFAIRS) == "world"

    def test_economy_macroeconomics_maps_to_business(self):
        assert map_domain_to_feed_category(Domain.ECONOMY_MACROECONOMICS) == "business"

    def test_finance_markets_maps_to_business(self):
        assert map_domain_to_feed_category(Domain.FINANCE_MARKETS) == "business"

    def test_business_industry_maps_to_business(self):
        assert map_domain_to_feed_category(Domain.BUSINESS_INDUSTRY) == "business"

    def test_labor_demographics_maps_to_business(self):
        assert map_domain_to_feed_category(Domain.LABOR_DEMOGRAPHICS) == "business"

    def test_infrastructure_systems_maps_to_business(self):
        assert map_domain_to_feed_category(Domain.INFRASTRUCTURE_SYSTEMS) == "business"

    def test_energy_maps_to_environment(self):
        assert map_domain_to_feed_category(Domain.ENERGY) == "environment"

    def test_environment_climate_maps_to_environment(self):
        assert map_domain_to_feed_category(Domain.ENVIRONMENT_CLIMATE) == "environment"

    def test_science_research_maps_to_science(self):
        assert map_domain_to_feed_category(Domain.SCIENCE_RESEARCH) == "science"

    def test_health_medicine_maps_to_health(self):
        assert map_domain_to_feed_category(Domain.HEALTH_MEDICINE) == "health"

    def test_technology_maps_to_technology(self):
        assert map_domain_to_feed_category(Domain.TECHNOLOGY) == "technology"

    def test_media_information_maps_to_technology(self):
        assert map_domain_to_feed_category(Domain.MEDIA_INFORMATION) == "technology"

    def test_sports_competition_maps_to_sports(self):
        assert map_domain_to_feed_category(Domain.SPORTS_COMPETITION) == "sports"

    def test_society_culture_maps_to_culture(self):
        assert map_domain_to_feed_category(Domain.SOCIETY_CULTURE) == "culture"

    def test_lifestyle_personal_maps_to_culture(self):
        assert map_domain_to_feed_category(Domain.LIFESTYLE_PERSONAL) == "culture"

    def test_direct_mappings_ignore_geography(self):
        """Direct mappings should return the same result regardless of geography."""
        for domain, expected_cat in DIRECT_MAPPINGS.items():
            for geo in ("us", "local", "international", "mixed"):
                result = map_domain_to_feed_category(domain, geography=geo)
                assert result == expected_cat.value, (
                    f"{domain} with geography={geo} should map to {expected_cat.value}, got {result}"
                )

    def test_all_15_direct_mappings_covered(self):
        """Verify there are exactly 15 direct mappings."""
        assert len(DIRECT_MAPPINGS) == 15


# ---------------------------------------------------------------------------
# Test: Geography-dependent mappings
# ---------------------------------------------------------------------------

class TestGeoDependentMappings:
    """All 5 geography-dependent domains with each geography value."""

    # -- governance_politics --

    def test_governance_politics_us(self):
        assert map_domain_to_feed_category(Domain.GOVERNANCE_POLITICS, "us") == "us"

    def test_governance_politics_local(self):
        assert map_domain_to_feed_category(Domain.GOVERNANCE_POLITICS, "local") == "us"

    def test_governance_politics_international(self):
        assert map_domain_to_feed_category(Domain.GOVERNANCE_POLITICS, "international") == "world"

    def test_governance_politics_mixed(self):
        assert map_domain_to_feed_category(Domain.GOVERNANCE_POLITICS, "mixed") == "us"

    # -- law_justice --

    def test_law_justice_us(self):
        assert map_domain_to_feed_category(Domain.LAW_JUSTICE, "us") == "us"

    def test_law_justice_local(self):
        assert map_domain_to_feed_category(Domain.LAW_JUSTICE, "local") == "us"

    def test_law_justice_international(self):
        assert map_domain_to_feed_category(Domain.LAW_JUSTICE, "international") == "world"

    def test_law_justice_mixed(self):
        assert map_domain_to_feed_category(Domain.LAW_JUSTICE, "mixed") == "us"

    # -- security_defense --

    def test_security_defense_us(self):
        assert map_domain_to_feed_category(Domain.SECURITY_DEFENSE, "us") == "us"

    def test_security_defense_local(self):
        assert map_domain_to_feed_category(Domain.SECURITY_DEFENSE, "local") == "us"

    def test_security_defense_international(self):
        assert map_domain_to_feed_category(Domain.SECURITY_DEFENSE, "international") == "world"

    def test_security_defense_mixed(self):
        assert map_domain_to_feed_category(Domain.SECURITY_DEFENSE, "mixed") == "us"

    # -- crime_public_safety --

    def test_crime_public_safety_us(self):
        assert map_domain_to_feed_category(Domain.CRIME_PUBLIC_SAFETY, "us") == "us"

    def test_crime_public_safety_local(self):
        """Crime with local geography maps to LOCAL (not US)."""
        assert map_domain_to_feed_category(Domain.CRIME_PUBLIC_SAFETY, "local") == "local"

    def test_crime_public_safety_international(self):
        assert map_domain_to_feed_category(Domain.CRIME_PUBLIC_SAFETY, "international") == "world"

    def test_crime_public_safety_mixed(self):
        assert map_domain_to_feed_category(Domain.CRIME_PUBLIC_SAFETY, "mixed") == "us"

    # -- incidents_disasters --

    def test_incidents_disasters_us(self):
        assert map_domain_to_feed_category(Domain.INCIDENTS_DISASTERS, "us") == "us"

    def test_incidents_disasters_local(self):
        """Incidents with local geography maps to LOCAL (not US)."""
        assert map_domain_to_feed_category(Domain.INCIDENTS_DISASTERS, "local") == "local"

    def test_incidents_disasters_international(self):
        assert map_domain_to_feed_category(Domain.INCIDENTS_DISASTERS, "international") == "world"

    def test_incidents_disasters_mixed(self):
        assert map_domain_to_feed_category(Domain.INCIDENTS_DISASTERS, "mixed") == "us"

    def test_all_5_geo_dependent_mappings_covered(self):
        """Verify there are exactly 5 geography-dependent mappings."""
        assert len(GEO_DEPENDENT_MAPPINGS) == 5

    def test_all_20_domains_accounted_for(self):
        """Direct + geo-dependent should cover all 20 domains."""
        all_mapped = set(DIRECT_MAPPINGS.keys()) | set(GEO_DEPENDENT_MAPPINGS.keys())
        all_domains = {d.value for d in Domain}
        assert all_mapped == all_domains, (
            f"Missing domains: {all_domains - all_mapped}, "
            f"Extra domains: {all_mapped - all_domains}"
        )


# ---------------------------------------------------------------------------
# Test: Local vs US distinction for crime/incidents
# ---------------------------------------------------------------------------

class TestLocalDistinction:
    """
    Verify that crime_public_safety and incidents_disasters are the ONLY
    two domains that map local geography to the LOCAL feed category.
    The other three geo-dependent domains map local to US.
    """

    def test_only_crime_and_incidents_have_local_category(self):
        """Only crime and incidents map 'local' geography to LOCAL feed category."""
        domains_with_local_output = []
        for domain, geo_map in GEO_DEPENDENT_MAPPINGS.items():
            if geo_map.get("local") == FeedCategory.LOCAL:
                domains_with_local_output.append(domain)

        assert set(domains_with_local_output) == {
            Domain.CRIME_PUBLIC_SAFETY,
            Domain.INCIDENTS_DISASTERS,
        }

    def test_governance_local_is_us_not_local(self):
        """Governance local -> US, not LOCAL."""
        assert map_domain_to_feed_category(Domain.GOVERNANCE_POLITICS, "local") == "us"

    def test_law_local_is_us_not_local(self):
        """Law local -> US, not LOCAL."""
        assert map_domain_to_feed_category(Domain.LAW_JUSTICE, "local") == "us"

    def test_security_local_is_us_not_local(self):
        """Security local -> US, not LOCAL."""
        assert map_domain_to_feed_category(Domain.SECURITY_DEFENSE, "local") == "us"


# ---------------------------------------------------------------------------
# Test: Unknown domains and geographies
# ---------------------------------------------------------------------------

class TestUnknownInputs:
    """Tests for unknown or edge-case inputs."""

    def test_unknown_domain_falls_back_to_world(self):
        assert map_domain_to_feed_category("completely_unknown_domain") == "world"

    def test_empty_domain_falls_back_to_world(self):
        assert map_domain_to_feed_category("") == "world"

    def test_none_domain_falls_back_to_world(self):
        """None domain should not crash; falls back to world."""
        assert map_domain_to_feed_category(None) == "world"

    def test_unknown_geography_for_geo_dependent_domain(self):
        """
        Unknown geography for a geo-dependent domain should fall back
        to the 'us' entry in that domain's geo_map.
        """
        result = map_domain_to_feed_category(Domain.GOVERNANCE_POLITICS, "martian")
        assert result == "us"

    def test_none_geography_defaults_to_us(self):
        """None geography should default to 'us'."""
        result = map_domain_to_feed_category(Domain.GOVERNANCE_POLITICS, None)
        assert result == "us"

    def test_empty_geography_defaults_to_us(self):
        """Empty geography string should default to 'us'."""
        result = map_domain_to_feed_category(Domain.GOVERNANCE_POLITICS, "")
        assert result == "us"


# ---------------------------------------------------------------------------
# Test: Input normalization
# ---------------------------------------------------------------------------

class TestInputNormalization:
    """Tests that inputs are normalized (lowercased, stripped)."""

    def test_domain_case_insensitive(self):
        assert map_domain_to_feed_category("GLOBAL_AFFAIRS") == "world"
        assert map_domain_to_feed_category("Global_Affairs") == "world"

    def test_domain_whitespace_stripped(self):
        assert map_domain_to_feed_category("  global_affairs  ") == "world"

    def test_geography_case_insensitive(self):
        assert map_domain_to_feed_category(Domain.GOVERNANCE_POLITICS, "US") == "us"
        assert map_domain_to_feed_category(Domain.GOVERNANCE_POLITICS, "International") == "world"

    def test_geography_whitespace_stripped(self):
        assert map_domain_to_feed_category(Domain.GOVERNANCE_POLITICS, "  us  ") == "us"

    def test_return_values_are_strings(self):
        """All return values should be plain strings, not enum instances."""
        for domain in Domain:
            result = map_domain_to_feed_category(domain.value)
            assert isinstance(result, str)
            # Should be a valid FeedCategory value
            assert result in {cat.value for cat in FeedCategory}
