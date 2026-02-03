# app/services/search_service.py
"""
Full-text search service for articles.

Provides server-side search with:
- PostgreSQL full-text search (tsvector/tsquery)
- Weighted ranking (title > summary > brief)
- Faceted results (category, source counts)
- Auto-complete suggestions for sections and publishers
"""

import logging
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import func, text, desc, and_
from sqlalchemy.orm import Session

from app import models
from app.models import FeedCategory, FEED_CATEGORY_DISPLAY
from app.schemas.search import (
    SearchResultItem,
    FacetCount,
    SearchFacets,
    SearchSuggestion,
    SearchResponse,
)

logger = logging.getLogger(__name__)


# Source display names (slug -> display name)
SOURCE_DISPLAY_NAMES = {
    "ap": "Associated Press",
    "ap-news": "AP News",
    "reuters": "Reuters",
    "bbc": "BBC",
    "npr": "NPR",
    "nyt": "New York Times",
    "wapo": "Washington Post",
    "wsj": "Wall Street Journal",
    "cnn": "CNN",
    "fox": "Fox News",
    "abc": "ABC News",
    "cbs": "CBS News",
    "nbc": "NBC News",
}


def get_source_display_name(slug: str, name: str) -> str:
    """Get display name for a source."""
    return SOURCE_DISPLAY_NAMES.get(slug.lower(), name)


