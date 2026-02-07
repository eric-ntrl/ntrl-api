# tests/test_enhanced_keyword_classifier.py
"""
Tests for enhanced_keyword_classifier: 20-domain keyword classification + geography detection.

Covers:
- Representative keywords detected for each of the 20 domains
- Geography detection (US, local, international, source slug hints)
- Edge cases: empty text, no matching keywords, None inputs
"""

from app.models import Domain
from app.services.enhanced_keyword_classifier import (
    DOMAIN_KEYWORDS,
    INTERNATIONAL_KEYWORDS,
    LOCAL_KEYWORDS,
    SOURCE_GEO_HINTS,
    US_KEYWORDS,
    _score_text,
    classify_by_keywords,
    detect_geography,
)

# ---------------------------------------------------------------------------
# Test: Keyword scoring helper
# ---------------------------------------------------------------------------


class TestScoreText:
    """Tests for the _score_text helper."""

    def test_single_keyword_match(self):
        assert _score_text("The united nations met today.", {"united nations"}) >= 1

    def test_no_match_returns_zero(self):
        assert _score_text("A simple sentence.", {"quantum", "blockchain"}) == 0

    def test_title_weight_multiplier(self):
        score_1x = _score_text("The nato summit begins.", {"nato"}, title_weight=1)
        score_3x = _score_text("The nato summit begins.", {"nato"}, title_weight=3)
        assert score_3x == 3 * score_1x

    def test_multiple_keywords_accumulate(self):
        text = "The police arrested a suspect after the robbery investigation."
        keywords = {"police", "arrest", "suspect", "robbery", "investigation"}
        # Each keyword matched adds to score
        score = _score_text(text, keywords)
        assert score >= 3  # At least police, suspect, robbery should match

    def test_case_insensitive_matching(self):
        assert _score_text("NATO Summit in Brussels", {"nato"}) >= 1

    def test_word_boundary_matching(self):
        """Keywords should match on word boundaries, not substrings."""
        # "art" should not match inside "party"
        score = _score_text("The party was fun.", {"art"})
        assert score == 0

    def test_empty_text_returns_zero(self):
        assert _score_text("", {"some", "keywords"}) == 0

    def test_empty_keywords_returns_zero(self):
        assert _score_text("Some text here.", set()) == 0


# ---------------------------------------------------------------------------
# Test: Domain keyword detection for each of the 20 domains
# ---------------------------------------------------------------------------


class TestDomainClassification:
    """Verify that representative keywords trigger the correct domain."""

    def _classify_title(self, title: str) -> str:
        """Classify an article by title alone and return the domain."""
        result = classify_by_keywords(title=title)
        return result["domain"]

    def test_global_affairs(self):
        domain = self._classify_title("United Nations summit on diplomatic sanctions")
        assert domain == Domain.GLOBAL_AFFAIRS

    def test_governance_politics(self):
        domain = self._classify_title("Senate passes bipartisan legislation on election reform")
        assert domain == Domain.GOVERNANCE_POLITICS

    def test_law_justice(self):
        domain = self._classify_title("Supreme Court ruling on federal lawsuit verdict")
        assert domain == Domain.LAW_JUSTICE

    def test_security_defense(self):
        domain = self._classify_title("Pentagon announces military deployment and national security update")
        assert domain == Domain.SECURITY_DEFENSE

    def test_crime_public_safety(self):
        domain = self._classify_title("Police arrest suspect in robbery and shooting investigation")
        assert domain == Domain.CRIME_PUBLIC_SAFETY

    def test_economy_macroeconomics(self):
        domain = self._classify_title("Federal Reserve raises interest rate amid inflation concerns")
        assert domain == Domain.ECONOMY_MACROECONOMICS

    def test_finance_markets(self):
        domain = self._classify_title("Wall Street stock market rally as Dow and Nasdaq hit records")
        assert domain == Domain.FINANCE_MARKETS

    def test_business_industry(self):
        domain = self._classify_title("CEO announces merger and acquisition of corporate subsidiary")
        assert domain == Domain.BUSINESS_INDUSTRY

    def test_labor_demographics(self):
        domain = self._classify_title("Workers union calls strike over wages and collective bargaining")
        assert domain == Domain.LABOR_DEMOGRAPHICS

    def test_infrastructure_systems(self):
        domain = self._classify_title("Highway bridge infrastructure construction and transit planning")
        assert domain == Domain.INFRASTRUCTURE_SYSTEMS

    def test_energy(self):
        domain = self._classify_title("Solar renewable energy transition and electric vehicle battery storage")
        assert domain == Domain.ENERGY

    def test_environment_climate(self):
        domain = self._classify_title("Climate change deforestation threatens biodiversity and ecosystem conservation")
        assert domain == Domain.ENVIRONMENT_CLIMATE

    def test_science_research(self):
        domain = self._classify_title("NASA space telescope discovers new asteroid near Mars")
        assert domain == Domain.SCIENCE_RESEARCH

    def test_health_medicine(self):
        domain = self._classify_title("FDA approves new vaccine for pandemic disease treatment")
        assert domain == Domain.HEALTH_MEDICINE

    def test_technology(self):
        domain = self._classify_title("AI artificial intelligence machine learning algorithm breakthrough")
        assert domain == Domain.TECHNOLOGY

    def test_media_information(self):
        domain = self._classify_title("Social media misinformation and journalism fact check censorship")
        assert domain == Domain.MEDIA_INFORMATION

    def test_sports_competition(self):
        domain = self._classify_title("NFL football championship playoff Super Bowl game results")
        assert domain == Domain.SPORTS_COMPETITION

    def test_society_culture(self):
        domain = self._classify_title("Civil rights protest activism community culture education")
        assert domain == Domain.SOCIETY_CULTURE

    def test_lifestyle_personal(self):
        domain = self._classify_title("Celebrity entertainment fashion food restaurant travel tourism")
        assert domain == Domain.LIFESTYLE_PERSONAL

    def test_incidents_disasters(self):
        domain = self._classify_title("Earthquake hurricane disaster emergency evacuation rescue relief")
        assert domain == Domain.INCIDENTS_DISASTERS

    def test_all_20_domains_have_keywords(self):
        """Verify every Domain enum value has an entry in DOMAIN_KEYWORDS."""
        for domain in Domain:
            assert domain.value in DOMAIN_KEYWORDS or domain in DOMAIN_KEYWORDS, (
                f"Domain {domain} missing from DOMAIN_KEYWORDS"
            )

    def test_each_domain_has_at_least_30_keywords(self):
        """Each domain should have at least 30 keywords per the module docstring."""
        for domain_val, keywords in DOMAIN_KEYWORDS.items():
            assert len(keywords) >= 30, f"Domain {domain_val} has only {len(keywords)} keywords (expected >=30)"


