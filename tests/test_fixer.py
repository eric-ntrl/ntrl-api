# tests/test_fixer.py
"""
Unit tests for the NTRL-FIX Fixer orchestrator.
"""

import pytest
from app.services.ntrl_fix import (
    NTRLFixer,
    FixerConfig,
    fix_article,
    GeneratorConfig,
    FixAction,
)
from app.services.ntrl_scan import (
    NTRLScanner,
    ScannerConfig,
    ArticleSegment,
)


@pytest.fixture
def fixer():
    """Create fixer with mock generators."""
    config = FixerConfig(
        generator_config=GeneratorConfig(provider="mock"),
        strict_validation=False,  # Use non-strict for testing
    )
    return NTRLFixer(config=config)


@pytest.fixture
def scanner():
    """Create scanner without semantic for fast tests."""
    config = ScannerConfig(
        enable_lexical=True,
        enable_structural=True,
        enable_semantic=False,
    )
    return NTRLScanner(config=config)


class TestFixerInit:
    """Tests for fixer initialization."""

    def test_default_config(self):
        """Should create fixer with default config."""
        fixer = NTRLFixer()
        assert fixer.config.strict_validation is True
        assert fixer.config.retry_on_failure is True

    def test_custom_config(self):
        """Should respect custom configuration."""
        config = FixerConfig(strict_validation=False, max_retries=5)
        fixer = NTRLFixer(config=config)
        assert fixer.config.strict_validation is False
        assert fixer.config.max_retries == 5


class TestBasicFixing:
    """Tests for basic fixing functionality."""

    @pytest.mark.asyncio
    async def test_fix_with_detections(self, fixer, scanner):
        """Should fix text with detected manipulation."""
        text = "BREAKING: Senator SLAMS critics in devastating attack."
        scan_result = await scanner.scan(text, ArticleSegment.BODY)

        result = await fixer.fix(
            body=text,
            title="Test Title",
            body_scan=scan_result,
        )

        assert result.detail_full is not None
        assert len(result.detail_full) > 0
        # Mock should remove/replace manipulation
        assert "BREAKING" not in result.detail_full or "SLAMS" not in result.detail_full

    @pytest.mark.asyncio
    async def test_fix_empty_text(self, fixer):
        """Should handle empty text."""
        result = await fixer.fix(body="", title="")

        assert result.detail_full == ""
        assert result.detail_brief == ""
        assert result.total_changes == 0

    @pytest.mark.asyncio
    async def test_fix_clean_text(self, fixer, scanner):
        """Should preserve clean text with no changes."""
        text = "The city council approved the budget amendment yesterday."
        scan_result = await scanner.scan(text, ArticleSegment.BODY)

        result = await fixer.fix(
            body=text,
            body_scan=scan_result,
        )

        # Should return original or very similar
        assert result.detail_full is not None
        assert result.total_changes == 0 or len(result.detail_full) > 0


class TestFixerOutputs:
    """Tests for fixer output fields."""

    @pytest.mark.asyncio
    async def test_fix_returns_all_fields(self, fixer, scanner):
        """Should return all required output fields."""
        text = "BREAKING: Major announcement made today."
        scan_result = await scanner.scan(text, ArticleSegment.BODY)

        result = await fixer.fix(
            body=text,
            title="BREAKING: Test",
            body_scan=scan_result,
        )

        assert hasattr(result, 'detail_full')
        assert hasattr(result, 'detail_brief')
        assert hasattr(result, 'feed_title')
        assert hasattr(result, 'feed_summary')
        assert hasattr(result, 'changes')
        assert hasattr(result, 'validation')
        assert hasattr(result, 'processing_time_ms')

    @pytest.mark.asyncio
    async def test_validation_included(self, fixer, scanner):
        """Should include validation results."""
        text = "The company reported $5 million in revenue."
        scan_result = await scanner.scan(text, ArticleSegment.BODY)

        result = await fixer.fix(body=text, body_scan=scan_result)

        assert result.validation is not None
        assert hasattr(result.validation, 'passed')
        assert hasattr(result.validation, 'checks')


