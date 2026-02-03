# app/routers/search.py
"""
Search endpoints.

GET /v1/search - Full-text search with facets and suggestions
"""

import logging
from datetime import datetime
from typing import Optional, List

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.search_service import SearchService
from app.schemas.search import SearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/search", tags=["search"])

# Cache for search results (5 minute TTL, max 500 entries)
# Key: (query, categories, sources, sort, limit, offset) tuple
_search_cache: TTLCache = TTLCache(maxsize=500, ttl=300)


def _parse_comma_list(value: Optional[str]) -> Optional[List[str]]:
    """Parse a comma-separated string into a list of trimmed values."""
    if not value:
        return None
    items = [v.strip() for v in value.split(',') if v.strip()]
    return items if items else None


def _get_cache_key(
    query: str,
    categories: Optional[List[str]],
    sources: Optional[List[str]],
    published_after: Optional[datetime],
    published_before: Optional[datetime],
    sort: str,
    limit: int,
    offset: int,
) -> str:
    """Generate a cache key for search parameters."""
    after_str = published_after.isoformat() if published_after else ""
    before_str = published_before.isoformat() if published_before else ""
    # Sort lists for consistent cache keys
    cats_str = ",".join(sorted(categories)) if categories else ""
    srcs_str = ",".join(sorted(sources)) if sources else ""
    return f"{query}|{cats_str}|{srcs_str}|{after_str}|{before_str}|{sort}|{limit}|{offset}"


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(
        ...,
        min_length=2,
        description="Search query (min 2 characters)"
    ),
    # New multi-value parameters (comma-separated)
    categories: Optional[str] = Query(
        None,
        description="Filter by feed_category, comma-separated (e.g., 'world,us,technology')"
    ),
    sources: Optional[str] = Query(
        None,
        description="Filter by publisher slug, comma-separated (e.g., 'ap,reuters')"
    ),
    # Backward-compatible single-value aliases (deprecated)
    category: Optional[str] = Query(
        None,
        description="[Deprecated: use 'categories'] Filter by single feed_category"
    ),
    source: Optional[str] = Query(
        None,
        description="[Deprecated: use 'sources'] Filter by single publisher slug"
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

    Supports multi-value filtering via comma-separated lists:
    - categories: "world,us,technology"
    - sources: "ap,reuters"

    For backward compatibility, single-value 'category' and 'source' params
    are also supported but deprecated.
    """
    # Validate sort parameter
    if sort not in ("relevance", "recency"):
        raise HTTPException(
            status_code=400,
            detail="Invalid sort parameter. Must be 'relevance' or 'recency'."
        )

    # Parse multi-value parameters
    category_list = _parse_comma_list(categories)
    source_list = _parse_comma_list(sources)

    # Backward compatibility: if old single-value params are used, add them
    if category and not category_list:
        category_list = [category]
    if source and not source_list:
        source_list = [source]

    # Check cache
    cache_key = _get_cache_key(
        q, category_list, source_list, published_after, published_before, sort, limit, offset
    )
    if cache_key in _search_cache:
        logger.debug(f"Search cache hit for query: {q}")
        return _search_cache[cache_key]

    # Perform search
    service = SearchService(db)
    try:
        result = service.search(
            query=q,
            categories=category_list,
            sources=source_list,
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
