# tests/unit/test_quality_gate.py
"""
Unit tests for the Quality Control gate service.

Covers:
- Each of the 21 individual QC checks (pass and fail cases)
- Aggregate check_article() behavior
- QC configuration overrides
- Edge cases (empty fields, boundary values, garbled output detection)
- LLM refusal/apology detection
- Original body size sufficiency
- Brief/full view difference detection
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.services.quality_gate import (
    QCCheckResult,
    QCConfig,
    QCStatus,
    QualityGateService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(slug: str = "ap", name: str = "AP News") -> MagicMock:
    """Create a mock Source object."""
    source = MagicMock()
    source.slug = slug
    source.name = name
    source.id = uuid.uuid4()
    return source


def _make_story_raw(
    story_id=None,
    published_at=None,
    source_id=None,
    feed_category="world",
    is_duplicate=False,
    original_url="https://example.com/article",
    raw_content_available=True,
    body_is_truncated=False,
    source_type="rss",
    raw_content_size=5000,
    url_status=None,
    url_http_status=None,
) -> MagicMock:
    """Create a mock StoryRaw object."""
    raw = MagicMock()
    raw.id = story_id or uuid.uuid4()
    raw.published_at = published_at or datetime.now(UTC) - timedelta(hours=1)
    raw.source_id = source_id or uuid.uuid4()
    raw.feed_category = feed_category
    raw.is_duplicate = is_duplicate
    raw.duplicate_of_id = None
    raw.original_url = original_url
    raw.original_title = "Test Article Title"
    raw.raw_content_available = raw_content_available
    raw.body_is_truncated = body_is_truncated
    raw.source_type = source_type
    raw.raw_content_size = raw_content_size
    raw.url_status = url_status
    raw.url_http_status = url_http_status
    return raw


_SENTINEL = object()


def _make_neutralized(
    neutralized_id=None,
    story_raw_id=None,
    status="success",
    feed_title="Test Article Headline",
    feed_summary="This is a test summary for the article with enough characters to pass bounds.",
    detail_brief=_SENTINEL,
    detail_full=_SENTINEL,
    has_manipulative_content=False,
    disclosure="Manipulative language removed.",
    failure_reason=None,
) -> MagicMock:
    """Create a mock StoryNeutralized object."""
    n = MagicMock()
    n.id = neutralized_id or uuid.uuid4()
    n.story_raw_id = story_raw_id or uuid.uuid4()
    n.is_current = True
    n.neutralization_status = status
    n.feed_title = feed_title
    n.feed_summary = feed_summary
    n.detail_brief = "This is a test detail brief. " * 10 if detail_brief is _SENTINEL else detail_brief
    n.detail_full = (
        (
            "The economy showed mixed signals in the latest quarterly report. "
            "Growth remained steady at two percent while consumer spending held firm. "
            "Exports declined slightly due to ongoing trade tensions between major economies. "
            "The labor market added jobs across multiple sectors including technology and healthcare. "
            "Inflation stayed within the target range set by the central bank during the period. "
            "Housing starts rose modestly in suburban areas driven by demand from remote workers. "
            "Retail sales exceeded expectations for the third straight month boosted by holiday spending. "
            "Manufacturing output was flat compared to the prior quarter amid supply chain adjustments. "
            "Analysts expect moderate growth to continue into next year based on current indicators. "
            "The federal reserve signaled it would maintain current interest rate levels through spring. "
            "International markets responded positively to the economic data released on Friday morning. "
            "Small business confidence improved according to the latest survey from the commerce department."
        )
        if detail_full is _SENTINEL
        else detail_full
    )
    n.has_manipulative_content = has_manipulative_content
    n.disclosure = disclosure
    n.failure_reason = failure_reason
    n.qc_status = None
    n.qc_failures = None
    n.qc_checked_at = None
    return n


def _service(config=None):
    return QualityGateService(config=config)


# ---------------------------------------------------------------------------
# A. Required Fields checks
# ---------------------------------------------------------------------------


class TestRequiredFeedTitle:
    def test_pass(self):
        svc = _service()
        result = svc._check_required_feed_title(_make_story_raw(), _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_empty(self):
        n = _make_neutralized(feed_title="")
        result = _service()._check_required_feed_title(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "empty" in result.reason

    def test_fail_none(self):
        n = _make_neutralized(feed_title=None)
        result = _service()._check_required_feed_title(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False

    def test_fail_whitespace_only(self):
        n = _make_neutralized(feed_title="   ")
        result = _service()._check_required_feed_title(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False


class TestRequiredFeedSummary:
    def test_pass(self):
        result = _service()._check_required_feed_summary(
            _make_story_raw(), _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_empty(self):
        n = _make_neutralized(feed_summary="")
        result = _service()._check_required_feed_summary(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False


class TestRequiredSource:
    def test_pass(self):
        result = _service()._check_required_source(_make_story_raw(), _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_no_source(self):
        result = _service()._check_required_source(_make_story_raw(), _make_neutralized(), None, QCConfig())
        assert result.passed is False
        assert "No source" in result.reason

    def test_fail_empty_name(self):
        source = _make_source(name="")
        result = _service()._check_required_source(_make_story_raw(), _make_neutralized(), source, QCConfig())
        assert result.passed is False
        assert "empty name" in result.reason


class TestRequiredPublishedAt:
    def test_pass(self):
        raw = _make_story_raw(published_at=datetime.now(UTC) - timedelta(hours=2))
        result = _service()._check_required_published_at(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_none(self):
        raw = _make_story_raw()
        raw.published_at = None
        result = _service()._check_required_published_at(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "not set" in result.reason

    def test_fail_future(self):
        raw = _make_story_raw(published_at=datetime.now(UTC) + timedelta(hours=5))
        result = _service()._check_required_published_at(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "future" in result.reason

    def test_pass_near_future_within_buffer(self):
        """Published 30 min in future should pass with 1h buffer."""
        raw = _make_story_raw(published_at=datetime.now(UTC) + timedelta(minutes=30))
        result = _service()._check_required_published_at(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_naive_datetime(self):
        """DB may return naive datetimes — should not crash."""
        naive_dt = datetime.utcnow() - timedelta(hours=1)
        assert naive_dt.tzinfo is None  # confirm it's naive
        raw = _make_story_raw(published_at=naive_dt)
        result = _service()._check_required_published_at(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_naive_future_datetime(self):
        """Naive future datetime should fail without crashing."""
        naive_dt = datetime.utcnow() + timedelta(hours=5)
        raw = _make_story_raw(published_at=naive_dt)
        result = _service()._check_required_published_at(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "future" in result.reason


class TestRequiredOriginalUrl:
    def test_pass_https(self):
        raw = _make_story_raw(original_url="https://example.com/article")
        result = _service()._check_required_original_url(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_http(self):
        raw = _make_story_raw(original_url="http://example.com/article")
        result = _service()._check_required_original_url(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_empty(self):
        raw = _make_story_raw(original_url="")
        result = _service()._check_required_original_url(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False

    def test_fail_bad_scheme(self):
        raw = _make_story_raw(original_url="ftp://example.com/file")
        result = _service()._check_required_original_url(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "invalid scheme" in result.reason


class TestRequiredFeedCategory:
    def test_pass(self):
        raw = _make_story_raw(feed_category="world")
        result = _service()._check_required_feed_category(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_none(self):
        raw = _make_story_raw(feed_category=None)
        result = _service()._check_required_feed_category(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "not set" in result.reason

    def test_fail_invalid_value(self):
        raw = _make_story_raw(feed_category="nonsense_category")
        result = _service()._check_required_feed_category(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "not a valid FeedCategory" in result.reason

    def test_pass_all_valid_categories(self):
        from app.models import FeedCategory

        for cat in FeedCategory:
            raw = _make_story_raw(feed_category=cat.value)
            result = _service()._check_required_feed_category(raw, _make_neutralized(), _make_source(), QCConfig())
            assert result.passed is True, f"Category {cat.value} should pass"


class TestSourceNameNotGeneric:
    def test_pass_real_publisher(self):
        source = _make_source(name="AP News", slug="ap")
        result = _service()._check_source_name_not_generic(_make_story_raw(), _make_neutralized(), source, QCConfig())
        assert result.passed is True

    def test_fail_perigon_api(self):
        source = _make_source(name="Perigon News API", slug="perigon-news-api")
        result = _service()._check_source_name_not_generic(_make_story_raw(), _make_neutralized(), source, QCConfig())
        assert result.passed is False
        assert "Generic API source name" in result.reason

    def test_fail_newsdata(self):
        source = _make_source(name="NewsData.io", slug="newsdata-io")
        result = _service()._check_source_name_not_generic(_make_story_raw(), _make_neutralized(), source, QCConfig())
        assert result.passed is False

    def test_pass_no_source(self):
        """None source should pass (required_source check catches this)."""
        result = _service()._check_source_name_not_generic(_make_story_raw(), _make_neutralized(), None, QCConfig())
        assert result.passed is True


# ---------------------------------------------------------------------------
# B. Content Quality checks
# ---------------------------------------------------------------------------


class TestOriginalBodyComplete:
    def test_pass_normal_article(self):
        raw = _make_story_raw(raw_content_available=True, body_is_truncated=False)
        result = _service()._check_original_body_complete(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_truncated(self):
        raw = _make_story_raw(raw_content_available=True, body_is_truncated=True, source_type="perigon")
        result = _service()._check_original_body_complete(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "truncated" in result.reason

    def test_fail_unavailable(self):
        raw = _make_story_raw(raw_content_available=False)
        result = _service()._check_original_body_complete(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "not available" in result.reason


class TestMinBodyLength:
    def test_pass_both_above_min(self):
        n = _make_neutralized(
            detail_brief="word " * 60,  # 60 words
            detail_full="word " * 120,  # 120 words
        )
        result = _service()._check_min_body_length(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_brief_only(self):
        """If only detail_brief meets threshold, should fail (both required)."""
        n = _make_neutralized(
            detail_brief="word " * 55,  # 55 words >= 50
            detail_full="short",  # 1 word < 100
        )
        result = _service()._check_min_body_length(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "detail_full" in result.reason

    def test_fail_full_only(self):
        """If only detail_full meets threshold, should fail (both required)."""
        n = _make_neutralized(
            detail_brief="short",  # 1 word < 50
            detail_full="word " * 110,  # 110 words >= 100
        )
        result = _service()._check_min_body_length(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "detail_brief" in result.reason

    def test_fail_both_below_min(self):
        n = _make_neutralized(
            detail_brief="word " * 10,  # 10 words < 50
            detail_full="word " * 20,  # 20 words < 100
        )
        result = _service()._check_min_body_length(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "brief" in result.reason and "full" in result.reason

    def test_fail_both_empty(self):
        n = _make_neutralized(detail_brief="", detail_full="")
        result = _service()._check_min_body_length(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False

    def test_custom_thresholds_both_pass(self):
        config = QCConfig(min_detail_brief_words=10, min_detail_full_words=20)
        n = _make_neutralized(
            detail_brief="word " * 12,
            detail_full="word " * 25,
        )
        result = _service(config)._check_min_body_length(_make_story_raw(), n, _make_source(), config)
        assert result.passed is True

    def test_custom_thresholds_full_fails(self):
        config = QCConfig(min_detail_brief_words=10, min_detail_full_words=20)
        n = _make_neutralized(
            detail_brief="word " * 12,
            detail_full="word " * 5,
        )
        result = _service(config)._check_min_body_length(_make_story_raw(), n, _make_source(), config)
        assert result.passed is False
        assert "detail_full" in result.reason


class TestFeedTitleBounds:
    def test_pass_normal(self):
        n = _make_neutralized(feed_title="Normal Headline Here")
        result = _service()._check_feed_title_bounds(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_too_short(self):
        n = _make_neutralized(feed_title="Hi")
        result = _service()._check_feed_title_bounds(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "min" in result.reason

    def test_fail_too_long(self):
        n = _make_neutralized(feed_title="A" * 85)
        result = _service()._check_feed_title_bounds(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "max" in result.reason

    def test_boundary_min(self):
        n = _make_neutralized(feed_title="Hello")  # 5 chars = min
        result = _service()._check_feed_title_bounds(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_boundary_max(self):
        n = _make_neutralized(feed_title="A" * 80)  # 80 chars = max
        result = _service()._check_feed_title_bounds(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True


class TestFeedSummaryBounds:
    def test_pass_normal(self):
        n = _make_neutralized(feed_summary="This is a normal summary with enough characters to pass the minimum check.")
        result = _service()._check_feed_summary_bounds(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_too_short(self):
        n = _make_neutralized(feed_summary="Short.")
        result = _service()._check_feed_summary_bounds(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False

    def test_fail_too_long(self):
        n = _make_neutralized(feed_summary="A" * 310)
        result = _service()._check_feed_summary_bounds(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False


class TestNoGarbledOutput:
    def test_pass_clean(self):
        n = _make_neutralized(
            feed_title="Clean Headline",
            feed_summary="A perfectly normal summary.",
            detail_brief="Normal article brief content here.",
        )
        result = _service()._check_no_garbled_output(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_placeholder_title(self):
        n = _make_neutralized(feed_title="[TITLE] placeholder text")
        result = _service()._check_no_garbled_output(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "placeholder" in result.reason

    def test_fail_handlebars_template(self):
        n = _make_neutralized(feed_summary="The {{article}} was published by {{source}}")
        result = _service()._check_no_garbled_output(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False

    def test_fail_repeated_words(self):
        n = _make_neutralized(feed_title="the the the the same word repeating")
        result = _service()._check_no_garbled_output(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "repeated word" in result.reason

    def test_fail_json_artifact(self):
        n = _make_neutralized(feed_title='{"title": "some JSON output"}')
        result = _service()._check_no_garbled_output(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "JSON" in result.reason

    def test_pass_normal_brackets(self):
        """Brackets in normal prose should not trigger false positive."""
        n = _make_neutralized(feed_title="U.S. [Updated] Policy Changes")
        result = _service()._check_no_garbled_output(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_short_repeated_words_ignored(self):
        """Short words (2 chars or less) shouldn't trigger repeated word check."""
        n = _make_neutralized(feed_title="to to to go home")
        result = _service()._check_no_garbled_output(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True


class TestNoLlmRefusal:
    def test_pass_clean(self):
        n = _make_neutralized()
        result = _service()._check_no_llm_refusal(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_sorry_in_detail_full(self):
        n = _make_neutralized(
            detail_full="I'm sorry, but I can't process this article because the content is incomplete."
        )
        result = _service()._check_no_llm_refusal(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "detail_full" in result.reason

    def test_fail_apologize_in_brief(self):
        n = _make_neutralized(detail_brief="I apologize, but I cannot provide a neutralized version of this article.")
        result = _service()._check_no_llm_refusal(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False

    def test_fail_as_an_ai(self):
        n = _make_neutralized(
            detail_full="As an AI language model, I cannot determine the factual content of this article."
        )
        result = _service()._check_no_llm_refusal(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False

    def test_fail_unable_to(self):
        n = _make_neutralized(detail_full="I'm unable to summarize this article as it appears to be behind a paywall.")
        result = _service()._check_no_llm_refusal(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False

    def test_fail_unfortunately(self):
        n = _make_neutralized(
            detail_full="Unfortunately, I can't provide a neutralized version because the source content is missing."
        )
        result = _service()._check_no_llm_refusal(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False

    def test_fail_article_too_short(self):
        n = _make_neutralized(detail_full="The article provided is too short to produce a meaningful neutralization.")
        result = _service()._check_no_llm_refusal(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False

    def test_fail_i_cannot(self):
        n = _make_neutralized(detail_full="I cannot provide a rewritten version of this article.")
        result = _service()._check_no_llm_refusal(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False

    def test_pass_none_fields(self):
        n = _make_neutralized(detail_brief=None, detail_full=None)
        result = _service()._check_no_llm_refusal(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_article_about_ai(self):
        """An article that discusses AI apologies mid-text should NOT be flagged."""
        n = _make_neutralized(
            detail_full=(
                "The chatbot responded with 'I'm sorry, but I can't help with that' "
                "when asked about medical advice. This has raised concerns about AI limitations."
            )
        )
        result = _service()._check_no_llm_refusal(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True


class TestOriginalBodySufficient:
    def test_pass_normal_article(self):
        raw = _make_story_raw(raw_content_size=5000)
        result = _service()._check_original_body_sufficient(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_snippet(self):
        raw = _make_story_raw(raw_content_size=200)
        result = _service()._check_original_body_sufficient(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "snippet" in result.reason

    def test_pass_no_size_metadata(self):
        """If raw_content_size is None, pass optimistically."""
        raw = _make_story_raw(raw_content_size=None)
        result = _service()._check_original_body_sufficient(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_content_unavailable(self):
        """If body isn't available, let original_body_complete handle it."""
        raw = _make_story_raw(raw_content_available=False, raw_content_size=100)
        result = _service()._check_original_body_sufficient(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_boundary_at_threshold(self):
        raw = _make_story_raw(raw_content_size=500)
        result = _service()._check_original_body_sufficient(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True  # >= threshold passes

    def test_boundary_below_threshold(self):
        raw = _make_story_raw(raw_content_size=499)
        result = _service()._check_original_body_sufficient(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False


class TestContentIsNews:
    def test_pass_normal_article(self):
        raw = _make_story_raw()
        raw.original_title = "Congress Passes New Infrastructure Bill"
        result = _service()._check_content_is_news(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_weather_forecast_temperature(self):
        raw = _make_story_raw()
        raw.original_title = "NYC Weather Saturday: Light Snow, -2°C Expected"
        result = _service()._check_content_is_news(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "weather" in result.reason.lower()

    def test_fail_weather_forecast_keyword(self):
        raw = _make_story_raw()
        raw.original_title = "Chicago Weather Forecast for the Week Ahead"
        result = _service()._check_content_is_news(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False

    def test_fail_gambling_promo(self):
        raw = _make_story_raw()
        raw.original_title = "FanDuel Promo Code for USA vs Canada: Get $200 Bonus Bets"
        result = _service()._check_content_is_news(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "gambling" in result.reason.lower() or "promo" in result.reason.lower()

    def test_fail_sportsbook_offer(self):
        raw = _make_story_raw()
        raw.original_title = "Best Sportsbook Offer for Super Bowl: Free Bets Available"
        result = _service()._check_content_is_news(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False

    def test_pass_sports_article(self):
        """Sports news should pass — only promos/forecasts are blocked."""
        raw = _make_story_raw()
        raw.original_title = "PGA Tour: Genesis Invitational Final Round Results"
        result = _service()._check_content_is_news(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_climate_article(self):
        """Climate change articles should not be caught by weather patterns."""
        raw = _make_story_raw()
        raw.original_title = "Global Warming Effects on Arctic Ice Shelf Studied"
        result = _service()._check_content_is_news(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True


# ---------------------------------------------------------------------------
# C. Pipeline Integrity checks
# ---------------------------------------------------------------------------


class TestNeutralizationSuccess:
    def test_pass(self):
        n = _make_neutralized(status="success")
        result = _service()._check_neutralization_success(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_llm_error(self):
        n = _make_neutralized(status="failed_llm")
        result = _service()._check_neutralization_success(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "failed_llm" in result.reason

    def test_fail_garbled(self):
        n = _make_neutralized(status="failed_garbled")
        result = _service()._check_neutralization_success(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False


class TestNotDuplicate:
    def test_pass(self):
        raw = _make_story_raw(is_duplicate=False)
        result = _service()._check_not_duplicate(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_fail(self):
        raw = _make_story_raw(is_duplicate=True)
        result = _service()._check_not_duplicate(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "duplicate" in result.reason


class TestUrlReachable:
    """Tests for check #19: url_reachable."""

    def test_pass_not_yet_checked(self):
        """url_status=None means not yet validated — should pass."""
        raw = _make_story_raw(url_status=None)
        result = _service()._check_url_reachable(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_reachable(self):
        raw = _make_story_raw(url_status="reachable", url_http_status=200)
        result = _service()._check_url_reachable(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_redirect(self):
        raw = _make_story_raw(url_status="redirect", url_http_status=301)
        result = _service()._check_url_reachable(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_timeout(self):
        """Timeouts are temporary — should pass."""
        raw = _make_story_raw(url_status="timeout")
        result = _service()._check_url_reachable(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_unreachable_404(self):
        raw = _make_story_raw(url_status="unreachable", url_http_status=404)
        result = _service()._check_url_reachable(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "404" in result.reason

    def test_fail_unreachable_410(self):
        raw = _make_story_raw(url_status="unreachable", url_http_status=410)
        result = _service()._check_url_reachable(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "410" in result.reason

    def test_fail_unreachable_403(self):
        raw = _make_story_raw(url_status="unreachable", url_http_status=403)
        result = _service()._check_url_reachable(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert "403" in result.reason

    def test_pass_unreachable_500(self):
        """Server errors are temporary — should pass through."""
        raw = _make_story_raw(url_status="unreachable", url_http_status=500)
        result = _service()._check_url_reachable(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_unreachable_no_http_status(self):
        """Network error (no HTTP status) — should pass through."""
        raw = _make_story_raw(url_status="unreachable", url_http_status=None)
        result = _service()._check_url_reachable(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_details_include_url_preview(self):
        raw = _make_story_raw(
            url_status="unreachable",
            url_http_status=404,
            original_url="https://example.com/very-long-article-url",
        )
        result = _service()._check_url_reachable(raw, _make_neutralized(), _make_source(), QCConfig())
        assert result.passed is False
        assert result.details["url_preview"] == "https://example.com/very-long-article-url"
        assert result.details["http_status"] == 404


# ---------------------------------------------------------------------------
# D. View Completeness checks
# ---------------------------------------------------------------------------


class TestViewsRenderable:
    def test_pass_both_present(self):
        n = _make_neutralized(
            detail_brief="Some brief content.",
            detail_full="Some full content.",
        )
        result = _service()._check_views_renderable(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_brief_only(self):
        n = _make_neutralized(
            detail_brief="Some brief content.",
            detail_full=None,
        )
        result = _service()._check_views_renderable(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_full_only(self):
        n = _make_neutralized(
            detail_brief=None,
            detail_full="Some full content.",
        )
        result = _service()._check_views_renderable(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_neither(self):
        n = _make_neutralized(
            detail_brief=None,
            detail_full=None,
        )
        result = _service()._check_views_renderable(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "Neither" in result.reason

    def test_fail_both_empty_strings(self):
        n = _make_neutralized(
            detail_brief="",
            detail_full="   ",
        )
        result = _service()._check_views_renderable(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False

    def test_pass_manipulative_with_disclosure(self):
        n = _make_neutralized(
            has_manipulative_content=True,
            disclosure="Manipulative language removed.",
        )
        result = _service()._check_views_renderable(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_manipulative_without_disclosure(self):
        n = _make_neutralized(
            has_manipulative_content=True,
            disclosure="",
        )
        result = _service()._check_views_renderable(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "disclosure" in result.reason


class TestBriefFullDifferent:
    def test_pass_both_present_different(self):
        n = _make_neutralized(
            detail_brief="A short brief about the article topic.",
            detail_full="A much longer full version with many more details about the article topic and additional context and information.",
        )
        result = _service()._check_brief_full_different(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_fail_full_is_none(self):
        n = _make_neutralized(
            detail_brief="Some brief content here.",
            detail_full=None,
        )
        result = _service()._check_brief_full_different(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "empty/None" in result.reason

    def test_fail_full_is_empty(self):
        n = _make_neutralized(
            detail_brief="Some brief content here.",
            detail_full="",
        )
        result = _service()._check_brief_full_different(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "empty/None" in result.reason

    def test_fail_identical_content(self):
        text = "The exact same text appears in both views."
        n = _make_neutralized(
            detail_brief=text,
            detail_full=text,
        )
        result = _service()._check_brief_full_different(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "100%" in result.reason

    def test_fail_nearly_identical(self):
        n = _make_neutralized(
            detail_brief="The president signed the bill into law on Tuesday.",
            detail_full="The president signed the bill into law on Tuesday .",
        )
        result = _service()._check_brief_full_different(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is False
        assert "similar" in result.reason

    def test_pass_neither_present(self):
        n = _make_neutralized(
            detail_brief=None,
            detail_full=None,
        )
        result = _service()._check_brief_full_different(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True

    def test_pass_only_full_present(self):
        n = _make_neutralized(
            detail_brief=None,
            detail_full="Only the full view has content.",
        )
        result = _service()._check_brief_full_different(_make_story_raw(), n, _make_source(), QCConfig())
        assert result.passed is True


# ---------------------------------------------------------------------------
# Aggregate check_article() tests
# ---------------------------------------------------------------------------


class TestCheckArticle:
    def test_all_pass(self):
        """A well-formed article should pass all checks."""
        svc = _service()
        result = svc.check_article(
            _make_story_raw(),
            _make_neutralized(),
            _make_source(),
        )
        assert result.status == QCStatus.PASSED
        assert len(result.failures) == 0
        assert len(result.checks) == 21  # All 21 checks ran

    def test_single_failure(self):
        """An article with one failing check should fail overall."""
        svc = _service()
        raw = _make_story_raw(feed_category=None)  # Missing category
        result = svc.check_article(raw, _make_neutralized(), _make_source())
        assert result.status == QCStatus.FAILED
        assert len(result.failures) >= 1
        failure_checks = [f.check for f in result.failures]
        assert "required_feed_category" in failure_checks

    def test_multiple_failures(self):
        """An article with multiple issues should collect all failures."""
        svc = _service()
        raw = _make_story_raw(
            feed_category=None,
            original_url="ftp://bad-scheme.com",
            is_duplicate=True,
        )
        n = _make_neutralized(
            feed_title="Hi",  # Too short
            status="failed_llm",
        )
        result = svc.check_article(raw, n, _make_source())
        assert result.status == QCStatus.FAILED
        assert len(result.failures) >= 4

    def test_checked_at_set(self):
        svc = _service()
        result = svc.check_article(_make_story_raw(), _make_neutralized(), _make_source())
        assert result.checked_at is not None


# ---------------------------------------------------------------------------
# QCCheckResult serialization
# ---------------------------------------------------------------------------


class TestQCCheckResultToDict:
    def test_basic(self):
        r = QCCheckResult(
            check="min_body_length",
            passed=False,
            category="content_quality",
            reason="detail_brief has 10 words (min 50)",
            details={"brief_words": 10},
        )
        d = r.to_dict()
        assert d["check"] == "min_body_length"
        assert d["category"] == "content_quality"
        assert d["reason"] == "detail_brief has 10 words (min 50)"
        assert d["details"]["brief_words"] == 10

    def test_no_details(self):
        r = QCCheckResult(
            check="required_source",
            passed=True,
            category="required_fields",
        )
        d = r.to_dict()
        assert "details" not in d


# ---------------------------------------------------------------------------
# Configuration tests
# ---------------------------------------------------------------------------


class TestQCConfig:
    def test_default_values(self):
        config = QCConfig()
        assert config.min_detail_brief_words == 50
        assert config.min_detail_full_words == 100
        assert config.min_feed_title_chars == 5
        assert config.max_feed_title_chars == 80
        assert config.min_feed_summary_chars == 20
        assert config.max_feed_summary_chars == 300
        assert config.future_publish_buffer_hours == 1
        assert config.repeated_word_run_threshold == 3
        assert config.min_original_body_chars == 500

    def test_custom_values(self):
        config = QCConfig(
            min_detail_brief_words=25,
            max_feed_title_chars=100,
        )
        assert config.min_detail_brief_words == 25
        assert config.max_feed_title_chars == 100
        # Others still use defaults
        assert config.min_detail_full_words == 100
