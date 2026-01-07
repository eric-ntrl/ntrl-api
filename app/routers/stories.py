# app/routers/stories.py
"""
Story endpoints.

GET /v1/stories/{id} - Get story detail (neutralized content first)
GET /v1/stories/{id}/transparency - Get transparency view with what was removed
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.schemas.stories import StoryDetail, StoryTransparency, TransparencySpanResponse

router = APIRouter(prefix="/v1/stories", tags=["stories"])


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

    return StoryTransparency(
        id=str(neutralized.id),
        original_title=story_raw.original_title,
        original_description=story_raw.original_description,
        original_body=story_raw.original_body,
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
