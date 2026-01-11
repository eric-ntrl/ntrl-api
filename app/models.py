# app/models.py
"""
NTRL Phase-1 POC Database Models

Tables:
- Source: RSS feed sources (fixed set for POC)
- StoryRaw: Raw articles exactly as published
- StoryNeutralized: Neutralized summaries, versioned
- TransparencySpan: What was removed/changed and why
- DailyBrief: Snapshot of assembled daily briefs
- DailyBriefItem: Stories in each brief, ordered
- PipelineLog: Audit trail for pipeline steps
"""

from datetime import datetime
from enum import Enum
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------

class Section(str, Enum):
    """Fixed sections for daily brief (deterministic order)."""
    WORLD = "world"
    US = "us"
    LOCAL = "local"
    BUSINESS = "business"
    TECHNOLOGY = "technology"


# Section ordering for deterministic briefs
SECTION_ORDER = {
    Section.WORLD: 0,
    Section.US: 1,
    Section.LOCAL: 2,
    Section.BUSINESS: 3,
    Section.TECHNOLOGY: 4,
}


class SpanAction(str, Enum):
    """What was done to the manipulative text."""
    REMOVED = "removed"
    REPLACED = "replaced"
    SOFTENED = "softened"


class SpanReason(str, Enum):
    """Why the text was flagged as manipulative."""
    CLICKBAIT = "clickbait"
    URGENCY_INFLATION = "urgency_inflation"
    EMOTIONAL_TRIGGER = "emotional_trigger"
    SELLING = "selling"
    AGENDA_SIGNALING = "agenda_signaling"
    RHETORICAL_FRAMING = "rhetorical_framing"


class PipelineStage(str, Enum):
    """Pipeline stages for logging."""
    INGEST = "ingest"
    NORMALIZE = "normalize"
    DEDUPE = "dedupe"
    NEUTRALIZE = "neutralize"
    CLASSIFY = "classify"
    BRIEF_ASSEMBLE = "brief_assemble"


class PipelineStatus(str, Enum):
    """Pipeline step status."""
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# -----------------------------------------------------------------------------
# Source
# -----------------------------------------------------------------------------

class Source(Base):
    """RSS feed sources - fixed set for POC."""
    __tablename__ = "sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(64), unique=True, nullable=False)  # e.g., "ap", "reuters"
    rss_url = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    default_section = Column(String(32), nullable=True)  # Hint for classification
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    stories = relationship("StoryRaw", back_populates="source")


# -----------------------------------------------------------------------------
# StoryRaw
# -----------------------------------------------------------------------------