# ---------------------------------------------------------------------------
# Test: Description and body contribute to classification
# ---------------------------------------------------------------------------


class TestDescriptionAndBody:
    """Verify that description and body_excerpt influence classification."""

    def test_description_contributes(self):
        """A weak title + strong description should classify correctly."""
        result = classify_by_keywords(
            title="Breaking update today",
            description="The Supreme Court issued a landmark ruling on the federal lawsuit.",
        )
        assert result["domain"] == Domain.LAW_JUSTICE

    def test_body_excerpt_contributes(self):
        """A weak title + strong body should classify correctly."""
        result = classify_by_keywords(
            title="Latest news report",
            body_excerpt="NASA scientists announced a breakthrough discovery using the space telescope. "
            "The research team published results in a peer-reviewed science journal.",
        )
        assert result["domain"] == Domain.SCIENCE_RESEARCH

    def test_title_weighted_more_than_body(self):
        """Title keywords count 3x, so title should dominate body."""
        # Title has sports keywords (3x weight), body has science keywords (1x)
        result = classify_by_keywords(
            title="NFL football championship playoff game",
            body_excerpt="The study found interesting results in biology research.",
        )
        assert result["domain"] == Domain.SPORTS_COMPETITION

    def test_body_truncated_to_2000_chars(self):
        """Body text beyond 2000 characters should be ignored."""
        # Keywords placed only after the 2000-char mark
        padding = "a " * 1100  # ~2200 chars of filler
        result = classify_by_keywords(
            title="Generic headline",
            body_excerpt=padding + "earthquake hurricane disaster emergency",
        )
        # The disaster keywords are beyond the 2000-char cutoff, so they shouldn't score
        # Result should be global_affairs (default) since no keywords match
        assert result["domain"] == Domain.GLOBAL_AFFAIRS


# ---------------------------------------------------------------------------
# Test: Geography detection
# ---------------------------------------------------------------------------


