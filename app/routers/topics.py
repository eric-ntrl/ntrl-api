# app/routers/topics.py
"""
Topics endpoints.

GET /v1/topics/trending - Returns trending topics from recent articles
"""

import logging

from cachetools import TTLCache
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.topics import TrendingTopicsResponse
from app.services.trending_service import TrendingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/topics", tags=["topics"])

# Cache for trending topics (5 minute TTL)
_trending_cache: TTLCache = TTLCache(maxsize=10, ttl=300)


def _get_cache_key(window_hours: int) -> str:
    """Generate cache key for trending topics."""
    return f"trending_{window_hours}"


@router.get("/trending", response_model=TrendingTopicsResponse)
def get_trending_topics(
    window_hours: int = Query(24, ge=1, le=168, description="Time window in hours (1-168, default 24)"),
    db: Session = Depends(get_db),
) -> TrendingTopicsResponse:
    """
    Get trending topics from recent articles.

    Returns a list of trending terms/phrases extracted from article titles
    and summaries within the specified time window.

    Topics are ranked by how many articles mention them. Results are cached
    for 5 minutes to reduce database load.
    """
    cache_key = _get_cache_key(window_hours)

    # Check cache
    if cache_key in _trending_cache:
        logger.debug("Trending topics cache hit")
        return _trending_cache[cache_key]

    # Generate trending topics
    service = TrendingService(db)
    result = service.get_trending_topics(window_hours=window_hours)

    # Cache result
    _trending_cache[cache_key] = result
    logger.debug(f"Generated {len(result.topics)} trending topics")

    return result
