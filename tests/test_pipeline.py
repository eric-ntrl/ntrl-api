# tests/test_pipeline.py
"""
Integration tests for the NTRL Pipeline.
"""

import pytest
from app.services.ntrl_pipeline import (
    NTRLPipeline,
    PipelineConfig,
    PipelineResult,
    ProcessingMode,
    process_article,
)
from app.services.ntrl_scan import ScannerConfig
from app.services.ntrl_fix import FixerConfig, GeneratorConfig


@pytest.fixture
def mock_pipeline():
    """Create pipeline with all mock providers."""
    config = PipelineConfig(
        mode=ProcessingMode.REALTIME,
        scanner_config=ScannerConfig(
            enable_lexical=True,
            enable_structural=True,
            enable_semantic=False,  # Skip semantic for speed
        ),
        fixer_config=FixerConfig(
            generator_config=GeneratorConfig(provider="mock"),
            strict_validation=False,
        ),
        enable_cache=True,
        generate_transparency=True,
    )
    return NTRLPipeline(config=config)


class TestPipelineInit:
    """Tests for pipeline initialization."""

    def test_default_config(self):
        """Should create pipeline with default config."""
        pipeline = NTRLPipeline()
        assert pipeline.config.mode == ProcessingMode.REALTIME
        assert pipeline.config.enable_cache is True

    def test_custom_config(self):
        """Should respect custom configuration."""
        config = PipelineConfig(
            mode=ProcessingMode.SCAN_ONLY,
            enable_cache=False,
        )
        pipeline = NTRLPipeline(config=config)
        assert pipeline.config.mode == ProcessingMode.SCAN_ONLY
        assert pipeline.config.enable_cache is False


class TestFullPipeline:
    """Tests for full pipeline processing."""

    @pytest.mark.asyncio
    async def test_process_detects_and_fixes(self, mock_pipeline):
        """Should detect manipulation and generate fixed content."""
        text = "BREAKING: Senator SLAMS critics in devastating attack."
        title = "BREAKING: Political News"

        result = await mock_pipeline.process(body=text, title=title)

        # Should have detections
        assert result.body_scan.total_detections > 0

        # Should have fixed content
        assert result.detail_full is not None
        assert len(result.detail_full) > 0

        # Mock should remove/replace manipulation
        assert "BREAKING" not in result.detail_full or "SLAMS" not in result.detail_full

        await mock_pipeline.close()

    @pytest.mark.asyncio
    async def test_process_empty_text(self, mock_pipeline):
        """Should handle empty text gracefully."""
        result = await mock_pipeline.process(body="", title="")

        assert result.detail_full == ""
        assert result.body_scan.total_detections == 0
        assert result.total_changes == 0

        await mock_pipeline.close()

    @pytest.mark.asyncio
    async def test_process_clean_text(self, mock_pipeline):
        """Should preserve clean text."""
        text = "The city council approved the budget amendment yesterday."

        result = await mock_pipeline.process(body=text, title="Council News")

        # Should have few or no detections
        assert result.body_scan.total_detections >= 0

        # Content should be similar to original
        assert len(result.detail_full) > 0

        await mock_pipeline.close()


class TestPipelineOutputs:
    """Tests for pipeline output fields."""

    @pytest.mark.asyncio
    async def test_all_outputs_present(self, mock_pipeline):
        """Should return all required output fields."""
        text = "BREAKING: Major announcement today."

        result = await mock_pipeline.process(body=text, title="News")

        # Check all fields present
        assert hasattr(result, 'original_body')
        assert hasattr(result, 'detail_full')
        assert hasattr(result, 'detail_brief')
        assert hasattr(result, 'feed_title')
        assert hasattr(result, 'feed_summary')
        assert hasattr(result, 'body_scan')
        assert hasattr(result, 'fix_result')
        assert hasattr(result, 'transparency')
        assert hasattr(result, 'total_processing_time_ms')

        await mock_pipeline.close()

    @pytest.mark.asyncio
    async def test_timing_recorded(self, mock_pipeline):
        """Should record processing times."""
        text = "Test article content."

        result = await mock_pipeline.process(body=text, title="Test")

        assert result.total_processing_time_ms >= 0
        assert result.scan_time_ms >= 0
        assert result.fix_time_ms >= 0

        await mock_pipeline.close()

    @pytest.mark.asyncio
    async def test_content_hash_generated(self, mock_pipeline):
        """Should generate content hash."""
        text = "Article content here."

        result = await mock_pipeline.process(body=text, title="Test")

        assert result.content_hash is not None
        assert len(result.content_hash) > 0

        await mock_pipeline.close()


