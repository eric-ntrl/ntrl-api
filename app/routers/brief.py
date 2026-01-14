# app/routers/brief.py
"""
Daily brief endpoints.

GET /v1/brief - Get the current daily brief
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.models import Section, SECTION_ORDER
from app.schemas.brief import BriefResponse, BriefSection, BriefStory, SECTION_DISPLAY_NAMES

router = APIRouter(prefix="/v1", tags=["brief"])


@router.get("/brief", response_model=BriefResponse)
def get_brief(
    db: Session = Depends(get_db),
) -> BriefResponse:
    """
    Get the current daily brief.

    Returns a deterministic feed of neutralized stories organized by section.
    Sections appear in fixed order: World, U.S., Local, Business & Markets, Technology.
    Stories within each section are ordered by time (most recent first).

    No personalization, trending, or engagement signals.
    """
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

    # Build sections
    sections: List[BriefSection] = []

    for section in Section:
        section_items = [
            item for item in brief.items
            if item.section == section.value
        ]

        if not section_items:
            continue

        stories = [
            BriefStory(
                id=str(item.story_neutralized_id),
                feed_title=item.feed_title,
                feed_summary=item.feed_summary,
                source_name=item.source_name,
                source_url=item.original_url,
                published_at=item.published_at,
                has_manipulative_content=item.has_manipulative_content,
                position=item.position,
            )
            for item in sorted(section_items, key=lambda x: x.position)
        ]

        sections.append(BriefSection(
            name=section.value,
            display_name=SECTION_DISPLAY_NAMES.get(section.value, section.value.title()),
            order=SECTION_ORDER[section],
            stories=stories,
            story_count=len(stories),
        ))

    # Sort sections by order
    sections.sort(key=lambda x: x.order)

    return BriefResponse(
        id=str(brief.id),
        brief_date=brief.brief_date,
        cutoff_time=brief.cutoff_time,
        assembled_at=brief.assembled_at,
        sections=sections,
        total_stories=brief.total_stories,
        is_empty=False,
        empty_message=None,
    )
