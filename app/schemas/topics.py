# app/schemas/topics.py
"""
Schemas for trending topics endpoint.

GET /v1/topics/trending - Returns trending topics from recent articles
"""

from datetime import datetime

from pydantic import BaseModel, Field


class TrendingTopic(BaseModel):
    """A single trending topic extracted from recent articles."""

    term: str = Field(..., description="The trending term/phrase (lowercase)")
    label: str = Field(..., description="Display label (title case)")
    count: int = Field(..., description="Number of articles mentioning this topic")
    sample_headline: str | None = Field(None, description="A sample headline featuring this topic")


class TrendingTopicsResponse(BaseModel):
    """Response from the trending topics endpoint."""

    topics: list[TrendingTopic] = Field(default_factory=list, description="List of trending topics sorted by count")
    generated_at: datetime = Field(..., description="When this list was generated")
    window_hours: int = Field(24, description="Time window in hours for trending calculation")