class TestGeographyDetection:
    """Tests for detect_geography."""

    def test_us_keywords_detected(self):
        geo = detect_geography("Congress passes new bill in Washington")
        assert geo == "us"

    def test_local_keywords_detected(self):
        geo = detect_geography("Mayor and city council discuss municipal zoning")
        assert geo == "local"

    def test_international_keywords_detected(self):
        geo = detect_geography("Russia and Ukraine conflict intensifies in Europe")
        assert geo == "international"

    def test_source_slug_hint_overrides(self):
        """Source slug hints should take priority over text analysis."""
        # Title says US but source says international
        geo = detect_geography(
            "Congress votes on new legislation",
            source_slug="ap-world",
        )
        assert geo == "international"

    def test_source_slug_ap_us(self):
        geo = detect_geography("Some headline", source_slug="ap-us")
        assert geo == "us"

    def test_source_slug_ap_local(self):
        geo = detect_geography("Some headline", source_slug="ap-local")
        assert geo == "local"

    def test_source_slug_bbc_world(self):
        geo = detect_geography("Some headline", source_slug="bbc-world")
        assert geo == "international"

    def test_source_slug_reuters_world(self):
        geo = detect_geography("Some headline", source_slug="reuters-world")
        assert geo == "international"

    def test_unknown_source_slug_ignored(self):
        """Unknown source slugs should not affect geography detection."""
        geo = detect_geography(
            "China and Japan hold diplomatic talks",
            source_slug="unknown-source",
        )
        assert geo == "international"

    def test_default_is_us(self):
        """When no keywords match, default should be US."""
        geo = detect_geography("A generic headline with no geographic signals")
        assert geo == "us"

    def test_description_contributes_to_geography(self):
        geo = detect_geography(
            "Latest developments today",
            description="The China and Russia alliance strengthens as Europe watches.",
        )
        assert geo == "international"

    def test_body_contributes_to_geography(self):
        geo = detect_geography(
            "Breaking news report",
            body_excerpt="The mayor and city council members met to discuss neighborhood zoning for the community.",
        )
        assert geo == "local"

    def test_us_state_names_detected(self):
        geo = detect_geography("California wildfire forces evacuations")
        assert geo == "us"

    def test_us_city_names_detected(self):
        geo = detect_geography("Chicago traffic disrupted by severe weather")
        assert geo in ("us", "local")  # Could be either; city is both US and local

    def test_international_countries_detected(self):
        geo = detect_geography("India and Japan sign new trade agreement")
        assert geo == "international"

    def test_title_weighted_more_in_geography(self):
        """Title keywords get 3x weight in geography detection."""
        # Title: international, body: US
        geo = detect_geography(
            "China and Russia tensions escalate",
            body_excerpt="The senate held hearings on the matter.",
        )
        assert geo == "international"


# ---------------------------------------------------------------------------
# Test: classify_by_keywords full output
# ---------------------------------------------------------------------------


class TestClassifyByKeywordsOutput:
    """Tests for the full classify_by_keywords return structure."""

    def test_returns_domain_key(self):
        result = classify_by_keywords("Congress passes bill")
        assert "domain" in result
        assert isinstance(result["domain"], str)

    def test_returns_geography_key(self):
        result = classify_by_keywords("Congress passes bill")
        assert "geography" in result
        assert result["geography"] in ("us", "local", "international", "mixed")

    def test_returns_tags_dict(self):
        result = classify_by_keywords("Congress passes bill")
        assert "tags" in result
        tags = result["tags"]
        assert "geography" in tags
        assert "geography_detail" in tags
        assert "actors" in tags
        assert "action_type" in tags
        assert "topic_keywords" in tags

    def test_tags_geography_matches_top_level(self):
        result = classify_by_keywords("Russia invades Ukraine in Europe")
        assert result["geography"] == result["tags"]["geography"]

    def test_actors_is_list(self):
        result = classify_by_keywords("Some headline")
        assert isinstance(result["tags"]["actors"], list)

    def test_topic_keywords_is_list(self):
        result = classify_by_keywords("Some headline")
        assert isinstance(result["tags"]["topic_keywords"], list)

    def test_action_type_is_string(self):
        result = classify_by_keywords("Some headline")
        assert isinstance(result["tags"]["action_type"], str)


