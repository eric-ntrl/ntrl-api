# app/services/ntrl_batcher.py
"""
NTRL Batcher: Adaptive batching for article processing.

Provides efficient batch processing for background jobs while maintaining
low latency for real-time requests.

Strategies:
- Real-time (1 article): Process immediately, lowest latency
- Small batch (2-4 articles): Parallel processing
- Large batch (5+ articles): Chunked parallel processing with rate limiting

Target throughput: 10-20 articles per second in batch mode
"""

import asyncio
import time
from dataclasses import dataclass, field

from .ntrl_pipeline import (
    NTRLPipeline,
    PipelineConfig,
    PipelineResult,
)


@dataclass
class BatchConfig:
    """Configuration for batch processing."""

    # Batch sizing
    max_concurrent: int = 5  # Max parallel articles
    chunk_size: int = 4  # Articles per chunk in large batches

    # Rate limiting
    rate_limit_per_second: float = 20.0  # Max articles per second
    rate_limit_burst: int = 10  # Burst allowance

    # Timeouts
    per_article_timeout: float = 30.0  # Timeout per article
    batch_timeout: float = 300.0  # Total batch timeout (5 min)

    # Retry settings
    max_retries: int = 2
    retry_delay: float = 1.0


@dataclass
class ArticleInput:
    """Input for batch processing."""

    article_id: str
    body: str
    title: str = ""
    deck: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class BatchResult:
    """Result from batch processing."""

    results: dict[str, PipelineResult]  # article_id -> result
    failures: dict[str, str]  # article_id -> error message
    total_articles: int
    successful: int
    failed: int
    total_time_ms: float
    avg_time_per_article_ms: float


