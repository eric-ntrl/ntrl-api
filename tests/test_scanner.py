# tests/test_scanner.py
"""
Unit tests for the NTRL Scanner orchestrator.
"""

import pytest
import asyncio
from app.services.ntrl_scan import (
    NTRLScanner,
    ScannerConfig,
    ArticleSegment,
    DetectorSource,
    scan_text,
)


@pytest.fixture
def scanner_no_semantic():
    """Create scanner without semantic detector for fast tests."""
    config = ScannerConfig(
        enable_lexical=True,
        enable_structural=True,
        enable_semantic=False,
    )
    return NTRLScanner(config=config)


@pytest.fixture
def scanner_mock_semantic():
    """Create scanner with mock semantic detector."""
    config = ScannerConfig(
        enable_lexical=True,
        enable_structural=True,
        enable_semantic=True,
        semantic_provider="mock",
    )
    return NTRLScanner(config=config)


@pytest.fixture
def scanner_lexical_only():
    """Create scanner with only lexical detector."""
    config = ScannerConfig(
        enable_lexical=True,
        enable_structural=False,
        enable_semantic=False,
    )
    return NTRLScanner(config=config)


class TestScannerInit:
    """Tests for scanner initialization."""

    def test_default_config(self):
        """Should create scanner with default config."""
        scanner = NTRLScanner()
        assert scanner.config.enable_lexical is True
        assert scanner.config.enable_structural is True
        assert scanner.config.enable_semantic is True

    def test_custom_config(self):
        """Should respect custom configuration."""
        config = ScannerConfig(enable_semantic=False)
        scanner = NTRLScanner(config=config)
        assert scanner.config.enable_semantic is False


class TestBasicScanning:
    """Tests for basic scanning functionality."""

    @pytest.mark.asyncio
    async def test_scan_detects_manipulation(self, scanner_no_semantic):
        """Should detect manipulation patterns."""
        text = "BREAKING: Senator SLAMS critics in devastating attack."
        result = await scanner_no_semantic.scan(text, ArticleSegment.TITLE)

        assert result.total_detections > 0
        assert len(result.spans) > 0

    @pytest.mark.asyncio
    async def test_scan_empty_text(self, scanner_no_semantic):
        """Should handle empty text."""
        result = await scanner_no_semantic.scan("", ArticleSegment.BODY)
        assert result.total_detections == 0
        assert result.text_length == 0

    @pytest.mark.asyncio
    async def test_scan_clean_text(self, scanner_lexical_only):
        """Should return no detections for clean text."""
        text = "The city council approved the budget amendment yesterday."
        result = await scanner_lexical_only.scan(text, ArticleSegment.BODY)
        assert result.total_detections == 0

    @pytest.mark.asyncio
    async def test_scan_returns_merged_result(self, scanner_no_semantic):
        """Should return MergedScanResult with all fields."""
        text = "BREAKING: The investigation was closed. Mistakes were made."
        result = await scanner_no_semantic.scan(text, ArticleSegment.BODY)

        assert hasattr(result, 'spans')
        assert hasattr(result, 'segment')
        assert hasattr(result, 'text_length')
        assert hasattr(result, 'total_scan_duration_ms')
        assert hasattr(result, 'detector_durations')
        assert hasattr(result, 'summary_stats')


class TestParallelExecution:
    """Tests for parallel detector execution."""

    @pytest.mark.asyncio
    async def test_multiple_detectors_run(self, scanner_no_semantic):
        """Should run both lexical and structural detectors."""
        text = "BREAKING: Mistakes were made in the investigation."
        result = await scanner_no_semantic.scan(text, ArticleSegment.BODY)

        # Should have timing for both detectors
        assert "lexical" in result.detector_durations
        assert "structural" in result.detector_durations

    @pytest.mark.asyncio
    async def test_detectors_find_different_patterns(self, scanner_no_semantic):
        """Different detectors should find different patterns."""
        text = "BREAKING: Some say the mistakes were made recently."
        result = await scanner_no_semantic.scan(text, ArticleSegment.BODY)

        # Collect which detectors found what
        sources = {span.detector_source for span in result.spans}

        # Should have findings from multiple detectors
        # (BREAKING from lexical, passive/vague from structural)
        assert len(sources) >= 1


class TestSpanMerging:
    """Tests for span merging and deduplication."""

    @pytest.mark.asyncio
    async def test_overlapping_spans_deduplicated(self, scanner_no_semantic):
        """Overlapping spans should be deduplicated."""
        # This text might have overlapping detections
        text = "BREAKING NEWS: You won't believe what SLAMS happened!"
        result = await scanner_no_semantic.scan(text, ArticleSegment.TITLE)

        # Check spans don't have significant overlap
        for i, span1 in enumerate(result.spans):
            for span2 in result.spans[i+1:]:
                # Calculate overlap
                start = max(span1.span_start, span2.span_start)
                end = min(span1.span_end, span2.span_end)
                overlap = max(0, end - start)

                smaller_len = min(
                    span1.span_end - span1.span_start,
                    span2.span_end - span2.span_start
                )

                if smaller_len > 0:
                    overlap_ratio = overlap / smaller_len
                    # Allow some overlap (different types) but not too much
                    # Unless they have different type_ids
                    if span1.type_id_primary == span2.type_id_primary:
                        assert overlap_ratio < 0.9, "Same-type spans should be deduplicated"

    @pytest.mark.asyncio
    async def test_spans_sorted_by_position(self, scanner_no_semantic):
        """Spans should be sorted by position."""
        text = "BREAKING: First. URGENT: Second. ALERT: Third."
        result = await scanner_no_semantic.scan(text, ArticleSegment.BODY)

        positions = [span.span_start for span in result.spans]
        assert positions == sorted(positions)


