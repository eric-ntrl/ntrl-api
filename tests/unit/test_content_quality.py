# tests/unit/test_content_quality.py
"""
Unit tests for content quality hardening features.

Covers:
- Source domain blocking at ingestion time
- is_blocked filter in brief assembly
- Scraping artifact cleanup (clean_body_artifacts)
- Content coherence QC check (#20)
- Source diversity cap in brief assembly
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.constants import SourceFiltering
from app.services.brief_assembly import BriefAssemblyService, StoryRow
from app.services.quality_gate import QCConfig, QualityGateService
from app.utils.content_sanitizer import clean_body_artifacts

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(slug="ap", name="AP News", is_blocked=False):
    source = MagicMock()
    source.id = uuid.uuid4()
    source.slug = slug
    source.name = name
    source.is_blocked = is_blocked
    source.homepage_url = f"https://{slug}.com"
    return source


def _make_story_raw(source_id=None, feed_category="world"):
    raw = MagicMock()
    raw.id = uuid.uuid4()
    raw.source_id = source_id or uuid.uuid4()
    raw.published_at = datetime.now(UTC) - timedelta(hours=1)
    raw.original_url = "https://example.com/article"
    raw.original_title = "Test Article"
    raw.is_duplicate = False
    raw.feed_category = feed_category
    raw.raw_content_available = True
    raw.body_is_truncated = False
    raw.source_type = "perigon"
    raw.raw_content_size = 5000
    raw.url_status = None
    raw.url_http_status = None
    return raw


def _make_neutralized(
    feed_title="Economic Growth Slows in Third Quarter",
    feed_summary="The economy showed signs of slowing with lower growth metrics.",
    detail_brief="The latest economic data shows a slowdown in growth. Analysts are watching closely.",
    detail_full="The latest economic data shows a slowdown in growth for the third quarter. "
    "Multiple indicators suggest that the trajectory may continue into next quarter. "
    "Economists from several major institutions have weighed in on the implications.",
):
    n = MagicMock()
    n.id = uuid.uuid4()
    n.story_raw_id = uuid.uuid4()
    n.is_current = True
    n.neutralization_status = "success"
    n.qc_status = "passed"
    n.feed_title = feed_title
    n.feed_summary = feed_summary
    n.detail_brief = detail_brief
    n.detail_full = detail_full
    n.has_manipulative_content = False
    n.disclosure = None
    return n


# ---------------------------------------------------------------------------
# clean_body_artifacts tests
# ---------------------------------------------------------------------------


class TestCleanBodyArtifacts:
    """Tests for scraping artifact removal."""

    def test_strips_recommended_stories(self):
        text = "First paragraph.\n\nRECOMMENDED STORIES\n\nSecond paragraph."
        result = clean_body_artifacts(text)
        assert "RECOMMENDED STORIES" not in result
        assert "First paragraph." in result
        assert "Second paragraph." in result

    def test_strips_related_articles(self):
        text = "Content here.\n\nRelated Articles\n\nMore content."
        result = clean_body_artifacts(text)
        assert "Related Articles" not in result

    def test_strips_advertisement(self):
        text = "Story text.\n\nAdvertisement\n\nMore story text."
        result = clean_body_artifacts(text)
        assert "Advertisement" not in result
        assert "Story text." in result

    def test_strips_social_sharing(self):
        text = "News content.\n\nShare this on Facebook and Twitter\n\nFinal paragraph."
        result = clean_body_artifacts(text)
        assert "Share this" not in result

    def test_strips_subscribe_line(self):
        text = "Article body.\n\nSubscribe\n\nMore text."
        result = clean_body_artifacts(text)
        assert result == "Article body.\n\nMore text."

    def test_strips_cookie_notice(self):
        text = "Article body.\n\nWe use cookies to improve your experience.\n\nMore text."
        result = clean_body_artifacts(text)
        assert "cookies" not in result

    def test_strips_comments_header(self):
        text = "Article body.\n\nComments\n\nMore text."
        result = clean_body_artifacts(text)
        assert result == "Article body.\n\nMore text."

    def test_clean_text_passes_unchanged(self):
        text = "The economy grew at a 2.1% rate last quarter. Analysts expect continued growth."
        result = clean_body_artifacts(text)
        assert result == text

    def test_collapses_excessive_blank_lines(self):
        text = "Paragraph one.\n\n\n\n\nParagraph two."
        result = clean_body_artifacts(text)
        assert result == "Paragraph one.\n\nParagraph two."

    def test_multiple_artifacts_stripped(self):
        text = (
            "Real content here.\n\n"
            "TRENDING STORIES\n\n"
            "More real content.\n\n"
            "Advertisement\n\n"
            "Follow us on Twitter for updates\n\n"
            "Final paragraph."
        )
        result = clean_body_artifacts(text)
        assert "TRENDING" not in result
        assert "Advertisement" not in result
        assert "Follow us" not in result
        assert "Real content here." in result
        assert "Final paragraph." in result

    def test_empty_string(self):
        assert clean_body_artifacts("") == ""

    def test_case_insensitive(self):
        text = "Content.\n\nadvertisement\n\nMore."
        result = clean_body_artifacts(text)
        assert "advertisement" not in result


# ---------------------------------------------------------------------------
# Content coherence QC check tests
# ---------------------------------------------------------------------------


class TestContentCoherenceCheck:
    """Tests for the content_coherence QC check."""

    def setup_method(self):
        self.service = QualityGateService()
        self.config = QCConfig()

    def test_clean_article_passes(self):
        raw = _make_story_raw()
        neutralized = _make_neutralized()
        source = _make_source()
        result = self.service._check_content_coherence(raw, neutralized, source, self.config)
        assert result.passed

    def test_unicode_spam_title_detected(self):
        raw = _make_story_raw()
        neutralized = _make_neutralized(feed_title="\u2460\u2461\u2462\u2463 Watch Movie Free")
        source = _make_source()
        result = self.service._check_content_coherence(raw, neutralized, source, self.config)
        assert not result.passed
        assert "spam pattern" in result.reason

    def test_template_text_detected(self):
        raw = _make_story_raw()
        neutralized = _make_neutralized(detail_full="Lorem ipsum dolor sit amet, consectetur adipiscing elit.")
        source = _make_source()
        result = self.service._check_content_coherence(raw, neutralized, source, self.config)
        assert not result.passed
        assert "spam pattern" in result.reason

    def test_pirate_streaming_detected(self):
        raw = _make_story_raw()
        neutralized = _make_neutralized(feed_title="Watch on 123movies Free HD")
        source = _make_source()
        result = self.service._check_content_coherence(raw, neutralized, source, self.config)
        assert not result.passed

    def test_all_caps_title_detected(self):
        raw = _make_story_raw()
        neutralized = _make_neutralized(feed_title="THIS IS AN ALL CAPS TITLE FOR CLICKS")
        source = _make_source()
        result = self.service._check_content_coherence(raw, neutralized, source, self.config)
        assert not result.passed
        assert "ALL-CAPS" in result.reason

    def test_short_caps_title_passes(self):
        """Short titles (<=3 words) should not trigger ALL-CAPS check."""
        raw = _make_story_raw()
        neutralized = _make_neutralized(feed_title="FBI UPDATE")
        source = _make_source()
        result = self.service._check_content_coherence(raw, neutralized, source, self.config)
        assert result.passed

    def test_repeated_sentence_detected(self):
        raw = _make_story_raw()
        repeated = "This is a sentence that appears many times in the article"
        detail_full = f"{repeated}. {repeated}. {repeated}. Normal ending."
        neutralized = _make_neutralized(detail_full=detail_full)
        source = _make_source()
        result = self.service._check_content_coherence(raw, neutralized, source, self.config)
        assert not result.passed
        assert "repeated sentence" in result.reason

    def test_normal_title_with_one_caps_word_passes(self):
        raw = _make_story_raw()
        neutralized = _make_neutralized(feed_title="FBI Investigates New Cybersecurity Threats")
        source = _make_source()
        result = self.service._check_content_coherence(raw, neutralized, source, self.config)
        assert result.passed

    def test_coherence_check_registered(self):
        """content_coherence should be registered as a check."""
        check_names = [c.name for c in self.service._checks]
        assert "content_coherence" in check_names


# ---------------------------------------------------------------------------
# Source diversity cap tests
# ---------------------------------------------------------------------------


class TestSourceDiversityCap:
    """Tests for per-source cap in brief assembly."""

    def test_cap_limits_single_source(self):
        """A source with more than MAX articles per category should be capped."""
        svc = BriefAssemblyService()
        source = _make_source(slug="spam-source")

        # Create 6 stories from the same source
        stories = []
        for i in range(6):
            raw = _make_story_raw(source_id=source.id)
            raw.published_at = datetime.now(UTC) - timedelta(hours=i)
            neutralized = _make_neutralized()
            stories.append(StoryRow(neutralized, raw, source))

        result = svc._enforce_source_diversity(stories)
        assert len(result) == SourceFiltering.MAX_PER_SOURCE_PER_CATEGORY

    def test_cap_preserves_diverse_sources(self):
        """Stories from different sources should all pass through."""
        svc = BriefAssemblyService()

        stories = []
        for i in range(5):
            source = _make_source(slug=f"source-{i}")
            raw = _make_story_raw(source_id=source.id)
            raw.published_at = datetime.now(UTC) - timedelta(hours=i)
            neutralized = _make_neutralized()
            stories.append(StoryRow(neutralized, raw, source))

        result = svc._enforce_source_diversity(stories)
        assert len(result) == 5

    def test_cap_mixed_sources(self):
        """Mix of one dominant source and others should cap dominant one."""
        svc = BriefAssemblyService()

        stories = []
        dominant = _make_source(slug="dominant")
        other = _make_source(slug="other")

        # 5 from dominant, 2 from other
        for i in range(5):
            raw = _make_story_raw(source_id=dominant.id)
            raw.published_at = datetime.now(UTC) - timedelta(hours=i)
            neutralized = _make_neutralized()
            stories.append(StoryRow(neutralized, raw, dominant))

        for i in range(2):
            raw = _make_story_raw(source_id=other.id)
            raw.published_at = datetime.now(UTC) - timedelta(hours=i)
            neutralized = _make_neutralized()
            stories.append(StoryRow(neutralized, raw, other))

        result = svc._enforce_source_diversity(stories)
        dominant_count = sum(1 for s in result if s.source.slug == "dominant")
        other_count = sum(1 for s in result if s.source.slug == "other")
        assert dominant_count == SourceFiltering.MAX_PER_SOURCE_PER_CATEGORY
        assert other_count == 2

    def test_empty_list(self):
        svc = BriefAssemblyService()
        result = svc._enforce_source_diversity([])
        assert result == []


# ---------------------------------------------------------------------------
# BLOCKED_DOMAINS constant tests
# ---------------------------------------------------------------------------


class TestBlockedDomains:
    """Tests for the BLOCKED_DOMAINS constant."""

    def test_known_spam_domains_present(self):
        assert "dev.healthimpactnews.com" in SourceFiltering.BLOCKED_DOMAINS
        assert "healthimpactnews.com" in SourceFiltering.BLOCKED_DOMAINS

    def test_non_news_domains_present(self):
        assert "imdb.com" in SourceFiltering.BLOCKED_DOMAINS
        assert "www.imdb.com" in SourceFiltering.BLOCKED_DOMAINS

    def test_legitimate_domain_not_blocked(self):
        assert "apnews.com" not in SourceFiltering.BLOCKED_DOMAINS
        assert "reuters.com" not in SourceFiltering.BLOCKED_DOMAINS


# ---------------------------------------------------------------------------
# Integration: QC gate includes content_coherence
# ---------------------------------------------------------------------------


class TestQCGateIntegration:
    """Test that content_coherence integrates into the full QC flow."""

    def test_spam_article_fails_qc(self):
        """An article with spam patterns should fail the full QC check."""
        service = QualityGateService()
        raw = _make_story_raw()
        neutralized = _make_neutralized(
            feed_title="\u2460\u2461\u2462\u2463 Stream Free Movies",
        )
        source = _make_source()

        result = service.check_article(raw, neutralized, source)
        assert result.status.value == "failed"
        failed_checks = [f.check for f in result.failures]
        assert "content_coherence" in failed_checks

    def test_clean_article_passes_qc(self):
        """A normal article should pass all checks including coherence."""
        service = QualityGateService()
        raw = _make_story_raw()
        neutralized = _make_neutralized()
        source = _make_source()

        result = service.check_article(raw, neutralized, source)
        # Check that content_coherence passed specifically
        coherence_results = [c for c in result.checks if c.check == "content_coherence"]
        assert len(coherence_results) == 1
        assert coherence_results[0].passed
