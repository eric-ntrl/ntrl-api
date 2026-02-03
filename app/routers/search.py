# app/routers/search.py
"""
Search endpoints.

GET /v1/search - Full-text search with facets and suggestions
"""

import logging
from datetime import datetime
from typing import Optional

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.search_service import SearchService
from app.schemas.search import SearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/search", tags=["search"])

# Cache for search results (5 minute TTL, max 500 entries)
# Key: (query, category, source, sort, limit, offset) tuple
_search_cache: TTLCache = TTLCache(maxsize=500, ttl=300)


def _get_cache_key(
    query: str,
    category: Optional[str],
    source: Optional[str],
    published_after: Optional[datetime],
    published_before: Optional[datetime],
    sort: str,
    limit: int,
    offset: int,
) -> str:
    """Generate a cache key for search parameters."""
    after_str = published_after.isoformat() if published_after else ""
    before_str = published_before.isoformat() if published_before else ""
    return f"{query}|{category}|{source}|{after_str}|{before_str}|{sort}|{limit}|{offset}"


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(
        ...,
        min_length=2,
        description="Search query (min 2 characters)"
    ),
    category: Optional[str] = Query(
        None,
        description="Filter by feed_category (world, us, technology, etc.)"
    ),
    source: Optional[str] = Query(
        None,
        description="Filter by publisher slug (ap, reuters, etc.)"
    ),
    published_after: Optional[datetime] = Query(
        None,
        description="Filter to articles published after this timestamp (ISO format)"
    ),
    published_before: Optional[datetime] = Query(
        None,
        description="Filter to articles published before this timestamp (ISO format)"
    ),
    sort: str = Query(
        "relevance",
        description="Sort order: 'relevance' (default) or 'recency'"
    ),
    limit: int = Query(
        20,
        ge=1,
        le=50,
        description="Results per page (1-50)"
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Pagination offset"
    ),
    db: Session = Depends(get_db),
) -> SearchResponse:
    """
    Search articles with full-text search.

    Returns matching articles sorted by relevance or recency,
    with facet counts for filtering and suggestions for auto-complete.
    """
    # Validate sort parameter
    if sort not in ("relevance", "recency"):
        raise HTTPException(
            status_code=400,
            detail="Invalid sort parameter. Must be 'relevance' or 'recency'."
        )

    # Check cache
    cache_key = _get_cache_key(
        q, category, source, published_after, published_before, sort, limit, offset
    )
    if cache_key in _search_cache:
        logger.debug(f"Search cache hit for query: {q}")
        return _search_cache[cache_key]

    # Perform search
    service = SearchService(db)
    try:
        result = service.search(
            query=q,
            category=category,
            source=source,
            published_after=published_after,
            published_before=published_before,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        logger.error(f"Search failed for query '{q}': {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Search failed. Please try again."
        )

    # Cache result
    _search_cache[cache_key] = result
    logger.debug(f"Search completed: query='{q}', total={result.total}")

    return result
