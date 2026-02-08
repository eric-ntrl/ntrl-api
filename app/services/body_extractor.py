"""
Robust article body extraction with retries and fallback extractors.

This module provides a hardened body extraction service that:
- Retries failed downloads with exponential backoff (3 attempts: 1s, 2s, 4s)
- Falls back through readability-lxml and newspaper3k when trafilatura fails
- Downloads HTML once and passes to all extractors (reduces network calls)
- Tracks detailed failure reasons for observability
"""

import configparser
import logging
import re
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
    extractor_used: str = "trafilatura"  # "trafilatura", "readability", or "newspaper3k"


class BodyExtractor:
    """Extract article body with retries, fallback extractors, and detailed failure tracking."""

    MIN_BODY_LENGTH = 200
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

    def _try_trafilatura(self, html: str) -> str | None:
        """Extract text using trafilatura from pre-downloaded HTML."""
        try:
            text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
            if text and len(text) >= self.MIN_BODY_LENGTH:
                return text
        except Exception as e:
            logger.debug(f"trafilatura extraction failed: {e}")
        return None

    def _try_readability(self, html: str) -> str | None:
        """Fallback extractor using readability-lxml (Mozilla algorithm)."""
        try:
            from readability import Document

            doc = Document(html)
            summary = doc.summary()
            # readability returns HTML, strip tags
            clean_text = re.sub(r"<[^>]+>", "", summary)
            clean_text = clean_text.strip()
            if clean_text and len(clean_text) >= self.MIN_BODY_LENGTH:
                logger.debug(f"readability extracted {len(clean_text)} chars")
                return clean_text
        except Exception as e:
            logger.debug(f"readability fallback failed: {e}")
        return None

    def _try_newspaper3k(self, url: str) -> str | None:
        """Fallback extractor using newspaper3k (re-downloads the page)."""
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
        1. Download HTML once with retries (exponential backoff: 1s, 2s, 4s)
        2. Try trafilatura on the downloaded HTML
        3. If failed: try readability-lxml on the same HTML
        4. If failed: try newspaper3k (re-downloads as last resort)
        5. Return detailed result with failure reason if all attempts fail
        """
        start_time = time.time()
        attempts = 0

        try:
            attempts = 1
            downloaded = self._fetch_with_retry(url)

            if not downloaded:
                # Download failed — try newspaper3k which does its own download
                logger.warning(f"trafilatura download failed for {url}, trying newspaper3k")
                text = self._try_newspaper3k(url)
                if text:
                    return ExtractionResult(
                        success=True,
                        body=text,
                        char_count=len(text),
                        attempts=attempts,
                        duration_ms=int((time.time() - start_time) * 1000),
                        extractor_used="newspaper3k",
                    )
                return ExtractionResult(
                    success=False,
                    failure_reason=ExtractionFailureReason.DOWNLOAD_FAILED,
                    attempts=attempts,
                    duration_ms=int((time.time() - start_time) * 1000),
                )

            # Try extractors in order on the same downloaded HTML
            extractors = [
                (lambda h: self._try_trafilatura(h), "trafilatura"),
                (lambda h: self._try_readability(h), "readability"),
            ]
            for extractor_fn, name in extractors:
                text = extractor_fn(downloaded)
                if text:
                    logger.debug(f"{name} extracted {len(text)} chars from {url}")
                    return ExtractionResult(
                        success=True,
                        body=text,
                        char_count=len(text),
                        attempts=attempts,
                        duration_ms=int((time.time() - start_time) * 1000),
                        extractor_used=name,
                    )

            # Last HTML-based extractors failed — try newspaper3k (re-downloads)
            logger.debug(f"trafilatura and readability insufficient for {url}, trying newspaper3k")
            text = self._try_newspaper3k(url)
            if text:
                return ExtractionResult(
                    success=True,
                    body=text,
                    char_count=len(text),
                    attempts=attempts,
                    duration_ms=int((time.time() - start_time) * 1000),
                    extractor_used="newspaper3k",
                )

            return ExtractionResult(
                success=False,
                failure_reason=ExtractionFailureReason.EXTRACTION_FAILED,
                attempts=attempts,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        except Exception as e:
            logger.warning(f"All extraction attempts failed for {url}: {e}")
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
