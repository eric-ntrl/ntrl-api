# app/schemas/stories.py
"""
Schemas for story endpoints.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class TransparencySpanResponse(BaseModel):
    """A single span of manipulative content that was modified."""
    model_config = ConfigDict(from_attributes=True)

    start_char: int = Field(..., description="Start position in original text")
    end_char: int = Field(..., description="End position in original text")
    original_text: str = Field(..., description="The original manipulative text")
    action: str = Field(..., description="removed|replaced|softened")
    reason: str = Field(..., description="Why this was flagged (e.g., clickbait, urgency_inflation)")
    replacement_text: Optional[str] = Field(None, description="Replacement text if replaced/softened")


class StoryDetail(BaseModel):
    """
    Story detail - shows filtered/neutralized content first.
    GET /v1/stories/{id}
    """
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Story ID (UUID)")

    # Feed outputs (for list views)
    feed_title: str = Field(..., description="Feed title, ≤6 words preferred, 12 max")
    feed_summary: str = Field(..., description="Feed summary, 1-2 sentences")

    # Detail outputs (for article view)
    detail_title: Optional[str] = Field(None, description="Precise article headline")
    detail_brief: Optional[str] = Field(None, description="3-5 paragraphs, prose, no headers")
    detail_full: Optional[str] = Field(None, description="Filtered full article")

    # Disclosure
    disclosure: str = Field("Manipulative language removed.", description="Disclosure message")
    has_manipulative_content: bool = Field(..., description="Whether manipulative content was found")

    # Source info
    source_name: str = Field(..., description="Source name")
    source_url: str = Field(..., description="Original source URL - always linked")
    published_at: datetime = Field(..., description="Original publish time")

    # Section
    section: Optional[str] = Field(None, description="Section classification")


class StoryTransparency(BaseModel):
    """
    Transparency view - shows what was removed and why.
    GET /v1/stories/{id}/transparency
    """
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Story ID (UUID)")

    # Original content (for comparison)
    original_title: str = Field(..., description="Original title as published")
    original_description: Optional[str] = Field(None, description="Original description")
    original_body: Optional[str] = Field(None, description="Original body text (from S3)")
    original_body_available: bool = Field(True, description="Whether body is available in storage")
    original_body_expired: bool = Field(False, description="Whether body has expired per retention policy")

    # Filtered outputs for comparison
    feed_title: str = Field(..., description="Filtered feed title")
    feed_summary: str = Field(..., description="Filtered feed summary")
    detail_full: Optional[str] = Field(None, description="Filtered full article (ntrl view applies here)")

    # What was changed
    spans: List[TransparencySpanResponse] = Field(
        default_factory=list,
        description="List of manipulative spans that were modified"
    )

    # Metadata
    disclosure: str = Field("Manipulative language removed.")
    has_manipulative_content: bool
    source_url: str = Field(..., description="Link to original source")

    # Processing info
    model_name: Optional[str] = Field(None, description="Model used for neutralization")
    prompt_version: Optional[str] = Field(None, description="Prompt version used")
    processed_at: datetime = Field(..., description="When neutralization was performed")