class TestCaching:
    """Tests for caching functionality."""

    @pytest.mark.asyncio
    async def test_cache_hit(self, mock_pipeline):
        """Should return cached result on second call."""
        text = "BREAKING: Same article content."

        # First call
        result1 = await mock_pipeline.process(body=text, title="Test")
        assert result1.cache_hit is False

        # Second call (should be cached)
        result2 = await mock_pipeline.process(body=text, title="Test")
        assert result2.cache_hit is True

        await mock_pipeline.close()

    @pytest.mark.asyncio
    async def test_force_skip_cache(self, mock_pipeline):
        """Force should skip cache."""
        text = "Article for force test."

        # First call
        await mock_pipeline.process(body=text, title="Test")

        # Second call with force
        result = await mock_pipeline.process(body=text, title="Test", force=True)
        assert result.cache_hit is False

        await mock_pipeline.close()


class TestTransparency:
    """Tests for transparency package."""

    @pytest.mark.asyncio
    async def test_transparency_generated(self, mock_pipeline):
        """Should generate transparency package."""
        text = "BREAKING: Senator SLAMS opponent."

        result = await mock_pipeline.process(body=text, title="Test")

        assert result.transparency is not None
        assert hasattr(result.transparency, 'total_detections')
        assert hasattr(result.transparency, 'detections_by_category')
        assert hasattr(result.transparency, 'changes')
        assert hasattr(result.transparency, 'validation')

        await mock_pipeline.close()

    @pytest.mark.asyncio
    async def test_transparency_has_version(self, mock_pipeline):
        """Should include filter version."""
        text = "Test article."

        result = await mock_pipeline.process(body=text, title="Test")

        if result.transparency:
            assert result.transparency.filter_version is not None
            assert "2.0" in result.transparency.filter_version

        await mock_pipeline.close()


class TestScanOnly:
    """Tests for scan-only mode."""

    @pytest.mark.asyncio
    async def test_scan_only(self, mock_pipeline):
        """Should run detection without fixing."""
        text = "BREAKING: Test article."

        body_scan, title_scan = await mock_pipeline.scan_only(body=text, title="Test")

        assert body_scan is not None
        assert body_scan.total_detections >= 0

        await mock_pipeline.close()

    @pytest.mark.asyncio
    async def test_scan_only_mode_config(self):
        """Scan-only mode should not run fixer."""
        config = PipelineConfig(
            mode=ProcessingMode.SCAN_ONLY,
            scanner_config=ScannerConfig(enable_semantic=False),
        )
        pipeline = NTRLPipeline(config=config)

        text = "BREAKING: Test article."
        result = await pipeline.process(body=text, title="Test")

        # Should have scans but no fix
        assert result.body_scan is not None
        assert result.fix_result is None
        assert result.detail_full == text  # Original returned

        await pipeline.close()


class TestValidation:
    """Tests for validation results."""

    @pytest.mark.asyncio
    async def test_validation_included(self, mock_pipeline):
        """Should include validation results."""
        text = "The company reported $5 million in revenue."

        result = await mock_pipeline.process(body=text, title="Test")

        assert result.passed_validation is not None

        await mock_pipeline.close()


class TestConvenienceFunction:
    """Tests for process_article convenience function."""

    @pytest.mark.asyncio
    async def test_process_article_basic(self):
        """process_article should work with defaults."""
        config = PipelineConfig(
            scanner_config=ScannerConfig(enable_semantic=False),
            fixer_config=FixerConfig(
                generator_config=GeneratorConfig(provider="mock"),
            ),
        )

        result = await process_article(
            body="BREAKING: Test article.",
            title="Test",
            config=config,
        )

        assert result.detail_full is not None


class TestCleanup:
    """Tests for resource cleanup."""

    @pytest.mark.asyncio
    async def test_close_pipeline(self, mock_pipeline):
        """Should close without error."""
        await mock_pipeline.close()
        # Should be able to call close multiple times
        await mock_pipeline.close()
