# tests/unit/test_quality_gate.py
"""
Unit tests for the Quality Control gate service.

Covers:
- Each of the 13 individual QC checks (pass and fail cases)
- Aggregate check_article() behavior
- QC configuration overrides
- Edge cases (empty fields, boundary values, garbled output detection)
"""

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.services.quality_gate import (
    QualityGateService,
    QCConfig,
    QCCheckResult,
    QCResult,
    QCStatus,
    QCCategory,
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
) -> MagicMock:
    """Create a mock StoryRaw object."""
    raw = MagicMock()
    raw.id = story_id or uuid.uuid4()
    raw.published_at = published_at or datetime.utcnow() - timedelta(hours=1)
    raw.source_id = source_id or uuid.uuid4()
    raw.feed_category = feed_category
    raw.is_duplicate = is_duplicate
    raw.duplicate_of_id = None
    raw.original_url = original_url
    raw.original_title = "Test Article Title"
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
    n.detail_full = "This is a test detail full. " * 20 if detail_full is _SENTINEL else detail_full
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
        result = svc._check_required_feed_title(
            _make_story_raw(), _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_empty(self):
        n = _make_neutralized(feed_title="")
        result = _service()._check_required_feed_title(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "empty" in result.reason

    def test_fail_none(self):
        n = _make_neutralized(feed_title=None)
        result = _service()._check_required_feed_title(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False

    def test_fail_whitespace_only(self):
        n = _make_neutralized(feed_title="   ")
        result = _service()._check_required_feed_title(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False


class TestRequiredFeedSummary:
    def test_pass(self):
        result = _service()._check_required_feed_summary(
            _make_story_raw(), _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_empty(self):
        n = _make_neutralized(feed_summary="")
        result = _service()._check_required_feed_summary(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False


class TestRequiredSource:
    def test_pass(self):
        result = _service()._check_required_source(
            _make_story_raw(), _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_no_source(self):
        result = _service()._check_required_source(
            _make_story_raw(), _make_neutralized(), None, QCConfig()
        )
        assert result.passed is False
        assert "No source" in result.reason

    def test_fail_empty_name(self):
        source = _make_source(name="")
        result = _service()._check_required_source(
            _make_story_raw(), _make_neutralized(), source, QCConfig()
        )
        assert result.passed is False
        assert "empty name" in result.reason


class TestRequiredPublishedAt:
    def test_pass(self):
        raw = _make_story_raw(published_at=datetime.utcnow() - timedelta(hours=2))
        result = _service()._check_required_published_at(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_none(self):
        raw = _make_story_raw()
        raw.published_at = None
        result = _service()._check_required_published_at(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "not set" in result.reason

    def test_fail_future(self):
        raw = _make_story_raw(published_at=datetime.utcnow() + timedelta(hours=5))
        result = _service()._check_required_published_at(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "future" in result.reason

    def test_pass_near_future_within_buffer(self):
        """Published 30 min in future should pass with 1h buffer."""
        raw = _make_story_raw(published_at=datetime.utcnow() + timedelta(minutes=30))
        result = _service()._check_required_published_at(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is True


class TestRequiredOriginalUrl:
    def test_pass_https(self):
        raw = _make_story_raw(original_url="https://example.com/article")
        result = _service()._check_required_original_url(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_pass_http(self):
        raw = _make_story_raw(original_url="http://example.com/article")
        result = _service()._check_required_original_url(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_empty(self):
        raw = _make_story_raw(original_url="")
        result = _service()._check_required_original_url(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is False

    def test_fail_bad_scheme(self):
        raw = _make_story_raw(original_url="ftp://example.com/file")
        result = _service()._check_required_original_url(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "invalid scheme" in result.reason


class TestRequiredFeedCategory:
    def test_pass(self):
        raw = _make_story_raw(feed_category="world")
        result = _service()._check_required_feed_category(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_none(self):
        raw = _make_story_raw(feed_category=None)
        result = _service()._check_required_feed_category(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "not set" in result.reason

    def test_fail_invalid_value(self):
        raw = _make_story_raw(feed_category="nonsense_category")
        result = _service()._check_required_feed_category(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "not a valid FeedCategory" in result.reason

    def test_pass_all_valid_categories(self):
        from app.models import FeedCategory
        for cat in FeedCategory:
            raw = _make_story_raw(feed_category=cat.value)
            result = _service()._check_required_feed_category(
                raw, _make_neutralized(), _make_source(), QCConfig()
            )
            assert result.passed is True, f"Category {cat.value} should pass"


# ---------------------------------------------------------------------------
# B. Content Quality checks
# ---------------------------------------------------------------------------

class TestMinBodyLength:
    def test_pass_both_above_min(self):
        n = _make_neutralized(
            detail_brief="word " * 60,  # 60 words
            detail_full="word " * 120,  # 120 words
        )
        result = _service()._check_min_body_length(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_pass_brief_only(self):
        """If only detail_brief meets threshold, should pass."""
        n = _make_neutralized(
            detail_brief="word " * 55,  # 55 words >= 50
            detail_full="short",       # 1 word < 100
        )
        result = _service()._check_min_body_length(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_pass_full_only(self):
        """If only detail_full meets threshold, should pass."""
        n = _make_neutralized(
            detail_brief="short",        # 1 word < 50
            detail_full="word " * 110,   # 110 words >= 100
        )
        result = _service()._check_min_body_length(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_both_below_min(self):
        n = _make_neutralized(
            detail_brief="word " * 10,  # 10 words < 50
            detail_full="word " * 20,   # 20 words < 100
        )
        result = _service()._check_min_body_length(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "brief" in result.reason and "full" in result.reason

    def test_fail_both_empty(self):
        n = _make_neutralized(detail_brief="", detail_full="")
        result = _service()._check_min_body_length(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False

    def test_custom_thresholds(self):
        config = QCConfig(min_detail_brief_words=10, min_detail_full_words=20)
        n = _make_neutralized(
            detail_brief="word " * 12,
            detail_full="word " * 5,
        )
        result = _service(config)._check_min_body_length(
            _make_story_raw(), n, _make_source(), config
        )
        assert result.passed is True


class TestFeedTitleBounds:
    def test_pass_normal(self):
        n = _make_neutralized(feed_title="Normal Headline Here")
        result = _service()._check_feed_title_bounds(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_too_short(self):
        n = _make_neutralized(feed_title="Hi")
        result = _service()._check_feed_title_bounds(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "min" in result.reason

    def test_fail_too_long(self):
        n = _make_neutralized(feed_title="A" * 85)
        result = _service()._check_feed_title_bounds(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "max" in result.reason

    def test_boundary_min(self):
        n = _make_neutralized(feed_title="Hello")  # 5 chars = min
        result = _service()._check_feed_title_bounds(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_boundary_max(self):
        n = _make_neutralized(feed_title="A" * 80)  # 80 chars = max
        result = _service()._check_feed_title_bounds(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True


class TestFeedSummaryBounds:
    def test_pass_normal(self):
        n = _make_neutralized(feed_summary="This is a normal summary with enough characters to pass the minimum check.")
        result = _service()._check_feed_summary_bounds(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_too_short(self):
        n = _make_neutralized(feed_summary="Short.")
        result = _service()._check_feed_summary_bounds(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False

    def test_fail_too_long(self):
        n = _make_neutralized(feed_summary="A" * 310)
        result = _service()._check_feed_summary_bounds(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False


class TestNoGarbledOutput:
    def test_pass_clean(self):
        n = _make_neutralized(
            feed_title="Clean Headline",
            feed_summary="A perfectly normal summary.",
            detail_brief="Normal article brief content here.",
        )
        result = _service()._check_no_garbled_output(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_placeholder_title(self):
        n = _make_neutralized(feed_title="[TITLE] placeholder text")
        result = _service()._check_no_garbled_output(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "placeholder" in result.reason

    def test_fail_handlebars_template(self):
        n = _make_neutralized(feed_summary="The {{article}} was published by {{source}}")
        result = _service()._check_no_garbled_output(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False

    def test_fail_repeated_words(self):
        n = _make_neutralized(feed_title="the the the the same word repeating")
        result = _service()._check_no_garbled_output(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "repeated word" in result.reason

    def test_fail_json_artifact(self):
        n = _make_neutralized(feed_title='{"title": "some JSON output"}')
        result = _service()._check_no_garbled_output(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "JSON" in result.reason

    def test_pass_normal_brackets(self):
        """Brackets in normal prose should not trigger false positive."""
        n = _make_neutralized(feed_title="U.S. [Updated] Policy Changes")
        result = _service()._check_no_garbled_output(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_pass_short_repeated_words_ignored(self):
        """Short words (2 chars or less) shouldn't trigger repeated word check."""
        n = _make_neutralized(feed_title="to to to go home")
        result = _service()._check_no_garbled_output(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True


# ---------------------------------------------------------------------------
# C. Pipeline Integrity checks
# ---------------------------------------------------------------------------

class TestNeutralizationSuccess:
    def test_pass(self):
        n = _make_neutralized(status="success")
        result = _service()._check_neutralization_success(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_llm_error(self):
        n = _make_neutralized(status="failed_llm")
        result = _service()._check_neutralization_success(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "failed_llm" in result.reason

    def test_fail_garbled(self):
        n = _make_neutralized(status="failed_garbled")
        result = _service()._check_neutralization_success(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False


class TestNotDuplicate:
    def test_pass(self):
        raw = _make_story_raw(is_duplicate=False)
        result = _service()._check_not_duplicate(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail(self):
        raw = _make_story_raw(is_duplicate=True)
        result = _service()._check_not_duplicate(
            raw, _make_neutralized(), _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "duplicate" in result.reason


# ---------------------------------------------------------------------------
# D. View Completeness checks
# ---------------------------------------------------------------------------

class TestViewsRenderable:
    def test_pass_both_present(self):
        n = _make_neutralized(
            detail_brief="Some brief content.",
            detail_full="Some full content.",
        )
        result = _service()._check_views_renderable(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_pass_brief_only(self):
        n = _make_neutralized(
            detail_brief="Some brief content.",
            detail_full=None,
        )
        result = _service()._check_views_renderable(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_pass_full_only(self):
        n = _make_neutralized(
            detail_brief=None,
            detail_full="Some full content.",
        )
        result = _service()._check_views_renderable(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_neither(self):
        n = _make_neutralized(
            detail_brief=None,
            detail_full=None,
        )
        result = _service()._check_views_renderable(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "Neither" in result.reason

    def test_fail_both_empty_strings(self):
        n = _make_neutralized(
            detail_brief="",
            detail_full="   ",
        )
        result = _service()._check_views_renderable(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False

    def test_pass_manipulative_with_disclosure(self):
        n = _make_neutralized(
            has_manipulative_content=True,
            disclosure="Manipulative language removed.",
        )
        result = _service()._check_views_renderable(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is True

    def test_fail_manipulative_without_disclosure(self):
        n = _make_neutralized(
            has_manipulative_content=True,
            disclosure="",
        )
        result = _service()._check_views_renderable(
            _make_story_raw(), n, _make_source(), QCConfig()
        )
        assert result.passed is False
        assert "disclosure" in result.reason


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
        assert len(result.checks) == 13  # All 13 checks ran

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
        result = svc.check_article(
            _make_story_raw(), _make_neutralized(), _make_source()
        )
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

    def test_custom_values(self):
        config = QCConfig(
            min_detail_brief_words=25,
            max_feed_title_chars=100,
        )
        assert config.min_detail_brief_words == 25
        assert config.max_feed_title_chars == 100
        # Others still use defaults
        assert config.min_detail_full_words == 100