# ---------------------------------------------------------------------------
# Test: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases: empty text, None inputs, no matching keywords."""

    def test_empty_title(self):
        """Empty title should not crash; defaults to global_affairs."""
        result = classify_by_keywords(title="")
        assert result["domain"] == Domain.GLOBAL_AFFAIRS

    def test_none_title(self):
        """None title should not crash."""
        result = classify_by_keywords(title=None)
        assert "domain" in result

    def test_none_description(self):
        """None description should not crash."""
        result = classify_by_keywords(title="Some title", description=None)
        assert "domain" in result

    def test_none_body_excerpt(self):
        """None body_excerpt should not crash."""
        result = classify_by_keywords(title="Some title", body_excerpt=None)
        assert "domain" in result

    def test_all_none_inputs(self):
        """All None inputs should not crash; returns default domain."""
        result = classify_by_keywords(title=None, description=None, body_excerpt=None, source_slug=None)
        assert result["domain"] == Domain.GLOBAL_AFFAIRS
        assert result["geography"] == "us"  # default

    def test_no_matching_keywords_defaults_to_global_affairs(self):
        """Text with no matching keywords should default to global_affairs."""
        result = classify_by_keywords(
            title="Xyzzy plugh plover",
            description="Completely unrelated gibberish words.",
        )
        assert result["domain"] == Domain.GLOBAL_AFFAIRS

    def test_whitespace_only_title(self):
        """Whitespace-only title should not crash."""
        result = classify_by_keywords(title="   ")
        assert result["domain"] == Domain.GLOBAL_AFFAIRS

    def test_very_long_body_handled(self):
        """Very long body should be truncated safely to 2000 chars."""
        long_body = "word " * 10000  # ~50000 chars
        result = classify_by_keywords(title="Some title", body_excerpt=long_body)
        assert "domain" in result  # Should not crash

    def test_source_slug_does_not_affect_domain(self):
        """Source slug affects geography, not domain classification."""
        result_no_slug = classify_by_keywords(title="NASA discovers new asteroid in space")
        result_with_slug = classify_by_keywords(
            title="NASA discovers new asteroid in space",
            source_slug="ap-world",
        )
        # Domain should be the same regardless of source slug
        assert result_no_slug["domain"] == result_with_slug["domain"]
        # But geography may differ
        assert result_with_slug["geography"] == "international"


# ---------------------------------------------------------------------------
# Test: Geography detection edge cases
# ---------------------------------------------------------------------------


class TestGeographyEdgeCases:
    """Edge cases for geography detection."""

    def test_empty_title_geography(self):
        geo = detect_geography("")
        assert geo == "us"  # default

    def test_none_title_geography(self):
        geo = detect_geography(None)
        assert geo == "us"  # default

    def test_none_description_geography(self):
        geo = detect_geography("Some title", description=None)
        assert isinstance(geo, str)

    def test_none_body_geography(self):
        geo = detect_geography("Some title", body_excerpt=None)
        assert isinstance(geo, str)

    def test_none_source_slug_geography(self):
        geo = detect_geography("Some title", source_slug=None)
        assert isinstance(geo, str)

    def test_geography_returns_string(self):
        """Geography should always return a string."""
        for title in [
            "Congress votes on bill",
            "Mayor discusses zoning",
            "China and Russia talks",
            "",
            "Generic news headline",
        ]:
            geo = detect_geography(title)
            assert isinstance(geo, str)
            assert geo in ("us", "local", "international", "mixed")

    def test_source_geo_hints_coverage(self):
        """Verify all source slug hints are tested."""
        expected_slugs = {"ap-world", "reuters-world", "bbc-world", "ap-us", "ap-local"}
        assert set(SOURCE_GEO_HINTS.keys()) == expected_slugs


# ---------------------------------------------------------------------------
# Test: Keyword set integrity
# ---------------------------------------------------------------------------


class TestKeywordSetIntegrity:
    """Verify the keyword data structures are well-formed."""

    def test_domain_keywords_keys_match_domain_enum(self):
        """All DOMAIN_KEYWORDS keys should be valid Domain enum values."""
        domain_values = {d.value for d in Domain}
        for key in DOMAIN_KEYWORDS:
            # Keys might be Domain enum members or string values
            key_str = key.value if hasattr(key, "value") else key
            assert key_str in domain_values, f"Unknown domain key: {key}"

    def test_all_keywords_are_lowercase(self):
        """All keywords should be lowercase for consistent matching."""
        for domain_val, keywords in DOMAIN_KEYWORDS.items():
            for kw in keywords:
                assert kw == kw.lower(), f"Keyword '{kw}' in domain {domain_val} is not lowercase"

    def test_us_keywords_are_lowercase(self):
        for kw in US_KEYWORDS:
            assert kw == kw.lower(), f"US keyword '{kw}' is not lowercase"

    def test_local_keywords_are_lowercase(self):
        for kw in LOCAL_KEYWORDS:
            assert kw == kw.lower(), f"Local keyword '{kw}' is not lowercase"

    def test_international_keywords_are_lowercase(self):
        for kw in INTERNATIONAL_KEYWORDS:
            assert kw == kw.lower(), f"International keyword '{kw}' is not lowercase"

    def test_all_keywords_are_strings(self):
        """All keywords should be strings."""
        for domain_val, keywords in DOMAIN_KEYWORDS.items():
            assert isinstance(keywords, set)
            for kw in keywords:
                assert isinstance(kw, str), f"Keyword {kw!r} in domain {domain_val} is not a string"