class NTRLBatcher:
    """
    Adaptive batcher for article processing.

    Automatically selects optimal processing strategy based on batch size.

    Usage:
        batcher = NTRLBatcher()

        # Single article (real-time)
        result = await batcher.process_one(article)

        # Batch processing
        results = await batcher.process_batch(articles)
    """

    def __init__(
        self,
        pipeline_config: PipelineConfig | None = None,
        batch_config: BatchConfig | None = None,
    ):
        """Initialize batcher with configurations."""
        self.pipeline_config = pipeline_config or PipelineConfig()
        self.batch_config = batch_config or BatchConfig()

        # Create pipeline instance
        self._pipeline: NTRLPipeline | None = None

        # Rate limiting state
        self._last_request_time: float = 0
        self._request_count: int = 0
        self._rate_limit_lock = asyncio.Lock()

    @property
    def pipeline(self) -> NTRLPipeline:
        """Get pipeline instance."""
        if self._pipeline is None:
            self._pipeline = NTRLPipeline(config=self.pipeline_config)
        return self._pipeline

    async def process_one(
        self,
        article: ArticleInput,
        force: bool = False,
    ) -> PipelineResult:
        """
        Process a single article (real-time mode).

        Args:
            article: Article to process
            force: Force reprocessing even if cached

        Returns:
            PipelineResult for the article
        """
        return await self.pipeline.process(
            body=article.body,
            title=article.title,
            deck=article.deck,
            force=force,
        )

    async def process_batch(
        self,
        articles: list[ArticleInput],
        force: bool = False,
    ) -> BatchResult:
        """
        Process a batch of articles.

        Automatically selects optimal strategy based on batch size.

        Args:
            articles: List of articles to process
            force: Force reprocessing even if cached

        Returns:
            BatchResult with all results and failures
        """
        start_time = time.perf_counter()

        if not articles:
            return BatchResult(
                results={},
                failures={},
                total_articles=0,
                successful=0,
                failed=0,
                total_time_ms=0.0,
                avg_time_per_article_ms=0.0,
            )

        # Select strategy based on batch size
        if len(articles) == 1:
            results, failures = await self._process_single(articles[0], force)
        elif len(articles) <= self.batch_config.max_concurrent:
            results, failures = await self._process_parallel(articles, force)
        else:
            results, failures = await self._process_chunked(articles, force)

        total_time_ms = (time.perf_counter() - start_time) * 1000
        successful = len(results)
        failed = len(failures)

        avg_time = total_time_ms / len(articles) if articles else 0

        return BatchResult(
            results=results,
            failures=failures,
            total_articles=len(articles),
            successful=successful,
            failed=failed,
            total_time_ms=round(total_time_ms, 2),
            avg_time_per_article_ms=round(avg_time, 2),
        )

    async def _process_single(
        self, article: ArticleInput, force: bool
    ) -> tuple[dict[str, PipelineResult], dict[str, str]]:
        """Process a single article."""
        results = {}
        failures = {}

        try:
            result = await self.process_one(article, force)
            results[article.article_id] = result
        except Exception as e:
            failures[article.article_id] = str(e)

        return results, failures

    async def _process_parallel(
        self, articles: list[ArticleInput], force: bool
    ) -> tuple[dict[str, PipelineResult], dict[str, str]]:
        """Process articles in parallel (small batch)."""
        results = {}
        failures = {}

        # Create tasks for all articles
        tasks = []
        for article in articles:
            task = asyncio.create_task(self._process_with_retry(article, force))
            tasks.append((article.article_id, task))

        # Wait for all with timeout
        try:
            done, pending = await asyncio.wait([t for _, t in tasks], timeout=self.batch_config.batch_timeout)

            # Cancel pending
            for task in pending:
                task.cancel()

            # Collect results
            for article_id, task in tasks:
                if task in done:
                    try:
                        result = task.result()
                        if isinstance(result, PipelineResult):
                            results[article_id] = result
                        else:
                            failures[article_id] = str(result)
                    except Exception as e:
                        failures[article_id] = str(e)
                else:
                    failures[article_id] = "Timeout"

        except Exception as e:
            # On any error, mark all remaining as failed
            for article in articles:
                if article.article_id not in results:
                    failures[article.article_id] = str(e)

        return results, failures

    async def _process_chunked(
        self, articles: list[ArticleInput], force: bool
    ) -> tuple[dict[str, PipelineResult], dict[str, str]]:
        """Process articles in chunks (large batch)."""
        all_results = {}
        all_failures = {}

        # Split into chunks
        chunks = [
            articles[i : i + self.batch_config.chunk_size]
            for i in range(0, len(articles), self.batch_config.chunk_size)
        ]

        for chunk in chunks:
            # Apply rate limiting between chunks
            await self._rate_limit()

            # Process chunk in parallel
            results, failures = await self._process_parallel(chunk, force)
            all_results.update(results)
            all_failures.update(failures)

        return all_results, all_failures

    async def _process_with_retry(self, article: ArticleInput, force: bool) -> PipelineResult:
        """Process article with retry logic."""
        last_error = None

        for attempt in range(self.batch_config.max_retries + 1):
            try:
                # Apply rate limiting
                await self._rate_limit()

                # Process with timeout
                result = await asyncio.wait_for(
                    self.process_one(article, force), timeout=self.batch_config.per_article_timeout
                )
                return result

            except TimeoutError:
                last_error = "Timeout"
            except Exception as e:
                last_error = str(e)

            # Wait before retry
            if attempt < self.batch_config.max_retries:
                await asyncio.sleep(self.batch_config.retry_delay)

        raise Exception(f"Failed after {self.batch_config.max_retries + 1} attempts: {last_error}")

    async def _rate_limit(self):
        """Apply rate limiting."""
        async with self._rate_limit_lock:
            now = time.time()

            # Reset counter if enough time has passed
            if now - self._last_request_time > 1.0:
                self._request_count = 0
                self._last_request_time = now

            # Check if we need to wait
            if self._request_count >= self.batch_config.rate_limit_per_second:
                wait_time = 1.0 - (now - self._last_request_time)
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                self._request_count = 0
                self._last_request_time = time.time()

            self._request_count += 1

    async def close(self):
        """Clean up resources."""
        if self._pipeline:
            await self._pipeline.close()


# Convenience functions
async def process_articles(
    articles: list[ArticleInput],
    config: PipelineConfig | None = None,
) -> BatchResult:
    """
    Convenience function to process a batch of articles.

    Args:
        articles: List of articles to process
        config: Optional pipeline configuration

    Returns:
        BatchResult with all results
    """
    batcher = NTRLBatcher(pipeline_config=config)
    try:
        return await batcher.process_batch(articles)
    finally:
        await batcher.close()