class SearchService:
    """Service for searching articles with full-text search."""

    def __init__(self, db: Session):
        """Initialize search service with database session."""
        self.db = db

    def search(
        self,
        query: str,
        categories: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
        published_after: Optional[datetime] = None,
        published_before: Optional[datetime] = None,
        sort: str = "relevance",
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """
        Perform full-text search with filters.

        Args:
            query: Search query string (min 2 chars)
            categories: Filter by feed_category (list for multi-select)
            sources: Filter by source slug (list for multi-select)
            published_after: Filter by publish date
            published_before: Filter by publish date
            sort: "relevance" or "recency"
            limit: Max results (1-50)
            offset: Pagination offset

        Returns:
            SearchResponse with items, facets, and suggestions
        """
        # Normalize query
        query = query.strip()
        if len(query) < 2:
            return SearchResponse(
                query=query,
                total=0,
                limit=limit,
                offset=offset,
                items=[],
                facets=SearchFacets(),
                suggestions=[],
            )

        # Build the base query with full-text search
        ts_query = func.plainto_tsquery('english', query)

        # Base query: join neutralized -> raw -> source
        base_query = (
            self.db.query(
                models.StoryNeutralized,
                models.StoryRaw,
                models.Source,
                func.ts_rank(models.StoryNeutralized.search_vector, ts_query).label('rank')
            )
            .join(models.StoryRaw, models.StoryNeutralized.story_raw_id == models.StoryRaw.id)
            .join(models.Source, models.StoryRaw.source_id == models.Source.id)
            .filter(
                models.StoryNeutralized.is_current == True,
                models.StoryNeutralized.neutralization_status == "success",
                models.StoryRaw.is_duplicate == False,
                models.StoryNeutralized.search_vector.op('@@')(ts_query),
            )
        )

        # Apply filters
        if categories:
            base_query = base_query.filter(models.StoryRaw.feed_category.in_(categories))

        if sources:
            base_query = base_query.filter(models.Source.slug.in_(sources))

        if published_after:
            base_query = base_query.filter(models.StoryRaw.published_at >= published_after)

        if published_before:
            base_query = base_query.filter(models.StoryRaw.published_at <= published_before)

        # Get total count (before pagination)
        count_query = base_query.with_entities(func.count()).scalar()
        total = count_query or 0

        # Apply sorting
        if sort == "recency":
            base_query = base_query.order_by(
                desc(models.StoryRaw.published_at),
                text('rank DESC'),
            )
        else:  # relevance (default)
            base_query = base_query.order_by(
                text('rank DESC'),
                desc(models.StoryRaw.published_at),
            )

        # Apply pagination
        results = base_query.offset(offset).limit(limit).all()

        # Transform results
        items = []
        for neutralized, story_raw, source_obj, rank in results:
            items.append(SearchResultItem(
                id=str(neutralized.id),
                feed_title=neutralized.feed_title,
                feed_summary=neutralized.feed_summary,
                detail_title=neutralized.detail_title,
                detail_brief=neutralized.detail_brief,
                source_name=source_obj.name,
                source_slug=source_obj.slug,
                source_url=story_raw.original_url,
                feed_category=story_raw.feed_category,
                published_at=story_raw.published_at,
                has_manipulative_content=neutralized.has_manipulative_content,
                rank=float(rank) if rank else None,
            ))

        # Get facets (unfiltered counts for showing available filters)
        facets = self._get_facets(query, ts_query)

        # Get suggestions (for short queries or showing related content)
        suggestions = self._get_suggestions(query)

        return SearchResponse(
            query=query,
            total=total,
            limit=limit,
            offset=offset,
            items=items,
            facets=facets,
            suggestions=suggestions,
        )

    def _get_facets(self, query: str, ts_query) -> SearchFacets:
        """
        Get facet counts for categories and sources.

        Returns counts without the current filters applied
        (so users can see what other filters are available).
        """
        # Category facets
        category_counts = (
            self.db.query(
                models.StoryRaw.feed_category,
                func.count(models.StoryNeutralized.id).label('count')
            )
            .join(models.StoryNeutralized, models.StoryNeutralized.story_raw_id == models.StoryRaw.id)
            .filter(
                models.StoryNeutralized.is_current == True,
                models.StoryNeutralized.neutralization_status == "success",
                models.StoryRaw.is_duplicate == False,
                models.StoryRaw.feed_category.isnot(None),
                models.StoryNeutralized.search_vector.op('@@')(ts_query),
            )
            .group_by(models.StoryRaw.feed_category)
            .all()
        )

        categories = []
        for cat_value, count in category_counts:
            if cat_value:
                label = FEED_CATEGORY_DISPLAY.get(cat_value, cat_value.title())
                categories.append(FacetCount(
                    key=cat_value,
                    label=label,
                    count=count,
                ))

        # Sort categories by the standard order
        category_order = {cat.value: idx for idx, cat in enumerate(FeedCategory)}
        categories.sort(key=lambda x: category_order.get(x.key, 99))

        # Source facets
        source_counts = (
            self.db.query(
                models.Source.slug,
                models.Source.name,
                func.count(models.StoryNeutralized.id).label('count')
            )
            .join(models.StoryRaw, models.StoryRaw.source_id == models.Source.id)
            .join(models.StoryNeutralized, models.StoryNeutralized.story_raw_id == models.StoryRaw.id)
            .filter(
                models.StoryNeutralized.is_current == True,
                models.StoryNeutralized.neutralization_status == "success",
                models.StoryRaw.is_duplicate == False,
                models.StoryNeutralized.search_vector.op('@@')(ts_query),
            )
            .group_by(models.Source.slug, models.Source.name)
            .order_by(desc('count'))
            .all()
        )

        sources = []
        for slug, name, count in source_counts:
            display_name = get_source_display_name(slug, name)
            sources.append(FacetCount(
                key=slug,
                label=display_name,
                count=count,
            ))

        return SearchFacets(categories=categories, sources=sources)

    def _get_suggestions(self, query: str) -> List[SearchSuggestion]:
        """
        Get auto-complete suggestions for the query.

        Returns matching:
        - Section names (feed categories)
        - Publisher names
        """
        suggestions = []
        query_lower = query.lower()

        # Match section names
        for cat in FeedCategory:
            label = FEED_CATEGORY_DISPLAY.get(cat.value, cat.value.title())
            if query_lower in label.lower() or query_lower in cat.value.lower():
                # Get count for this category
                count = (
                    self.db.query(func.count(models.StoryNeutralized.id))
                    .join(models.StoryRaw, models.StoryNeutralized.story_raw_id == models.StoryRaw.id)
                    .filter(
                        models.StoryNeutralized.is_current == True,
                        models.StoryNeutralized.neutralization_status == "success",
                        models.StoryRaw.is_duplicate == False,
                        models.StoryRaw.feed_category == cat.value,
                    )
                    .scalar() or 0
                )
                if count > 0:
                    suggestions.append(SearchSuggestion(
                        type="section",
                        value=cat.value,
                        label=label,
                        count=count,
                    ))

        # Match publisher names
        sources = (
            self.db.query(models.Source)
            .filter(models.Source.is_active == True)
            .all()
        )

        for source in sources:
            display_name = get_source_display_name(source.slug, source.name)
            if query_lower in display_name.lower() or query_lower in source.slug.lower():
                # Get count for this source
                count = (
                    self.db.query(func.count(models.StoryNeutralized.id))
                    .join(models.StoryRaw, models.StoryNeutralized.story_raw_id == models.StoryRaw.id)
                    .filter(
                        models.StoryNeutralized.is_current == True,
                        models.StoryNeutralized.neutralization_status == "success",
                        models.StoryRaw.is_duplicate == False,
                        models.StoryRaw.source_id == source.id,
                    )
                    .scalar() or 0
                )
                if count > 0:
                    suggestions.append(SearchSuggestion(
                        type="publisher",
                        value=source.slug,
                        label=display_name,
                        count=count,
                    ))

        # Limit suggestions and sort by count
        suggestions.sort(key=lambda x: -(x.count or 0))
        return suggestions[:8]
