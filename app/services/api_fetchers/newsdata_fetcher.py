# app/services/api_fetchers/newsdata_fetcher.py
"""
NewsData.io API fetcher for NTRL ingestion pipeline.

NewsData.io provides news from 87,000+ sources across 206 countries.
Full article body requires Professional plan ($350/month) or higher.

API Documentation: https://newsdata.io/documentation
"""

import logging
import time
from datetime import datetime
from typing import Any

import httpx

from app.services.api_fetchers.base import BaseFetcher, NormalizedEntry

logger = logging.getLogger(__name__)


# Map NewsData.io categories to NTRL feed categories
NEWSDATA_CATEGORY_MAP = {
    "business": "business",
    "entertainment": "culture",
    "environment": "environment",
    "food": "culture",
    "health": "health",
    "politics": "us",
    "science": "science",
    "sports": "sports",
    "technology": "technology",
    "top": "world",
    "tourism": "culture",
    "world": "world",
}


class NewsDataFetcher(BaseFetcher):
    """
    Fetch articles from NewsData.io API.

    NewsData.io provides:
    - 12 built-in categories
    - 89 languages
    - AI-generated summaries (paid plans)
    - Full content (Professional plan and above, requires full_content=1)

    Rate limits:
    - Free: 30 credits/15 min (300 articles)
    - Paid: 1,800 credits/15 min (90,000 articles)
    - 1 credit = 10 results
    """

    BASE_URL = "https://newsdata.io/api/1"
    DEFAULT_PAGE_SIZE = 10  # NewsData.io free plan max per request
    DEFAULT_TIMEOUT = 30.0

    def __init__(
        self,
        api_key: str,
        timeout: float = DEFAULT_TIMEOUT,
        request_full_content: bool = True,
    ):
        """
        Initialize NewsData.io fetcher.

        Args:
            api_key: NewsData.io API key
            timeout: HTTP request timeout in seconds
            request_full_content: Request full article body (requires Professional plan)
        """
        self.api_key = api_key
        self.request_full_content = request_full_content
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Accept": "application/json",
            },
        )

    @property
    def source_type(self) -> str:
        return "newsdata"

    async def fetch_articles(
        self,
        categories: list[str] | None = None,
        language: str = "en",
        max_results: int = 50,
        from_date: datetime | None = None,
    ) -> list[NormalizedEntry]:
        """
        Fetch and normalize articles from NewsData.io.

        Args:
            categories: Optional list of NewsData.io categories
            language: Language code (default "en")
            max_results: Maximum articles to return
            from_date: Only fetch articles after this date (requires paid plan for historical)

        Returns:
            List of normalized article entries
        """
        start_time = time.time()
        articles: list[NormalizedEntry] = []
        page_size = min(max_results, self.DEFAULT_PAGE_SIZE)
        next_page: str | None = None

        try:
            while len(articles) < max_results:
                # Build query parameters
                params: dict[str, Any] = {
                    "apikey": self.api_key,
                    "language": language,
                    "size": page_size,
                }

                # Request full content if enabled (Professional plan required)
                if self.request_full_content:
                    params["full_content"] = 1

                if categories:
                    params["category"] = ",".join(categories)

                if from_date:
                    params["from_date"] = from_date.strftime("%Y-%m-%d")

                if next_page:
                    params["page"] = next_page

                # Fetch articles from latest news endpoint
                response = await self.client.get(
                    f"{self.BASE_URL}/latest",
                    params=params,
                )
                response.raise_for_status()
                data = response.json()

                # Check for API errors
                if data.get("status") != "success":
                    error_msg = data.get("results", {}).get("message", "Unknown error")
                    logger.error(f"NewsData.io API error: {error_msg}")
                    raise ValueError(f"NewsData.io API error: {error_msg}")

                # Normalize each article
                results = data.get("results", [])
                if not results:
                    break

                for article in results:
                    try:
                        normalized = self._normalize_article(article, start_time)
                        if normalized:
                            articles.append(normalized)
                    except Exception as e:
                        logger.warning(f"Failed to normalize NewsData.io article: {e}")
                        continue

                # Check for next page
                next_page = data.get("nextPage")
                if not next_page:
                    break

            # Trim to max_results
            articles = articles[:max_results]

            logger.info(f"NewsData.io fetched {len(articles)} articles in {int((time.time() - start_time) * 1000)}ms")

        except httpx.HTTPStatusError as e:
            logger.error(f"NewsData.io API error: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"NewsData.io fetch failed: {e}")
            raise

        return articles

    async def fetch_by_keywords(
        self,
        keywords: list[str],
        language: str = "en",
        max_results: int = 50,
    ) -> list[NormalizedEntry]:
        """
        Fetch articles by keyword search.

        Args:
            keywords: List of keywords to search for
            language: Language code
            max_results: Maximum articles to return

        Returns:
            List of normalized article entries
        """
        start_time = time.time()
        articles: list[NormalizedEntry] = []

        params: dict[str, Any] = {
            "apikey": self.api_key,
            "language": language,
            "q": " OR ".join(keywords),  # OR search
            "size": min(max_results, self.DEFAULT_PAGE_SIZE),
        }

        if self.request_full_content:
            params["full_content"] = 1

        response = await self.client.get(
            f"{self.BASE_URL}/latest",
            params=params,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") == "success":
            for article in data.get("results", []):
                try:
                    normalized = self._normalize_article(article, start_time)
                    if normalized:
                        articles.append(normalized)
                except Exception:
                    continue

        return articles

    def _normalize_article(
        self,
        article: dict[str, Any],
        start_time: float,
    ) -> NormalizedEntry | None:
        """
        Convert NewsData.io article to NTRL NormalizedEntry.

        Args:
            article: Raw article from NewsData.io API
            start_time: Fetch start time for duration calculation

        Returns:
            Normalized entry or None if required fields missing
        """
        # Extract required fields
        url = article.get("link")
        title = article.get("title")

        if not url or not title:
            return None

        # Get body - prefer full_content, fall back to content, then description
        body = article.get("full_content") or article.get("content") or article.get("description") or ""

        # Parse publication date
        pub_date_str = article.get("pubDate")
        if pub_date_str:
            try:
                # NewsData.io format: "2024-01-15 12:30:00"
                published_at = datetime.strptime(pub_date_str, "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                try:
                    # Try ISO format
                    published_at = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    published_at = datetime.utcnow()
        else:
            published_at = datetime.utcnow()

        # Extract source info
        source_name = article.get("source_name")
        source_domain = article.get("source_url")

        # Extract author (can be a list)
        creator = article.get("creator")
        if isinstance(creator, list) and creator:
            author = creator[0]
        elif isinstance(creator, str):
            author = creator
        else:
            author = None

        # Extract categories
        category = article.get("category", [])
        if isinstance(category, str):
            categories = [category]
        elif isinstance(category, list):
            categories = category
        else:
            categories = []

        # Extract keywords/tags as entities
        keywords = article.get("keywords", []) or []
        entities: dict[str, Any] = {}
        if keywords:
            entities["keywords"] = keywords

        # Calculate extraction duration
        duration_ms = int((time.time() - start_time) * 1000)

        # Determine if we got full content
        has_full_content = bool(article.get("full_content"))

        return NormalizedEntry(
            url=url,
            title=title,
            body=body,
            published_at=published_at,
            description=article.get("description"),
            author=author,
            source_name=source_name,
            source_domain=source_domain,
            api_source="newsdata",
            api_article_id=article.get("article_id"),
            categories=categories,
            entities=entities,
            body_downloaded=has_full_content or bool(body),
            extractor_used="newsdata_api",
            extraction_failure_reason=None if body else "no_content",
            extraction_duration_ms=duration_ms,
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self) -> "NewsDataFetcher":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
