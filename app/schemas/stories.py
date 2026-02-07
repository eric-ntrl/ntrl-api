# app/schemas/stories.py
"""
Schemas for story endpoints.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TransparencySpanResponse(BaseModel):
    """A single span of manipulative content that was modified."""

    model_config = ConfigDict(from_attributes=True)

    field: str = Field("body", description="Which field contains this span: title, description, or body")
    start_char: int = Field(..., description="Start position in original text")
    end_char: int = Field(..., description="End position in original text")
    original_text: str = Field(..., description="The original manipulative text")
    action: str = Field(..., description="removed|replaced|softened")
    reason: str = Field(..., description="Why this was flagged (e.g., clickbait, urgency_inflation)")
    replacement_text: str | None = Field(None, description="Replacement text if replaced/softened")


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
    detail_title: str | None = Field(None, description="Precise article headline")
    detail_brief: str | None = Field(None, description="3-5 paragraphs, prose, no headers")
    detail_full: str | None = Field(None, description="Filtered full article")

    # Disclosure
    disclosure: str = Field("Manipulative language removed.", description="Disclosure message")
    has_manipulative_content: bool = Field(..., description="Whether manipulative content was found")

    # Source info
    source_name: str = Field(..., description="Source name")
    source_url: str = Field(..., description="Original source URL - always linked")
    published_at: datetime = Field(..., description="Original publish time")

    # Section
    section: str | None = Field(None, description="Section classification")


class StoryTransparency(BaseModel):
    """
    Transparency view - shows what was removed and why.
    GET /v1/stories/{id}/transparency
    """

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Story ID (UUID)")

    # Original content (for comparison)
    original_title: str = Field(..., description="Original title as published")
    original_description: str | None = Field(None, description="Original description")
    original_body: str | None = Field(None, description="Original body text (from S3)")
    original_body_available: bool = Field(True, description="Whether body is available in storage")
    original_body_expired: bool = Field(False, description="Whether body has expired per retention policy")

    # Filtered outputs for comparison
    feed_title: str = Field(..., description="Filtered feed title")
    feed_summary: str = Field(..., description="Filtered feed summary")
    detail_full: str | None = Field(None, description="Filtered full article (ntrl view applies here)")

    # What was changed
    spans: list[TransparencySpanResponse] = Field(
        default_factory=list, description="List of manipulative spans that were modified"
    )

    # Metadata
    disclosure: str = Field("Manipulative language removed.")
    has_manipulative_content: bool
    source_url: str = Field(..., description="Link to original source")

    # Processing info
    model_name: str | None = Field(None, description="Model used for neutralization")
    prompt_version: str | None = Field(None, description="Prompt version used")
    processed_at: datetime = Field(..., description="When neutralization was performed")


class StoryDebug(BaseModel):
    """
    Debug view - diagnostic info for troubleshooting content display issues.
    GET /v1/stories/{id}/debug
    """

    model_config = ConfigDict(from_attributes=True)

    story_id: str = Field(..., description="Story ID (UUID)")

    # Original content info
    original_body: str | None = Field(None, description="First 500 chars of original body from S3")
    original_body_length: int = Field(0, description="Total length of original body")
    original_body_available: bool = Field(False, description="Whether body is in storage")

    # Neutralized content info
    detail_full: str | None = Field(None, description="First 500 chars of detail_full")
    detail_full_length: int = Field(0, description="Total length of detail_full")
    detail_brief: str | None = Field(None, description="First 500 chars of detail_brief")
    detail_brief_length: int = Field(0, description="Total length of detail_brief")

    # Transparency spans info
    span_count: int = Field(0, description="Number of transparency spans")
    spans_sample: list[TransparencySpanResponse] = Field(
        default_factory=list, description="First 3 spans for debugging"
    )

    # Processing metadata
    model_used: str | None = Field(None, description="Model used for neutralization")
    has_manipulative_content: bool = Field(False, description="Whether manipulative content was detected")

    # Quality indicators
    detail_full_readable: bool = Field(True, description="Basic readability check for detail_full")
    issues: list[str] = Field(default_factory=list, description="Detected issues")


class PipelineTraceItem(BaseModel):
    """Phrase filtered out at some pipeline stage."""

    phrase: str = Field(..., description="The phrase text")
    reason: str | None = Field(None, description="Why it was filtered")


class PipelineTrace(BaseModel):
    """Trace of what happened to phrases through the filtering pipeline."""

    after_position_matching: int = Field(0, description="Span count after position matching")
    after_quote_filter: int = Field(0, description="Span count after quote filter")
    after_false_positive_filter: int = Field(0, description="Final span count")
    phrases_filtered_by_quotes: list[str] = Field(default_factory=list, description="Phrases removed by quote filter")
    phrases_filtered_as_false_positives: list[str] = Field(default_factory=list, description="Phrases removed as FPs")
    phrases_not_found_in_text: list[str] = Field(
        default_factory=list, description="Phrases LLM returned but not found in body"
    )


class LLMPhraseItem(BaseModel):
    """A phrase returned by the LLM."""

    phrase: str
    reason: str | None = None
    action: str | None = None
    replacement: str | None = None


class SpanDetectionDebug(BaseModel):
    """
    Debug view for span detection pipeline.
    GET /v1/stories/{id}/debug/spans

    Shows the full LLM response and what happened at each filtering stage.
    """

    story_id: str = Field(..., description="Story ID (UUID)")
    original_body_preview: str | None = Field(None, description="First 500 chars of original body")
    original_body_length: int = Field(0, description="Total length of original body")

    # LLM response
    llm_raw_response: str | None = Field(None, description="Raw JSON response from LLM")
    llm_phrases_count: int = Field(0, description="Number of phrases LLM returned")
    llm_phrases: list[LLMPhraseItem] = Field(default_factory=list, description="All phrases from LLM")

    # Pipeline trace
    pipeline_trace: PipelineTrace = Field(default_factory=PipelineTrace, description="Filtering pipeline trace")

    # Final result
    final_span_count: int = Field(0, description="Final number of spans after all filtering")
    final_spans: list[TransparencySpanResponse] = Field(default_factory=list, description="Final spans")

    # Metadata
    model_used: str | None = Field(None, description="Model used for span detection")
