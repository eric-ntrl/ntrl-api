"""
Robust article body extraction with retries and fallback extractors.

This module provides a hardened body extraction service that:
- Retries failed downloads with exponential backoff (3 attempts: 1s, 2s, 4s)
- Falls back to newspaper3k when trafilatura fails
- Tracks detailed failure reasons for observability
"""

import configparser
import logging
import time
from dataclasses import dataclass
from enum import Enum

import trafilatura
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class ExtractionFailureReason(str, Enum):
    """Categorized failure reasons for observability."""

    DOWNLOAD_FAILED = "download_failed"
    EXTRACTION_FAILED = "extraction_failed"
    CONTENT_TOO_SHORT = "content_too_short"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class ExtractionResult:
    """Result of a body extraction attempt with detailed metadata."""

    success: bool
    body: str | None = None
    char_count: int = 0
    failure_reason: ExtractionFailureReason | None = None
    attempts: int = 1
    duration_ms: int = 0
    extractor_used: str = "trafilatura"  # "trafilatura" or "newspaper3k"


class BodyExtractor:
    """Extract article body with retries, fallback extractors, and detailed failure tracking."""

    MIN_BODY_LENGTH = 100
    TIMEOUT_SECONDS = 15

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((TimeoutError, ConnectionError, OSError)),
        reraise=True,
    )
    def _fetch_with_retry(self, url: str) -> str | None:
        """Fetch URL content with retries on network errors."""
        config = configparser.ConfigParser()
        config.read_dict(
            {
                "DEFAULT": {
                    "DOWNLOAD_TIMEOUT": str(self.TIMEOUT_SECONDS),
                }
            }
        )
        return trafilatura.fetch_url(url, config=config)

    def _try_newspaper3k(self, url: str) -> str | None:
        """Fallback extractor using newspaper3k."""
        try:
            from newspaper import Article

            article = Article(url)
            article.download()
            article.parse()
            if article.text and len(article.text) >= self.MIN_BODY_LENGTH:
                logger.debug(f"newspaper3k extracted {len(article.text)} chars from {url}")
                return article.text
        except Exception as e:
            logger.debug(f"newspaper3k fallback failed for {url}: {e}")
        return None

    def extract(self, url: str) -> ExtractionResult:
        """
        Extract article body with retries, fallback, and detailed failure tracking.

        Extraction flow:
        1. Try trafilatura with 3 retries (exponential backoff: 1s, 2s, 4s)
        2. If trafilatura fails to download or extract, try newspaper3k
        3. Return detailed result with failure reason if all attempts fail
        """
        start_time = time.time()
        attempts = 0
        extractor_used = "trafilatura"

        try:
            attempts = 1
            downloaded = self._fetch_with_retry(url)

            if not downloaded:
                # Try newspaper3k fallback for download failure
                logger.warning(f"trafilatura download failed for {url}, trying newspaper3k")
                text = self._try_newspaper3k(url)
                if text:
                    extractor_used = "newspaper3k"
                    return ExtractionResult(
                        success=True,
                        body=text,
                        char_count=len(text),
                        attempts=attempts,
                        duration_ms=int((time.time() - start_time) * 1000),
                        extractor_used=extractor_used,
                    )
                return ExtractionResult(
                    success=False,
                    failure_reason=ExtractionFailureReason.DOWNLOAD_FAILED,
                    attempts=attempts,
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            text = trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )

            # If trafilatura extraction fails or content too short, try newspaper3k
            if not text or len(text) < self.MIN_BODY_LENGTH:
                logger.debug(
                    f"trafilatura extraction insufficient ({len(text) if text else 0} chars), trying newspaper3k"
                )
                fallback_text = self._try_newspaper3k(url)
                if fallback_text:
                    extractor_used = "newspaper3k"
                    return ExtractionResult(
                        success=True,
                        body=fallback_text,
                        char_count=len(fallback_text),
                        attempts=attempts,
                        duration_ms=int((time.time() - start_time) * 1000),
                        extractor_used=extractor_used,
                    )

            if not text:
                return ExtractionResult(
                    success=False,
                    failure_reason=ExtractionFailureReason.EXTRACTION_FAILED,
                    attempts=attempts,
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            if len(text) < self.MIN_BODY_LENGTH:
                return ExtractionResult(
                    success=False,
                    body=text,
                    char_count=len(text),
                    failure_reason=ExtractionFailureReason.CONTENT_TOO_SHORT,
                    attempts=attempts,
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            logger.debug(f"trafilatura extracted {len(text)} chars from {url}")
            return ExtractionResult(
                success=True,
                body=text,
                char_count=len(text),
                attempts=attempts,
                duration_ms=int((time.time() - start_time) * 1000),
                extractor_used=extractor_used,
            )

        except Exception as e:
            logger.warning(f"All trafilatura attempts failed for {url}: {e}")
            # Last resort: try newspaper3k
            fallback_text = self._try_newspaper3k(url)
            if fallback_text:
                return ExtractionResult(
                    success=True,
                    body=fallback_text,
                    char_count=len(fallback_text),
                    attempts=attempts,
                    duration_ms=int((time.time() - start_time) * 1000),
                    extractor_used="newspaper3k",
                )
            return ExtractionResult(
                success=False,
                failure_reason=(
                    ExtractionFailureReason.TIMEOUT if "timeout" in str(e).lower() else ExtractionFailureReason.UNKNOWN
                ),
                attempts=attempts,
                duration_ms=int((time.time() - start_time) * 1000),
            )
