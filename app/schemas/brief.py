# app/schemas/brief.py
"""
Schemas for daily brief endpoints.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BriefStory(BaseModel):
    """A single story in the daily brief."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Story ID (UUID)")
    feed_title: str = Field(..., description="Feed title, ≤6 words preferred")
    feed_summary: str = Field(..., description="Feed summary, 1-2 sentences")
    source_name: str = Field(..., description="Source name")
    source_url: str = Field(..., description="Original source URL")
    published_at: datetime = Field(..., description="Publish time")
    has_manipulative_content: bool = Field(..., description="Whether content was modified")
    position: int = Field(..., description="Position within section")

    # Detail fields (for article view - eliminates N+1 calls)
    detail_title: str | None = Field(None, description="Precise article headline")
    detail_brief: str | None = Field(None, description="3-5 paragraphs prose summary")
    detail_full: str | None = Field(None, description="Filtered full article text")
    disclosure: str | None = Field(None, description="Disclosure message about modifications")


class BriefSection(BaseModel):
    """A section in the daily brief with its stories."""

    model_config = ConfigDict(from_attributes=True)

    name: str = Field(..., description="Section name (e.g. world, us, science, health)")
    display_name: str = Field(..., description="Display name for UI")
    order: int = Field(..., description="Section order (0-9)")
    stories: list[BriefStory] = Field(default_factory=list)
    story_count: int = Field(0, description="Number of stories in section")


class BriefResponse(BaseModel):
    """
    Daily brief response.
    GET /v1/brief
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Brief ID (UUID)")
    brief_date: datetime = Field(..., description="Date this brief covers")
    cutoff_time: datetime = Field(..., description="Stories before this time")
    assembled_at: datetime = Field(..., description="When brief was assembled")

    # Content
    sections: list[BriefSection] = Field(default_factory=list)
    total_stories: int = Field(0, description="Total stories in brief")

    # Empty state
    is_empty: bool = Field(False, description="Whether brief has no qualifying stories")
    empty_message: str | None = Field(
        None, description="Message if no stories: 'Insufficient qualifying stories in the last 24 hours.'"
    )


# Section display names (legacy 5-section)
SECTION_DISPLAY_NAMES = {
    "world": "World",
    "us": "U.S.",
    "local": "Local",
    "business": "Business & Markets",
    "technology": "Technology",
}

# Feed category display names (10-category)
FEED_CATEGORY_DISPLAY_NAMES = {
    "world": "World",
    "us": "U.S.",
    "local": "Local",
    "business": "Business",
    "technology": "Technology",
    "science": "Science",
    "health": "Health",
    "environment": "Environment",
    "sports": "Sports",
    "culture": "Culture",
}
