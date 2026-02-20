# app/services/api_fetchers/perigon_fetcher.py
"""
Perigon News API fetcher for NTRL ingestion pipeline.

Perigon provides AI-enriched news with full article bodies, entity extraction,
sentiment analysis, and story clustering. This is the primary API source.

API Documentation: https://docs.perigon.io
"""

import logging
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.api_fetchers.base import BaseFetcher, NormalizedEntry

logger = logging.getLogger(__name__)


# Map Perigon categories to NTRL feed categories
PERIGON_CATEGORY_MAP = {
    # Direct mappings
    "Politics": "us",
    "Business": "business",
    "Finance": "business",
    "Tech": "technology",
    "Science": "science",
    "Health": "health",
    "Environment": "environment",
    "Sports": "sports",
    "Entertainment": "culture",
    "Lifestyle": "culture",
    "Arts": "culture",
    # World/international
    "World": "world",
    "International": "world",
    # Default
    "General": "world",
}

# Regex to detect Perigon content truncation markers like "...[1811 symbols]"
TRUNCATION_PATTERN = re.compile(r"\.\.\.\[\d+\s*(?:symbols?|chars?|characters?)\]")


class PerigonFetcher(BaseFetcher):
    """
    Fetch articles from Perigon News API.

    Perigon provides:
    - Full article body text
    - AI-extracted entities (people, organizations, locations)
    - Sentiment analysis
    - Category classification
    - Story clustering via /stories endpoint

    Rate limits:
    - Page size: 0-100 articles per request
    - Pagination supported via 'page' parameter
    """

    BASE_URL = "https://api.goperigon.com/v1"
    DEFAULT_PAGE_SIZE = 100
    DEFAULT_TIMEOUT = 30.0

    def __init__(
        self,
        api_key: str,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """
        Initialize Perigon fetcher.

        Args:
            api_key: Perigon API key
            timeout: HTTP request timeout in seconds
        """
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "x-api-key": api_key,
                "Accept": "application/json",
            },
        )

    @property
    def source_type(self) -> str:
        return "perigon"

    async def fetch_articles(
        self,
        categories: list[str] | None = None,
        language: str = "en",
        max_results: int = 100,
        from_date: datetime | None = None,
    ) -> list[NormalizedEntry]:
        """
        Fetch and normalize articles from Perigon.

        Args:
            categories: Optional list of Perigon categories to filter by
            language: Language code (default "en")
            max_results: Maximum articles to return (default 100)
            from_date: Only fetch articles after this date

        Returns:
            List of normalized article entries
        """
        start_time = time.time()
        articles: list[NormalizedEntry] = []

        try:
            # Build query parameters
            params: dict[str, Any] = {
                "language": language,
                "size": min(max_results, self.DEFAULT_PAGE_SIZE),
                "sortBy": "date",
            }

            if categories:
                params["category"] = ",".join(categories)

            if from_date:
                params["from"] = from_date.strftime("%Y-%m-%dT%H:%M:%S")

            # Fetch articles
            response = await self.client.get(
                f"{self.BASE_URL}/all",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            # Normalize each article
            for article in data.get("articles", []):
                try:
                    normalized = self._normalize_article(article, start_time)
                    if normalized:
                        articles.append(normalized)
                except Exception as e:
                    logger.warning(f"Failed to normalize Perigon article: {e}")
                    continue

            logger.info(f"Perigon fetched {len(articles)} articles in {int((time.time() - start_time) * 1000)}ms")

        except httpx.HTTPStatusError as e:
            logger.error(f"Perigon API error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Perigon fetch failed: {e}")
            raise

        return articles

    async def fetch_stories(
        self,
        language: str = "en",
        max_results: int = 50,
        from_date: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch clustered news stories (trending topics).

        Perigon's /stories endpoint groups related articles into stories,
        useful for identifying trending topics.

        Args:
            language: Language code
            max_results: Maximum stories to return
            from_date: Only fetch stories after this date

        Returns:
            List of story clusters with metadata
        """
        params: dict[str, Any] = {
            "language": language,
            "size": min(max_results, self.DEFAULT_PAGE_SIZE),
            "sortBy": "count",  # Sort by article count
        }

        if from_date:
            params["from"] = from_date.strftime("%Y-%m-%dT%H:%M:%S")

        response = await self.client.get(
            f"{self.BASE_URL}/stories",
            params=params,
        )
        response.raise_for_status()
        data = response.json()

        return data.get("stories", [])

    @staticmethod
    def _is_body_truncated(body: str) -> bool:
        """Check if Perigon body text contains truncation markers."""
        if not body:
            return False
        return bool(TRUNCATION_PATTERN.search(body))

    def _normalize_article(
        self,
        article: dict[str, Any],
        start_time: float,
    ) -> NormalizedEntry | None:
        """
        Convert Perigon article to NTRL NormalizedEntry.

        Args:
            article: Raw article from Perigon API
            start_time: Fetch start time for duration calculation

        Returns:
            Normalized entry or None if required fields missing
        """
        # Extract required fields
        url = article.get("url")
        title = article.get("title")
        body = article.get("content")  # Full body text

        # Check for truncation markers in Perigon content
        body_is_truncated = self._is_body_truncated(body) if body else False
        if body_is_truncated:
            logger.info(f"Perigon article body truncated, will need web scraping: {url}")

        if not url or not title:
            return None

        # Parse publication date
        pub_date_str = article.get("pubDate")
        if pub_date_str:
            try:
                published_at = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                published_at = datetime.now(UTC)
        else:
            published_at = datetime.now(UTC)

        # Extract source info
        source = article.get("source", {})
        source_name = source.get("name")
        source_domain = source.get("domain")

        # Fallback: derive publisher name from domain if source.name is missing
        if not source_name and source_domain:
            source_name = source_domain.lower().removeprefix("www.")
            logger.debug(f"Perigon article missing source.name, derived from domain: {source_name}")
        elif not source_name and url:
            try:
                parsed = urlparse(url)
                if parsed.netloc:
                    source_name = parsed.netloc.lower().removeprefix("www.")
                    logger.debug(f"Perigon article missing source.name, derived from URL: {source_name}")
            except Exception as e:
                logger.warning(f"Failed to parse Perigon article URL: {e}")

        # Extract categories and map to NTRL
        categories = []
        for cat in article.get("categories", []):
            if isinstance(cat, str):
                categories.append(cat)
            elif isinstance(cat, dict):
                categories.append(cat.get("name", ""))

        # Extract entities
        entities: dict[str, Any] = {}
        for entity_type in ["people", "organizations", "locations"]:
            entity_list = article.get(entity_type, [])
            if entity_list:
                entities[entity_type] = [e.get("name") if isinstance(e, dict) else e for e in entity_list]

        # Calculate extraction duration
        duration_ms = int((time.time() - start_time) * 1000)

        return NormalizedEntry(
            url=url,
            title=title,
            body=body or "",
            published_at=published_at,
            description=article.get("description"),
            author=article.get("authorsByline"),
            source_name=source_name,
            source_domain=source_domain,
            api_source="perigon",
            api_article_id=article.get("articleId"),
            categories=categories,
            entities=entities,
            body_downloaded=bool(body) and not body_is_truncated,
            extractor_used="perigon_api" if (body and not body_is_truncated) else None,
            extraction_failure_reason=("truncated_content" if body_is_truncated else (None if body else "no_content")),
            extraction_duration_ms=duration_ms,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self) -> "PerigonFetcher":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