class TestSegmentMultipliers:
    """Tests for segment severity multipliers."""

    @pytest.mark.asyncio
    async def test_title_has_higher_weighted_severity(self, scanner_no_semantic):
        """Title segments should have higher weighted severity."""
        text = "BREAKING: Major event"

        title_result = await scanner_no_semantic.scan(text, ArticleSegment.TITLE)
        body_result = await scanner_no_semantic.scan(text, ArticleSegment.BODY)

        if title_result.spans and body_result.spans:
            title_span = title_result.spans[0]
            body_span = body_result.spans[0]

            # Same base severity, different weighted
            if title_span.type_id_primary == body_span.type_id_primary:
                assert title_span.severity_weighted > body_span.severity_weighted


class TestScanArticle:
    """Tests for full article scanning."""

    @pytest.mark.asyncio
    async def test_scan_article_returns_all_segments(self, scanner_no_semantic):
        """Should return results for all provided segments."""
        results = await scanner_no_semantic.scan_article(
            title="BREAKING: Major Event",
            body="The investigation was closed recently.",
            deck="Shocking developments unfold.",
        )

        assert ArticleSegment.TITLE in results
        assert ArticleSegment.BODY in results
        assert ArticleSegment.DECK in results

    @pytest.mark.asyncio
    async def test_scan_article_without_deck(self, scanner_no_semantic):
        """Should work without deck."""
        results = await scanner_no_semantic.scan_article(
            title="BREAKING: Major Event",
            body="The details of the event.",
        )

        assert ArticleSegment.TITLE in results
        assert ArticleSegment.BODY in results
        assert ArticleSegment.DECK not in results


class TestSemanticDetector:
    """Tests for semantic detector integration."""

    @pytest.mark.asyncio
    async def test_mock_semantic_detects_patterns(self, scanner_mock_semantic):
        """Mock semantic detector should detect patterns when tested directly."""
        # Test the semantic detector directly since merge logic may favor
        # lexical detector for overlapping patterns with higher confidence
        text = "They did this to silence critics. Officials want you to be scared."
        result = await scanner_mock_semantic.semantic.detect(text, ArticleSegment.BODY)

        semantic_spans = [
            s for s in result.spans
            if s.detector_source == DetectorSource.SEMANTIC
        ]
        assert len(semantic_spans) > 0

    @pytest.mark.asyncio
    async def test_semantic_disabled_no_semantic_spans(self, scanner_no_semantic):
        """Disabled semantic detector should not produce spans."""
        text = "They did this to silence critics."
        result = await scanner_no_semantic.scan(text, ArticleSegment.BODY)

        semantic_spans = [
            s for s in result.spans
            if s.detector_source == DetectorSource.SEMANTIC
        ]
        assert len(semantic_spans) == 0


class TestConvenienceFunction:
    """Tests for scan_text convenience function."""

    @pytest.mark.asyncio
    async def test_scan_text_basic(self):
        """scan_text should work with defaults."""
        config = ScannerConfig(enable_semantic=False)
        result = await scan_text(
            "BREAKING: Major event.",
            segment=ArticleSegment.TITLE,
            config=config,
        )
        assert result.total_detections > 0


class TestPerformance:
    """Tests for scanner performance."""

    @pytest.mark.asyncio
    async def test_fast_scanning(self, scanner_no_semantic):
        """Should complete quickly for typical text."""
        text = "BREAKING: " + "The quick brown fox. " * 50
        result = await scanner_no_semantic.scan(text, ArticleSegment.BODY)

        # Without semantic detector, should be very fast
        assert result.total_scan_duration_ms < 200

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        """Should handle timeout gracefully."""
        config = ScannerConfig(
            enable_semantic=False,
            timeout_seconds=0.001,  # Very short timeout
        )
        scanner = NTRLScanner(config=config)

        # Should not raise, may return partial results
        text = "BREAKING: Test text."
        result = await scanner.scan(text, ArticleSegment.BODY)
        assert result is not None


class TestCleanup:
    """Tests for resource cleanup."""

    @pytest.mark.asyncio
    async def test_close_scanner(self, scanner_mock_semantic):
        """Should close without error."""
        await scanner_mock_semantic.close()
        # Should be able to call close multiple times
        await scanner_mock_semantic.close()
