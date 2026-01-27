# app/schemas/admin.py
"""
Schemas for admin pipeline endpoints.
"""

from datetime import datetime
from typing import List, Optional, Any
from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Ingest
# -----------------------------------------------------------------------------

class IngestRunRequest(BaseModel):
    """Request to trigger ingestion."""
    source_slugs: Optional[List[str]] = Field(
        None,
        description="Specific sources to ingest (default: all active)"
    )
    max_items_per_source: int = Field(
        20,
        ge=1,
        le=100,
        description="Max items to ingest per source"
    )


class IngestSourceResult(BaseModel):
    """Result for a single source."""
    source_slug: str
    source_name: str
    ingested: int
    skipped_duplicate: int
    errors: List[str] = Field(default_factory=list)


class IngestRunResponse(BaseModel):
    """Response from ingestion run."""
    status: str = Field(..., description="completed|partial|failed")
    started_at: datetime
    finished_at: datetime
    duration_ms: int

    # Results
    sources_processed: int
    total_ingested: int
    total_skipped_duplicate: int
    source_results: List[IngestSourceResult] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Neutralize
# -----------------------------------------------------------------------------

class NeutralizeRunRequest(BaseModel):
    """Request to trigger neutralization."""
    story_ids: Optional[List[str]] = Field(
        None,
        description="Specific story IDs to neutralize (default: all pending)"
    )
    force: bool = Field(
        False,
        description="Re-neutralize even if already processed"
    )
    limit: int = Field(
        50,
        ge=1,
        le=200,
        description="Max stories to process"
    )
    max_workers: int = Field(
        5,
        ge=1,
        le=10,
        description="Number of parallel workers for LLM calls"
    )


class NeutralizeStoryResult(BaseModel):
    """Result for a single story."""
    story_id: str
    status: str  # completed|skipped|failed
    feed_title: Optional[str] = None
    has_manipulative_content: bool = False
    span_count: int = 0
    error: Optional[str] = None


class NeutralizeRunResponse(BaseModel):
    """Response from neutralization run."""
    status: str = Field(..., description="completed|partial|failed")
    started_at: datetime
    finished_at: datetime
    duration_ms: int

    # Results
    total_processed: int
    total_skipped: int
    total_failed: int
    story_results: List[NeutralizeStoryResult] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Classify
# -----------------------------------------------------------------------------

class ClassifyRunRequest(BaseModel):
    """Request to trigger article classification."""
    limit: int = Field(
        25,
        ge=1,
        le=500,
        description="Max stories to classify"
    )
    force: bool = Field(
        False,
        description="Reclassify already-classified articles"
    )
    story_ids: Optional[List[str]] = Field(
        None,
        description="Specific story IDs to classify (default: all pending)"
    )


class ClassifyRunResponse(BaseModel):
    """Response from classification run."""
    status: str = Field(..., description="completed|empty|failed")
    started_at: datetime
    finished_at: datetime
    duration_ms: int

    # Results
    classify_total: int = 0
    classify_success: int = 0
    classify_llm: int = 0
    classify_keyword_fallback: int = 0
    classify_failed: int = 0

    # Errors
    errors: List[str] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Brief Assembly
# -----------------------------------------------------------------------------

class BriefRunRequest(BaseModel):
    """Request to trigger brief assembly."""
    force: bool = Field(
        False,
        description="Reassemble even if current brief exists"
    )
    cutoff_hours: int = Field(
        24,
        ge=1,
        le=72,
        description="Hours to look back for stories"
    )


class BriefSectionResult(BaseModel):
    """Result for a section."""
    section: str
    story_count: int


class BriefRunResponse(BaseModel):
    """Response from brief assembly."""
    status: str = Field(..., description="completed|empty|failed")
    started_at: datetime
    finished_at: datetime
    duration_ms: int

    # Brief info
    brief_id: Optional[str] = None
    brief_date: Optional[datetime] = None
    cutoff_time: Optional[datetime] = None
    total_stories: int = 0
    is_empty: bool = False
    empty_reason: Optional[str] = None

    # Section breakdown
    sections: List[BriefSectionResult] = Field(default_factory=list)

    # Errors
    error: Optional[str] = None
