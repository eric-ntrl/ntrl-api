# app/routers/brief.py
"""
Daily brief endpoints.

GET /v1/brief - Get the current daily brief
"""

from datetime import UTC, datetime, timedelta

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app import models
from app.database import get_db
from app.models import FEED_CATEGORY_ORDER, FeedCategory
from app.schemas.brief import FEED_CATEGORY_DISPLAY_NAMES, BriefResponse, BriefSection, BriefStory

router = APIRouter(prefix="/v1", tags=["brief"])

# In-memory cache for brief responses (15 min TTL, max 10 entries)
_brief_cache: TTLCache = TTLCache(maxsize=10, ttl=900)


def invalidate_brief_cache():
    """Clear the brief response cache. Call after POST /v1/brief/run."""
    _brief_cache.clear()


@router.get("/brief", response_model=BriefResponse)
def get_brief(
    response: Response,
    db: Session = Depends(get_db),
    hours: int | None = Query(
        default=None,
        ge=1,
        le=168,
        description="Filter to stories from last N hours (1-168). Default: all stories in brief.",
    ),
) -> BriefResponse:
    """
    Get the current daily brief.

    Returns a deterministic feed of neutralized stories organized by section.
    Sections appear in fixed order: World, U.S., Local, Business & Markets, Technology.
    Stories within each section are ordered by time (most recent first).

    Use ?hours=24 to get only stories from the last 24 hours (recommended for mobile).

    No personalization, trending, or engagement signals.
    """
    # Check cache
    cache_key = f"brief:{hours}"
    cached = _brief_cache.get(cache_key)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        response.headers["Cache-Control"] = "public, max-age=900"
        return cached

    response.headers["X-Cache"] = "MISS"
    response.headers["Cache-Control"] = "public, max-age=900"

    # Get current brief
    brief = (
        db.query(models.DailyBrief)
        .filter(models.DailyBrief.is_current == True)
        .order_by(models.DailyBrief.assembled_at.desc())
        .first()
    )

    if not brief:
        raise HTTPException(
            status_code=404,
            detail="No daily brief available. Run POST /v1/brief/run to assemble one.",
        )

    # Handle empty brief
    if brief.is_empty:
        return BriefResponse(
            id=str(brief.id),
            brief_date=brief.brief_date,
            cutoff_time=brief.cutoff_time,
            assembled_at=brief.assembled_at,
            sections=[],
            total_stories=0,
            is_empty=True,
            empty_message=brief.empty_reason or "Insufficient qualifying stories in the last 24 hours.",
        )

    # Calculate time cutoff if hours parameter provided
    time_cutoff = None
    if hours:
        time_cutoff = datetime.now(UTC) - timedelta(hours=hours)

    # Build sections
    sections: list[BriefSection] = []
    total_filtered_stories = 0

    for category in FeedCategory:
        category_items = [item for item in brief.items if item.section == category.value]

        # Apply time filter if specified
        if time_cutoff:
            category_items = [
                item
                for item in category_items
                if (
                    item.published_at.replace(tzinfo=UTC)
                    if item.published_at and item.published_at.tzinfo is None
                    else item.published_at
                )
                >= time_cutoff
            ]

        if not category_items:
            continue

        # Fetch detail fields from story_neutralized for each item
        story_ids = [item.story_neutralized_id for item in category_items]
        neutralized_map = {}
        if story_ids:
            neutralized_stories = (
                db.query(models.StoryNeutralized).filter(models.StoryNeutralized.id.in_(story_ids)).all()
            )
            neutralized_map = {str(s.id): s for s in neutralized_stories}

        stories = []
        for item in sorted(category_items, key=lambda x: x.position):
            neutralized = neutralized_map.get(str(item.story_neutralized_id))
            stories.append(
                BriefStory(
                    id=str(item.story_neutralized_id),
                    feed_title=item.feed_title,
                    feed_summary=item.feed_summary,
                    source_name=item.source_name,
                    source_url=item.original_url,
                    published_at=item.published_at,
                    has_manipulative_content=item.has_manipulative_content,
                    publisher_url=item.source_homepage_url,
                    position=item.position,
                    # Detail fields from story_neutralized (for article view)
                    detail_title=neutralized.detail_title if neutralized else None,
                    detail_brief=neutralized.detail_brief if neutralized else None,
                    detail_full=neutralized.detail_full if neutralized else None,
                    disclosure=neutralized.disclosure if neutralized else None,
                )
            )

        total_filtered_stories += len(stories)

        sections.append(
            BriefSection(
                name=category.value,
                display_name=FEED_CATEGORY_DISPLAY_NAMES.get(category.value, category.value.title()),
                order=FEED_CATEGORY_ORDER[category],
                stories=stories,
                story_count=len(stories),
            )
        )

    # Sort sections by order
    sections.sort(key=lambda x: x.order)

    result = BriefResponse(
        id=str(brief.id),
        brief_date=brief.brief_date,
        cutoff_time=brief.cutoff_time,
        assembled_at=brief.assembled_at,
        sections=sections,
        total_stories=total_filtered_stories if hours else brief.total_stories,
        is_empty=len(sections) == 0,
        empty_message="No stories in the requested time window." if len(sections) == 0 and hours else None,
    )

    # Store in cache
    _brief_cache[cache_key] = result
    return result