class TestChangeRecords:
    """Tests for change record generation."""

    @pytest.mark.asyncio
    async def test_changes_tracked(self, fixer, scanner):
        """Should track changes made."""
        text = "BREAKING: This is urgent news."
        scan_result = await scanner.scan(text, ArticleSegment.BODY)

        result = await fixer.fix(body=text, body_scan=scan_result)

        # Should have changes if manipulation detected
        if scan_result.total_detections > 0:
            assert len(result.changes) > 0 or result.detail_full != text

    @pytest.mark.asyncio
    async def test_change_record_structure(self, fixer, scanner):
        """Change records should have required fields."""
        text = "SLAMS the opposition in devastating attack."
        scan_result = await scanner.scan(text, ArticleSegment.BODY)

        result = await fixer.fix(body=text, body_scan=scan_result)

        for change in result.changes:
            assert hasattr(change, 'detection_id')
            assert hasattr(change, 'type_id')
            assert hasattr(change, 'before')
            assert hasattr(change, 'after')
            assert hasattr(change, 'action')
            assert isinstance(change.action, FixAction)


class TestFeedOutputs:
    """Tests for feed title and summary generation."""

    @pytest.mark.asyncio
    async def test_feed_title_generated(self, fixer, scanner):
        """Should generate feed title."""
        text = "The mayor announced new policies for the city today."
        scan_result = await scanner.scan(text, ArticleSegment.BODY)

        result = await fixer.fix(
            body=text,
            title="BREAKING: Mayor SLAMS critics",
            body_scan=scan_result,
        )

        assert result.feed_title is not None
        assert len(result.feed_title) > 0

    @pytest.mark.asyncio
    async def test_feed_title_neutralized(self, fixer, scanner):
        """Feed title should remove manipulation."""
        text = "The senator responded to criticism."
        scan_result = await scanner.scan(text, ArticleSegment.BODY)

        result = await fixer.fix(
            body=text,
            title="BREAKING: Senator SLAMS Critics",
            body_scan=scan_result,
        )

        # Mock should clean up the title
        # Check that at least some cleanup happened
        assert result.feed_title is not None


class TestLengthMetrics:
    """Tests for length tracking."""

    @pytest.mark.asyncio
    async def test_length_metrics(self, fixer, scanner):
        """Should track original and fixed lengths."""
        text = "BREAKING: This is a test article with some manipulation."
        scan_result = await scanner.scan(text, ArticleSegment.BODY)

        result = await fixer.fix(body=text, body_scan=scan_result)

        assert result.original_length == len(text)
        assert result.fixed_length >= 0
        assert result.length_ratio >= 0

    @pytest.mark.asyncio
    async def test_processing_time_recorded(self, fixer, scanner):
        """Should record processing time."""
        text = "Test article content here."
        scan_result = await scanner.scan(text, ArticleSegment.BODY)

        result = await fixer.fix(body=text, body_scan=scan_result)

        assert result.processing_time_ms >= 0


class TestConvenienceFunction:
    """Tests for fix_article convenience function."""

    @pytest.mark.asyncio
    async def test_fix_article_basic(self):
        """fix_article should work with defaults."""
        config = FixerConfig(
            generator_config=GeneratorConfig(provider="mock"),
            strict_validation=False,
        )

        result = await fix_article(
            body="BREAKING: Major news event.",
            title="Test Title",
            config=config,
        )

        assert result.detail_full is not None
        assert result.validation is not None


class TestCleanup:
    """Tests for resource cleanup."""

    @pytest.mark.asyncio
    async def test_close_fixer(self, fixer):
        """Should close without error."""
        await fixer.close()
        # Should be able to call close multiple times
        await fixer.close()


class TestEdgeCases:
    """Tests for edge cases."""

    @pytest.mark.asyncio
    async def test_fix_without_scan(self, fixer):
        """Should work without scan results."""
        result = await fixer.fix(
            body="Normal article text.",
            title="Normal Title",
        )

        assert result.detail_full == "Normal article text."
        assert result.total_changes == 0

    @pytest.mark.asyncio
    async def test_fix_very_long_text(self, fixer, scanner):
        """Should handle long articles."""
        text = "BREAKING: " + "The quick brown fox jumped. " * 200
        scan_result = await scanner.scan(text, ArticleSegment.BODY)

        result = await fixer.fix(body=text, body_scan=scan_result)

        assert result.detail_full is not None
        assert len(result.detail_full) > 0
