# app/services/api_fetchers/__init__.py
"""
News API fetchers for NTRL ingestion pipeline.

This package provides fetchers for external news APIs that supplement
the existing RSS feed ingestion. Each fetcher normalizes API responses
to NTRL's internal NormalizedEntry format for seamless pipeline integration.

Supported APIs:
- Perigon News API (primary)
- NewsData.io (backup)
"""

from app.services.api_fetchers.base import BaseFetcher, NormalizedEntry
from app.services.api_fetchers.perigon_fetcher import PerigonFetcher
from app.services.api_fetchers.newsdata_fetcher import NewsDataFetcher

__all__ = [
    "BaseFetcher",
    "NormalizedEntry",
    "PerigonFetcher",
    "NewsDataFetcher",
]
