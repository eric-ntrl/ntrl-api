# app/schemas/brief.py
"""
Schemas for daily brief endpoints.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class BriefStory(BaseModel):
    """A single story in the daily brief."""
    id: str = Field(..., description="Story ID (UUID)")
    feed_title: str = Field(..., description="Feed title, ≤6 words preferred")
    feed_summary: str = Field(..., description="Feed summary, 1-2 sentences")
    source_name: str = Field(..., description="Source name")
    source_url: str = Field(..., description="Original source URL")
    published_at: datetime = Field(..., description="Publish time")
    has_manipulative_content: bool = Field(..., description="Whether content was modified")
    position: int = Field(..., description="Position within section")

    # Detail fields (for article view - eliminates N+1 calls)
    detail_title: Optional[str] = Field(None, description="Precise article headline")
    detail_brief: Optional[str] = Field(None, description="3-5 paragraphs prose summary")
    detail_full: Optional[str] = Field(None, description="Filtered full article text")
    disclosure: Optional[str] = Field(None, description="Disclosure message about modifications")

    class Config:
        from_attributes = True


class BriefSection(BaseModel):
    """A section in the daily brief with its stories."""
    name: str = Field(..., description="Section name (world, us, local, business, technology)")
    display_name: str = Field(..., description="Display name for UI")
    order: int = Field(..., description="Section order (0-4)")
    stories: List[BriefStory] = Field(default_factory=list)
    story_count: int = Field(0, description="Number of stories in section")

    class Config:
        from_attributes = True


class BriefResponse(BaseModel):
    """
    Daily brief response.
    GET /v1/brief
    """
    id: str = Field(..., description="Brief ID (UUID)")
    brief_date: datetime = Field(..., description="Date this brief covers")
    cutoff_time: datetime = Field(..., description="Stories before this time")
    assembled_at: datetime = Field(..., description="When brief was assembled")

    # Content
    sections: List[BriefSection] = Field(default_factory=list)
    total_stories: int = Field(0, description="Total stories in brief")

    # Empty state
    is_empty: bool = Field(False, description="Whether brief has no qualifying stories")
    empty_message: Optional[str] = Field(
        None,
        description="Message if no stories: 'Insufficient qualifying stories in the last 24 hours.'"
    )

    class Config:
        from_attributes = True


# Section display names
SECTION_DISPLAY_NAMES = {
    "world": "World",
    "us": "U.S.",
    "local": "Local",
    "business": "Business & Markets",
    "technology": "Technology",
}
