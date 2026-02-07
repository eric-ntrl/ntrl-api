# tests/test_batcher.py
"""
Integration tests for the NTRL Batcher.
"""

import pytest

from app.services.ntrl_batcher import (
    ArticleInput,
    BatchConfig,
    NTRLBatcher,
    process_articles,
)
from app.services.ntrl_fix import FixerConfig, GeneratorConfig
from app.services.ntrl_pipeline import PipelineConfig
from app.services.ntrl_scan import ScannerConfig


@pytest.fixture
def mock_batcher():
    """Create batcher with mock providers."""
    pipeline_config = PipelineConfig(
        scanner_config=ScannerConfig(
            enable_semantic=False,
        ),
        fixer_config=FixerConfig(
            generator_config=GeneratorConfig(provider="mock"),
            strict_validation=False,
        ),
    )
    batch_config = BatchConfig(
        max_concurrent=3,
        chunk_size=2,
        per_article_timeout=10.0,
    )
    return NTRLBatcher(
        pipeline_config=pipeline_config,
        batch_config=batch_config,
    )


def make_article(article_id: str, manipulation: bool = True) -> ArticleInput:
    """Create test article input."""
    if manipulation:
        body = f"BREAKING: Article {article_id} with SHOCKING news."
        title = f"BREAKING: Title {article_id}"
    else:
        body = f"Article {article_id} contains normal news content."
        title = f"Title {article_id}"

    return ArticleInput(
        article_id=article_id,
        body=body,
        title=title,
    )


class TestBatcherInit:
    """Tests for batcher initialization."""

    def test_default_config(self):
        """Should create batcher with default config."""
        batcher = NTRLBatcher()
        assert batcher.batch_config.max_concurrent == 5
        assert batcher.batch_config.chunk_size == 4

    def test_custom_config(self):
        """Should respect custom configuration."""
        config = BatchConfig(max_concurrent=10, chunk_size=5)
        batcher = NTRLBatcher(batch_config=config)
        assert batcher.batch_config.max_concurrent == 10
        assert batcher.batch_config.chunk_size == 5


class TestSingleArticle:
    """Tests for single article processing."""

    @pytest.mark.asyncio
    async def test_process_one(self, mock_batcher):
        """Should process single article."""
        article = make_article("test-1")

        result = await mock_batcher.process_one(article)

        assert result is not None
        assert result.detail_full is not None
        assert len(result.detail_full) > 0

        await mock_batcher.close()


class TestBatchProcessing:
    """Tests for batch processing."""

    @pytest.mark.asyncio
    async def test_batch_empty(self, mock_batcher):
        """Should handle empty batch."""
        result = await mock_batcher.process_batch([])

        assert result.total_articles == 0
        assert result.successful == 0
        assert result.failed == 0

        await mock_batcher.close()

    @pytest.mark.asyncio
    async def test_batch_single(self, mock_batcher):
        """Should handle single-item batch."""
        articles = [make_article("batch-1")]

        result = await mock_batcher.process_batch(articles)

        assert result.total_articles == 1
        assert result.successful == 1
        assert result.failed == 0
        assert "batch-1" in result.results

        await mock_batcher.close()

    @pytest.mark.asyncio
    async def test_batch_small(self, mock_batcher):
        """Should process small batch in parallel."""
        articles = [make_article(f"small-{i}") for i in range(3)]

        result = await mock_batcher.process_batch(articles)

        assert result.total_articles == 3
        assert result.successful == 3
        assert result.failed == 0

        # All results should be present
        for article in articles:
            assert article.article_id in result.results

        await mock_batcher.close()

    @pytest.mark.asyncio
    async def test_batch_large(self, mock_batcher):
        """Should process large batch in chunks."""
        articles = [make_article(f"large-{i}") for i in range(8)]

        result = await mock_batcher.process_batch(articles)

        assert result.total_articles == 8
        assert result.successful == 8
        assert result.failed == 0

        await mock_batcher.close()


class TestBatchMetrics:
    """Tests for batch metrics."""

    @pytest.mark.asyncio
    async def test_timing_recorded(self, mock_batcher):
        """Should record timing metrics."""
        articles = [make_article(f"timing-{i}") for i in range(2)]

        result = await mock_batcher.process_batch(articles)

        assert result.total_time_ms > 0
        assert result.avg_time_per_article_ms > 0

        await mock_batcher.close()


class TestConvenienceFunction:
    """Tests for process_articles convenience function."""

    @pytest.mark.asyncio
    async def test_process_articles_basic(self):
        """process_articles should work with defaults."""
        config = PipelineConfig(
            scanner_config=ScannerConfig(enable_semantic=False),
            fixer_config=FixerConfig(
                generator_config=GeneratorConfig(provider="mock"),
            ),
        )

        articles = [
            ArticleInput(article_id="conv-1", body="Test article.", title="Test"),
        ]

        result = await process_articles(articles, config=config)

        assert result.total_articles == 1
        assert result.successful == 1


class TestCleanup:
    """Tests for resource cleanup."""

    @pytest.mark.asyncio
    async def test_close_batcher(self, mock_batcher):
        """Should close without error."""
        await mock_batcher.close()
        # Should be able to call close multiple times
        await mock_batcher.close()
