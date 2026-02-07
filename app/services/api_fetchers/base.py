# app/services/api_fetchers/base.py
"""
Base classes and types for News API fetchers.

Defines the abstract BaseFetcher interface and NormalizedEntry TypedDict
that all API fetchers must implement and produce.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, TypedDict


class NormalizedEntry(TypedDict, total=False):
    """
    Normalized article entry from any news API source.

    This format mirrors the normalization done by RSS ingestion,
    allowing seamless integration with the existing pipeline.
    """

    # Required fields
    url: str  # Original article URL
    title: str  # Article headline
    body: str  # Full article body text
    published_at: datetime  # Publication timestamp

    # Optional fields
    description: str | None  # Short summary/excerpt
    author: str | None  # Article author
    source_name: str | None  # Publisher name (e.g., "Reuters")
    source_domain: str | None  # Publisher domain (e.g., "reuters.com")

    # API-specific metadata
    api_source: str  # "perigon", "newsdata", etc.
    api_article_id: str | None  # External article ID from API
    categories: list[str]  # API-provided categories
    entities: dict[str, Any]  # Extracted entities (people, orgs, locations)

    # Extraction metrics (for compatibility with RSS flow)
    body_downloaded: bool  # Whether body was fetched successfully
    extractor_used: str | None  # "api" for API sources
    extraction_failure_reason: str | None
    extraction_duration_ms: int


class BaseFetcher(ABC):
    """
    Abstract base class for news API fetchers.

    All API fetchers must implement this interface to integrate
    with NTRL's ingestion pipeline.
    """

    @abstractmethod
    async def fetch_articles(
        self,
        categories: list[str] | None = None,
        language: str = "en",
        max_results: int = 100,
        from_date: datetime | None = None,
    ) -> list[NormalizedEntry]:
        """
        Fetch and normalize articles from the API.

        Args:
            categories: Optional list of categories to filter by
            language: Language code (default "en" for English)
            max_results: Maximum number of articles to return
            from_date: Only fetch articles published after this date

        Returns:
            List of NormalizedEntry dictionaries ready for pipeline ingestion
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources (close HTTP client, etc.)."""
        pass

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Return the source type identifier (e.g., 'perigon', 'newsdata')."""
        pass