class StoryRaw(Base):
    """
    Raw articles - metadata stored in Postgres, body content in S3.

    Storage strategy:
    - Title/description stored in Postgres (used for display/dedupe)
    - Full body content stored in S3 (compressed)
    - Postgres stores only S3 references for body
    - Raw content may expire per retention policy
    - Metadata, summaries, and transparency spans persist
    """
    __tablename__ = "stories_raw"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)

    # Metadata stored in Postgres (for display and dedupe)
    original_url = Column(Text, nullable=False)
    original_title = Column(Text, nullable=False)
    original_description = Column(Text, nullable=True)  # Short, kept in Postgres
    original_author = Column(String(255), nullable=True)

    # S3 references for raw body content (not stored in Postgres)
    raw_content_uri = Column(String(512), nullable=True)  # S3 object key
    raw_content_hash = Column(String(64), nullable=True)  # SHA256 of extracted text
    raw_content_type = Column(String(64), nullable=True)  # e.g., "text/plain"
    raw_content_encoding = Column(String(16), nullable=True)  # e.g., "gzip"
    raw_content_size = Column(Integer, nullable=True)  # Original size in bytes

    # Lifecycle management
    raw_content_available = Column(Boolean, default=True, nullable=False)
    raw_content_expired_at = Column(DateTime, nullable=True)

    # Normalized fields for processing
    url_hash = Column(String(64), nullable=False)  # SHA256 of URL for dedupe
    title_hash = Column(String(64), nullable=False)  # SHA256 of normalized title
    published_at = Column(DateTime, nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Classification (set during pipeline)
    section = Column(String(32), nullable=True)  # Section enum value
    is_duplicate = Column(Boolean, default=False, nullable=False)
    duplicate_of_id = Column(UUID(as_uuid=True), ForeignKey("stories_raw.id"), nullable=True)

    # Minimal metadata (no full raw_payload to save space)
    feed_entry_id = Column(String(512), nullable=True)  # RSS entry ID if available

    # Relationships
    source = relationship("Source", back_populates="stories")
    neutralized = relationship("StoryNeutralized", back_populates="story_raw",
                               order_by="desc(StoryNeutralized.version)")
    duplicate_of = relationship("StoryRaw", remote_side=[id])

    __table_args__ = (
        Index("ix_stories_raw_url_hash", "url_hash"),
        Index("ix_stories_raw_title_hash", "title_hash"),
        Index("ix_stories_raw_published_at", "published_at"),
        Index("ix_stories_raw_section", "section"),
        Index("ix_stories_raw_ingested_at", "ingested_at"),
        Index("ix_stories_raw_content_available", "raw_content_available"),
    )


# -----------------------------------------------------------------------------
# StoryNeutralized
# -----------------------------------------------------------------------------

class StoryNeutralized(Base):
    """Neutralized summaries, versioned separately from raw."""
    __tablename__ = "stories_neutralized"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_raw_id = Column(UUID(as_uuid=True), ForeignKey("stories_raw.id"), nullable=False)

    # Version control
    version = Column(Integer, default=1, nullable=False)
    is_current = Column(Boolean, default=True, nullable=False)

    # Neutralized content
    neutral_headline = Column(Text, nullable=False)  # 1 line, no hype
    neutral_summary = Column(Text, nullable=False)   # 2-3 lines max

    # What the summary answers (structured)
    what_happened = Column(Text, nullable=True)
    why_it_matters = Column(Text, nullable=True)
    what_is_known = Column(Text, nullable=True)
    what_is_uncertain = Column(Text, nullable=True)

    # Disclosure
    disclosure = Column(String(255), default="Manipulative language removed.", nullable=False)
    has_manipulative_content = Column(Boolean, default=False, nullable=False)

    # Model/prompt tracking
    model_name = Column(String(128), nullable=True)
    prompt_version = Column(String(64), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    story_raw = relationship("StoryRaw", back_populates="neutralized")
    spans = relationship("TransparencySpan", back_populates="story_neutralized",
                        order_by="TransparencySpan.start_char")

    __table_args__ = (
        UniqueConstraint("story_raw_id", "version", name="uq_story_version"),
        Index("ix_stories_neutralized_is_current", "is_current"),
    )


# -----------------------------------------------------------------------------
# TransparencySpan
# -----------------------------------------------------------------------------

class TransparencySpan(Base):
    """What was removed/changed and why - for transparency view."""
    __tablename__ = "transparency_spans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_neutralized_id = Column(UUID(as_uuid=True),
                                   ForeignKey("stories_neutralized.id"), nullable=False)

    # Position in original text
    field = Column(String(32), nullable=False)  # "title", "description", "body"
    start_char = Column(Integer, nullable=False)
    end_char = Column(Integer, nullable=False)

    # What was there and what happened
    original_text = Column(Text, nullable=False)
    action = Column(String(16), nullable=False)  # SpanAction enum
    reason = Column(String(32), nullable=False)  # SpanReason enum
    replacement_text = Column(Text, nullable=True)  # For replaced/softened

    # Relationships
    story_neutralized = relationship("StoryNeutralized", back_populates="spans")

    __table_args__ = (
        Index("ix_transparency_spans_story", "story_neutralized_id"),
    )


# -----------------------------------------------------------------------------
# DailyBrief
# -----------------------------------------------------------------------------

class DailyBrief(Base):
    """Snapshot of assembled daily briefs - deterministic."""
    __tablename__ = "daily_briefs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Brief identity
    brief_date = Column(DateTime, nullable=False)  # Date this brief covers
    version = Column(Integer, default=1, nullable=False)

    # Metadata
    total_stories = Column(Integer, default=0, nullable=False)
    cutoff_time = Column(DateTime, nullable=False)  # Stories before this time
    is_current = Column(Boolean, default=True, nullable=False)

    # Empty state
    is_empty = Column(Boolean, default=False, nullable=False)
    empty_reason = Column(String(255), nullable=True)

    # Assembly metadata
    assembled_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    assembly_duration_ms = Column(Integer, nullable=True)

    # Relationships
    items = relationship("DailyBriefItem", back_populates="brief",
                        order_by="DailyBriefItem.section_order, DailyBriefItem.position")

    __table_args__ = (
        Index("ix_daily_briefs_date", "brief_date"),
        Index("ix_daily_briefs_is_current", "is_current"),
    )


# -----------------------------------------------------------------------------
# DailyBriefItem
# -----------------------------------------------------------------------------

class DailyBriefItem(Base):
    """Stories in each brief, with deterministic ordering."""
    __tablename__ = "daily_brief_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brief_id = Column(UUID(as_uuid=True), ForeignKey("daily_briefs.id"), nullable=False)
    story_neutralized_id = Column(UUID(as_uuid=True),
                                   ForeignKey("stories_neutralized.id"), nullable=False)

    # Ordering
    section = Column(String(32), nullable=False)  # Section enum
    section_order = Column(Integer, nullable=False)  # 0=world, 1=us, etc.
    position = Column(Integer, nullable=False)  # Position within section

    # Denormalized for fast reads
    neutral_headline = Column(Text, nullable=False)
    neutral_summary = Column(Text, nullable=False)
    source_name = Column(String(255), nullable=False)
    original_url = Column(Text, nullable=False)
    published_at = Column(DateTime, nullable=False)
    has_manipulative_content = Column(Boolean, default=False, nullable=False)

    # Relationships
    brief = relationship("DailyBrief", back_populates="items")
    story_neutralized = relationship("StoryNeutralized")

    __table_args__ = (
        Index("ix_brief_items_brief_section", "brief_id", "section"),
    )


# -----------------------------------------------------------------------------
# PipelineLog
# -----------------------------------------------------------------------------

class PipelineLog(Base):
    """Audit trail for pipeline steps."""
    __tablename__ = "pipeline_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # What ran
    stage = Column(String(32), nullable=False)  # PipelineStage enum
    status = Column(String(16), nullable=False)  # PipelineStatus enum

    # Context
    story_raw_id = Column(UUID(as_uuid=True), ForeignKey("stories_raw.id"), nullable=True)
    brief_id = Column(UUID(as_uuid=True), ForeignKey("daily_briefs.id"), nullable=True)

    # Details
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    log_metadata = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_pipeline_logs_stage", "stage"),
        Index("ix_pipeline_logs_started_at", "started_at"),
    )


# -----------------------------------------------------------------------------
# Prompt
# -----------------------------------------------------------------------------

class Prompt(Base):
    """
    Prompts for LLM operations - stored in DB for hot-reload without redeploy.

    For fast iteration during development. Version column tracks changes
    but we overwrite rather than insert (true versioning comes later).
    """
    __tablename__ = "prompts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(64), unique=True, nullable=False)  # e.g., "system_prompt", "user_prompt"
    content = Column(Text, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
