# app/routers/stories.py
"""
Story endpoints.

GET /v1/stories/{id} - Get story detail (neutralized content first)
GET /v1/stories/{id}/transparency - Get transparency view with what was removed
"""

import logging
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.schemas.stories import StoryDetail, StoryTransparency, TransparencySpanResponse
from app.storage.factory import get_storage_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/stories", tags=["stories"])


def _get_body_from_storage(story_raw: models.StoryRaw) -> Optional[str]:
    """
    Retrieve body content from object storage.

    Returns None if:
    - No content was stored
    - Content has expired
    - Storage retrieval fails
    """
    if not story_raw.raw_content_available or not story_raw.raw_content_uri:
        return None

    try:
        storage = get_storage_provider()
        result = storage.download(story_raw.raw_content_uri)
        if result and result.exists:
            return result.content.decode("utf-8")
    except Exception as e:
        logger.warning(f"Failed to retrieve body from storage: {e}")

    return None


def _get_story_or_404(db: Session, story_id: str) -> tuple:
    """Get story with neutralization or raise 404."""
    try:
        story_uuid = uuid.UUID(story_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid story ID format")

    # First try to find by neutralized ID
    neutralized = (
        db.query(models.StoryNeutralized)
        .filter(models.StoryNeutralized.id == story_uuid)
        .first()
    )

    if neutralized:
        story_raw = neutralized.story_raw
    else:
        # Try by raw story ID
        story_raw = (
            db.query(models.StoryRaw)
            .filter(models.StoryRaw.id == story_uuid)
            .first()
        )

        if not story_raw:
            raise HTTPException(status_code=404, detail="Story not found")

        # Get current neutralization
        neutralized = (
            db.query(models.StoryNeutralized)
            .filter(
                models.StoryNeutralized.story_raw_id == story_raw.id,
                models.StoryNeutralized.is_current == True,
            )
            .first()
        )

        if not neutralized:
            raise HTTPException(
                status_code=404,
                detail="Story has not been neutralized yet",
            )

    source = story_raw.source
    return neutralized, story_raw, source


# -----------------------------------------------------------------------------
# List Stories
# -----------------------------------------------------------------------------

from pydantic import BaseModel, Field
from datetime import datetime

class StoryListItem(BaseModel):
    """Story list item showing before/after comparison."""
    id: str
    # Original (before)
    original_title: str
    original_description: Optional[str]
    # Neutralized (after)
    neutral_headline: Optional[str]
    neutral_summary: Optional[str]
    # Metadata
    source_name: str
    source_slug: str
    source_url: str
    published_at: datetime
    section: Optional[str]
    has_manipulative_content: bool
    is_neutralized: bool

    class Config:
        from_attributes = True


class StoryListResponse(BaseModel):
    """List of stories."""
    stories: List[StoryListItem]
    total: int


@router.get("", response_model=StoryListResponse)
def list_stories(
    source_slug: Optional[str] = None,
    neutralized_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> StoryListResponse:
    """
    List stories with before/after comparison.

    Filter by source_slug or show only neutralized stories.
    """
    query = (
        db.query(models.StoryRaw)
        .filter(models.StoryRaw.is_duplicate == False)
        .join(models.Source)
    )

    if source_slug:
        query = query.filter(models.Source.slug == source_slug)

    if neutralized_only:
        query = query.join(
            models.StoryNeutralized,
            models.StoryRaw.id == models.StoryNeutralized.story_raw_id
        ).filter(models.StoryNeutralized.is_current == True)

    total = query.count()
    stories_raw = (
        query
        .order_by(models.StoryRaw.published_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    result = []
    for story in stories_raw:
        # Get current neutralization if exists
        neutralized = (
            db.query(models.StoryNeutralized)
            .filter(
                models.StoryNeutralized.story_raw_id == story.id,
                models.StoryNeutralized.is_current == True
            )
            .first()
        )

        result.append(StoryListItem(
            id=str(story.id),
            original_title=story.original_title,
            original_description=story.original_description,
            neutral_headline=neutralized.neutral_headline if neutralized else None,
            neutral_summary=neutralized.neutral_summary if neutralized else None,
            source_name=story.source.name,
            source_slug=story.source.slug,
            source_url=story.original_url,
            published_at=story.published_at,
            section=story.section,
            has_manipulative_content=neutralized.has_manipulative_content if neutralized else False,
            is_neutralized=neutralized is not None,
        ))

    return StoryListResponse(stories=result, total=total)


@router.get("/{story_id}", response_model=StoryDetail)
def get_story(
    story_id: str,
    db: Session = Depends(get_db),
) -> StoryDetail:
    """
    Get story detail.

    Shows neutralized/filtered content first with disclosure.
    Always links to original source URL.
    No engagement mechanics (likes, saves, shares).
    """
    neutralized, story_raw, source = _get_story_or_404(db, story_id)

    return StoryDetail(
        id=str(neutralized.id),
        neutral_headline=neutralized.neutral_headline,
        neutral_summary=neutralized.neutral_summary,
        what_happened=neutralized.what_happened,
        why_it_matters=neutralized.why_it_matters,
        what_is_known=neutralized.what_is_known,
        what_is_uncertain=neutralized.what_is_uncertain,
        disclosure=neutralized.disclosure if neutralized.has_manipulative_content else "",
        has_manipulative_content=neutralized.has_manipulative_content,
        source_name=source.name,
        source_url=story_raw.original_url,
        published_at=story_raw.published_at,
        section=story_raw.section,
    )


@router.get("/{story_id}/transparency", response_model=StoryTransparency)
def get_story_transparency(
    story_id: str,
    db: Session = Depends(get_db),
) -> StoryTransparency:
    """
    Get transparency view for a story.

    Shows what manipulative content was removed/changed and why.
    Includes original content for comparison.
    Always links to original source.
    """
    neutralized, story_raw, source = _get_story_or_404(db, story_id)

    # Get spans
    spans = (
        db.query(models.TransparencySpan)
        .filter(models.TransparencySpan.story_neutralized_id == neutralized.id)
        .order_by(models.TransparencySpan.field, models.TransparencySpan.start_char)
        .all()
    )

    span_responses = [
        TransparencySpanResponse(
            start_char=span.start_char,
            end_char=span.end_char,
            original_text=span.original_text,
            action=span.action,
            reason=span.reason,
            replacement_text=span.replacement_text,
        )
        for span in spans
    ]

    # Retrieve body from object storage
    original_body = _get_body_from_storage(story_raw)

    return StoryTransparency(
        id=str(neutralized.id),
        original_title=story_raw.original_title,
        original_description=story_raw.original_description,
        original_body=original_body,
        original_body_available=story_raw.raw_content_available,
        original_body_expired=not story_raw.raw_content_available and story_raw.raw_content_expired_at is not None,
        neutral_headline=neutralized.neutral_headline,
        neutral_summary=neutralized.neutral_summary,
        spans=span_responses,
        disclosure=neutralized.disclosure if neutralized.has_manipulative_content else "",
        has_manipulative_content=neutralized.has_manipulative_content,
        source_url=story_raw.original_url,
        model_name=neutralized.model_name,
        prompt_version=neutralized.prompt_version,
        processed_at=neutralized.created_at,
    )
