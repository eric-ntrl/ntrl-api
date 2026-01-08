# app/schemas/stories.py
"""
Schemas for story endpoints.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class TransparencySpanResponse(BaseModel):
    """A single span of manipulative content that was modified."""
    start_char: int = Field(..., description="Start position in original text")
    end_char: int = Field(..., description="End position in original text")
    original_text: str = Field(..., description="The original manipulative text")
    action: str = Field(..., description="removed|replaced|softened")
    reason: str = Field(..., description="Why this was flagged (e.g., clickbait, urgency_inflation)")
    replacement_text: Optional[str] = Field(None, description="Replacement text if replaced/softened")

    class Config:
        from_attributes = True


class StoryDetail(BaseModel):
    """
    Story detail - shows filtered/neutralized content first.
    GET /v1/stories/{id}
    """
    id: str = Field(..., description="Story ID (UUID)")

    # Neutralized content (shown first)
    neutral_headline: str = Field(..., description="Neutral headline, no hype")
    neutral_summary: str = Field(..., description="Neutral summary, 2-3 lines max")

    # Structured summary
    what_happened: Optional[str] = Field(None, description="What happened")
    why_it_matters: Optional[str] = Field(None, description="Why it matters")
    what_is_known: Optional[str] = Field(None, description="What is known")
    what_is_uncertain: Optional[str] = Field(None, description="What is uncertain")

    # Disclosure
    disclosure: str = Field("Manipulative language removed.", description="Disclosure message")
    has_manipulative_content: bool = Field(..., description="Whether manipulative content was found")

    # Source info
    source_name: str = Field(..., description="Source name")
    source_url: str = Field(..., description="Original source URL - always linked")
    published_at: datetime = Field(..., description="Original publish time")

    # Section
    section: Optional[str] = Field(None, description="Section classification")

    class Config:
        from_attributes = True


class StoryTransparency(BaseModel):
    """
    Transparency view - shows what was removed and why.
    GET /v1/stories/{id}/transparency
    """
    id: str = Field(..., description="Story ID (UUID)")

    # Original content (for comparison)
    original_title: str = Field(..., description="Original title as published")
    original_description: Optional[str] = Field(None, description="Original description")
    original_body: Optional[str] = Field(None, description="Original body text (from S3)")
    original_body_available: bool = Field(True, description="Whether body is available in storage")
    original_body_expired: bool = Field(False, description="Whether body has expired per retention policy")

    # Neutralized for comparison
    neutral_headline: str = Field(..., description="Neutralized headline")
    neutral_summary: str = Field(..., description="Neutralized summary")

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

    class Config:
        from_attributes = True
