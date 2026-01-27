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
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship

from app.database import Base


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------

class Section(str, Enum):
    """Fixed sections for daily brief (deterministic order). Legacy — see FeedCategory."""
    WORLD = "world"
    US = "us"
    LOCAL = "local"
    BUSINESS = "business"
    TECHNOLOGY = "technology"


# Section ordering for deterministic briefs (legacy — see FEED_CATEGORY_ORDER)
SECTION_ORDER = {
    Section.WORLD: 0,
    Section.US: 1,
    Section.LOCAL: 2,
    Section.BUSINESS: 3,
    Section.TECHNOLOGY: 4,
}


class Domain(str, Enum):
    """20 internal editorial domains (system-only, not user-facing)."""
    GLOBAL_AFFAIRS = "global_affairs"
    GOVERNANCE_POLITICS = "governance_politics"
    LAW_JUSTICE = "law_justice"
    SECURITY_DEFENSE = "security_defense"
    CRIME_PUBLIC_SAFETY = "crime_public_safety"
    ECONOMY_MACROECONOMICS = "economy_macroeconomics"
    FINANCE_MARKETS = "finance_markets"
    BUSINESS_INDUSTRY = "business_industry"
    LABOR_DEMOGRAPHICS = "labor_demographics"
    INFRASTRUCTURE_SYSTEMS = "infrastructure_systems"
    ENERGY = "energy"
    ENVIRONMENT_CLIMATE = "environment_climate"
    SCIENCE_RESEARCH = "science_research"
    HEALTH_MEDICINE = "health_medicine"
    TECHNOLOGY = "technology"
    MEDIA_INFORMATION = "media_information"
    SPORTS_COMPETITION = "sports_competition"
    SOCIETY_CULTURE = "society_culture"
    LIFESTYLE_PERSONAL = "lifestyle_personal"
    INCIDENTS_DISASTERS = "incidents_disasters"


class FeedCategory(str, Enum):
    """10 user-facing feed categories."""
    WORLD = "world"
    US = "us"
    LOCAL = "local"
    BUSINESS = "business"
    TECHNOLOGY = "technology"
    SCIENCE = "science"
    HEALTH = "health"
    ENVIRONMENT = "environment"
    SPORTS = "sports"
    CULTURE = "culture"


FEED_CATEGORY_ORDER = {
    FeedCategory.WORLD: 0,
    FeedCategory.US: 1,
    FeedCategory.LOCAL: 2,
    FeedCategory.BUSINESS: 3,
    FeedCategory.TECHNOLOGY: 4,
    FeedCategory.SCIENCE: 5,
    FeedCategory.HEALTH: 6,
    FeedCategory.ENVIRONMENT: 7,
    FeedCategory.SPORTS: 8,
    FeedCategory.CULTURE: 9,
}


FEED_CATEGORY_DISPLAY = {
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
    EDITORIAL_VOICE = "editorial_voice"  # First-person opinion markers in news


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


class NeutralizationStatus(str, Enum):
    """Status of neutralization processing."""
    SUCCESS = "success"
    FAILED_LLM = "failed_llm"           # LLM API error
    FAILED_AUDIT = "failed_audit"       # Audit verdict FAIL
    FAILED_GARBLED = "failed_garbled"   # Output was garbled
    SKIPPED = "skipped"                 # Audit verdict SKIP


# -----------------------------------------------------------------------------
# Source
# -----------------------------------------------------------------------------

class Source(Base):
    """
    RSS feed sources tracked by the NTRL pipeline.

    Each Source represents a single RSS feed URL (e.g., AP Top News, Reuters World)
    from which articles are periodically ingested. Sources are a fixed set during
    the POC phase and are toggled via the is_active flag rather than added or removed
    at runtime.

    Created manually (seed data) before any pipeline run.

    Relationships:
        stories -> StoryRaw: One-to-many. Every ingested article references the
            Source it was pulled from.
    """
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
    Ingested articles from RSS feeds -- the single source of truth for each story.

    A StoryRaw row is created during the INGEST pipeline stage whenever a new RSS
    entry is discovered. Article metadata (title, description, URL) is stored in
    Postgres while the full article body is scraped and stored in S3 as plain text.
    The body in S3 is the canonical text that all downstream stages operate on:
    CLASSIFY reads it to assign domain/feed_category, and NEUTRALIZE reads it to
    produce every user-facing output (feed title, summary, detail brief, detail
    full, and transparency spans).

    Storage strategy:
        - Title/description stored in Postgres (used for display and dedupe).
        - Full body content stored in S3 (compressed).
        - Postgres stores only S3 references for the body.
        - Raw content may expire per retention policy; metadata persists.

    Relationships:
        source -> Source: Many-to-one. The RSS feed this article came from.
        neutralized -> StoryNeutralized: One-to-many (versioned). Each
            neutralization pass produces a new StoryNeutralized row.
        duplicate_of -> StoryRaw: Self-referential. Points to the canonical
            article when this row is flagged as a duplicate during DEDUPE.
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

    # Classification (set during ingestion — keyword heuristic)
    section = Column(String(32), nullable=True)  # Legacy Section enum value

    # Classification results (populated by CLASSIFY pipeline stage)
    domain = Column(String(40), nullable=True)                  # Internal domain (20 values)
    feed_category = Column(String(32), nullable=True)           # User-facing category (10 values)
    classification_tags = Column(JSONB, nullable=True)          # {geography, actors, action_type, ...}
    classification_confidence = Column(Float, nullable=True)    # 0.0-1.0
    classification_model = Column(String(64), nullable=True)    # "gpt-4o-mini", "gemini-2.0-flash", etc.
    classification_method = Column(String(20), nullable=True)   # "llm" or "keyword_fallback"
    classified_at = Column(DateTime(timezone=True), nullable=True)

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
        Index("ix_stories_raw_domain", "domain"),
        Index("ix_stories_raw_feed_category", "feed_category"),
        Index("ix_stories_raw_classified_at", "classified_at"),
        Index("ix_stories_raw_classification_method", "classification_method"),
    )


# -----------------------------------------------------------------------------
# StoryNeutralized
# -----------------------------------------------------------------------------

class StoryNeutralized(Base):
    """
    Neutralized version of an article, produced during the NEUTRALIZE pipeline stage.

    For each StoryRaw, the neutralizer reads the original body from S3 and asks
    an LLM to produce several outputs: a short feed title and summary (for list
    views), a detail title and multi-paragraph brief (for the article detail
    screen), and a filtered full-length article (detail_full). Each output is
    derived solely from the original body -- RSS titles and descriptions are never
    used for generation.

    Rows are versioned per story so that re-neutralization (e.g., after a prompt
    change) creates a new version while preserving earlier results. Only the row
    with is_current=True is served to clients.

    The neutralization_status field tracks whether the LLM call succeeded,
    failed, or produced garbled output. Only rows with status "success" appear
    in briefs and story listings.

    Relationships:
        story_raw -> StoryRaw: Many-to-one. The original article this was
            derived from.
        spans -> TransparencySpan: One-to-many. UI-oriented spans highlighting
            manipulative phrases removed or softened during neutralization.
        manipulation_spans -> ManipulationSpan: One-to-many. Taxonomy-bound
            spans from the NTRL-SCAN structural/lexical analysis pipeline.
    """
    __tablename__ = "stories_neutralized"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_raw_id = Column(UUID(as_uuid=True), ForeignKey("stories_raw.id"), nullable=False)

    # Version control
    version = Column(Integer, default=1, nullable=False)
    is_current = Column(Boolean, default=True, nullable=False)

    # Feed outputs (for list views)
    feed_title = Column(Text, nullable=False)       # ≤6 words preferred, 12 max
    feed_summary = Column(Text, nullable=False)     # 1-2 sentences, ≤3 lines

    # Detail outputs (for article view)
    detail_title = Column(Text, nullable=True)      # Precise article headline
    detail_brief = Column(Text, nullable=True)      # 3-5 paragraphs, prose, no headers
    detail_full = Column(Text, nullable=True)       # Filtered full article

    # Disclosure
    disclosure = Column(String(255), default="Manipulative language removed.", nullable=False)
    has_manipulative_content = Column(Boolean, default=False, nullable=False)

    # Model/prompt tracking
    model_name = Column(String(128), nullable=True)
    prompt_version = Column(String(64), nullable=True)

    # Neutralization status tracking
    neutralization_status = Column(String(50), default="success", nullable=False)
    failure_reason = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    story_raw = relationship("StoryRaw", back_populates="neutralized")
    spans = relationship("TransparencySpan", back_populates="story_neutralized",
                        order_by="TransparencySpan.start_char")
    manipulation_spans = relationship(
        "ManipulationSpan",
        back_populates="story_neutralized",
        order_by="ManipulationSpan.span_start"
    )

    __table_args__ = (
        UniqueConstraint("story_raw_id", "version", name="uq_story_version"),
        Index("ix_stories_neutralized_is_current", "is_current"),
        Index("ix_stories_neutralized_status", "neutralization_status"),
    )


# -----------------------------------------------------------------------------
# TransparencySpan
# -----------------------------------------------------------------------------

class TransparencySpan(Base):
    """
    A span highlighting a manipulative phrase in the original article text,
    intended for display in the ntrl-view UI.

    TransparencySpans are created during the NEUTRALIZE pipeline stage. After the
    LLM produces the neutralized outputs, a separate span-detection pass
    identifies manipulative phrases in the original body and records what action
    was taken (removed, replaced, or softened) and why (clickbait, emotional
    trigger, urgency inflation, etc.). The frontend uses these spans to render
    colour-coded highlights over the original text so readers can see exactly
    what was changed.

    Each span stores character offsets (start_char, end_char) into the original
    text of a specific field (title, description, or body). Offsets always
    reference the original article text, never the neutralized output.

    Distinction from ManipulationSpan:
        TransparencySpan is the UI-facing model. It uses a simple action/reason
        taxonomy (SpanAction and SpanReason enums) and is optimised for rendering
        highlights in the ntrl-view. It is produced by the LLM span-detection
        prompt during the NEUTRALIZE stage.

        ManipulationSpan (see below) is the analysis-facing model from the
        NTRL-SCAN pipeline. It carries a richer taxonomy (type_id from
        taxonomy.py with 115 manipulation types), severity scoring, detector
        provenance, and exemption metadata. The two models may coexist for the
        same article.

    Relationships:
        story_neutralized -> StoryNeutralized: Many-to-one. The neutralized
            version these spans annotate.
    """
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
# ManipulationSpan (NTRL Filter v2)
# -----------------------------------------------------------------------------

class ManipulationSpan(Base):
    """
    A detected manipulation span from the NTRL-SCAN pipeline's structural and
    lexical analysis (NTRL Filter v2).

    Unlike TransparencySpan, which is a lightweight UI model created during the
    NEUTRALIZE stage, ManipulationSpan captures the full analytical output of
    the NTRL-SCAN pipeline. Each row binds to one or more entries in the 115-type
    manipulation taxonomy (app/taxonomy.py) via type_id_primary and
    type_ids_secondary, and includes severity scoring (raw and segment-weighted),
    detection confidence, the action taken (remove/replace/rewrite/annotate/
    preserve), and provenance metadata (which detector found it, which guardrail
    exemptions applied, which rewrite template was used).

    Spans reference character offsets (span_start, span_end) within a named
    segment of the original article (title, deck, lede, body, or caption).
    Offsets always point into the original text, not the neutralized output.

    Distinction from TransparencySpan:
        TransparencySpan is created by the LLM span-detection prompt during
        NEUTRALIZE and is designed for simple UI highlighting with a small
        action/reason enum. ManipulationSpan is created by the NTRL-SCAN
        pipeline's multi-detector analysis (lexical, structural, semantic) and
        carries richer taxonomy, scoring, and audit fields. Both may coexist
        for the same neutralized article.

    Relationships:
        story_neutralized -> StoryNeutralized: Many-to-one. The neutralized
            version this span annotates.
    """
    __tablename__ = "manipulation_spans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    story_neutralized_id = Column(
        UUID(as_uuid=True),
        ForeignKey("stories_neutralized.id"),
        nullable=False
    )

    # Taxonomy binding (references app/taxonomy.py)
    type_id_primary = Column(String(10), nullable=False)    # e.g., "A.1.1"
    type_ids_secondary = Column(ARRAY(String), default=[])  # Additional types

    # Location in original text
    segment = Column(String(20), nullable=False)     # title/deck/lede/body/caption
    span_start = Column(Integer, nullable=False)     # Character index in segment
    span_end = Column(Integer, nullable=False)       # Exclusive end index
    original_text = Column(Text, nullable=False)     # Exact text that was flagged

    # Scoring
    confidence = Column(Float, nullable=False)       # Detection confidence (0-1)
    severity = Column(Integer, nullable=False)       # Base severity (1-5)
    severity_weighted = Column(Float, nullable=True) # After segment multiplier

    # Decision
    action = Column(String(20), nullable=False)      # remove/replace/rewrite/annotate/preserve
    rewritten_text = Column(Text, nullable=True)     # Result after action (if applicable)
    rationale = Column(Text, nullable=True)          # Brief explanation for transparency

    # Audit / Provenance
    detector_source = Column(String(20), nullable=False)  # lexical/structural/semantic
    exemptions_applied = Column(ARRAY(String), default=[])  # Guardrails that applied
    rewrite_template_id = Column(String(64), nullable=True)  # Template used (if any)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    story_neutralized = relationship(
        "StoryNeutralized",
        back_populates="manipulation_spans"
    )

    __table_args__ = (
        Index("ix_manipulation_spans_story", "story_neutralized_id"),
        Index("ix_manipulation_spans_type", "type_id_primary"),
        Index("ix_manipulation_spans_segment", "segment"),
        Index("ix_manipulation_spans_severity", "severity"),
    )


# -----------------------------------------------------------------------------
# DailyBrief
# -----------------------------------------------------------------------------

class DailyBrief(Base):
    """
    An assembled daily news brief -- a deterministic snapshot of top stories.

    A DailyBrief is created during the BRIEF_ASSEMBLE pipeline stage. It groups
    successfully neutralized stories by feed_category (10 user-facing categories:
    World, U.S., Local, Business, Technology, Science, Health, Environment,
    Sports, Culture) in a fixed display order. Only articles with
    neutralization_status "success" are included.

    Briefs are versioned per date so that rebuilding the brief (e.g., after new
    articles arrive) creates a new version while preserving the previous snapshot.
    The is_current flag marks the latest version for a given date; older versions
    remain in the database for audit.

    If no stories are available for a given run, the brief is marked as empty
    (is_empty=True) with a human-readable empty_reason.

    Relationships:
        items -> DailyBriefItem: One-to-many. The ordered list of stories in
            this brief, each carrying denormalized display fields for fast reads.
    """
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
    feed_title = Column(Text, nullable=False)
    feed_summary = Column(Text, nullable=False)
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
    """
    Audit log entry for a single pipeline stage execution.

    A PipelineLog row is written at the start and end of each pipeline stage
    (INGEST, NORMALIZE, DEDUPE, CLASSIFY, NEUTRALIZE, BRIEF_ASSEMBLE). It
    records timing, success/failure status, optional error details, and a
    trace_id that correlates all stages within a single pipeline run.

    For per-article observability, the entry_url and entry_url_hash fields
    allow tracing a specific RSS entry across pipeline stages without requiring
    a StoryRaw row (useful when ingestion itself fails before a row is created).

    Structured failure reasons (failure_reason) use a fixed vocabulary so that
    alerting rules can fire on specific error classes rather than parsing free-
    text error messages.

    Relationships:
        story_raw_id -> StoryRaw: Optional FK. Present when the log entry
            pertains to a specific article (e.g., neutralization of one story).
        brief_id -> DailyBrief: Optional FK. Present when the log entry
            pertains to a brief assembly run.
    """
    __tablename__ = "pipeline_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # What ran
    stage = Column(String(32), nullable=False)  # PipelineStage enum
    status = Column(String(16), nullable=False)  # PipelineStatus enum

    # Context
    story_raw_id = Column(UUID(as_uuid=True), ForeignKey("stories_raw.id"), nullable=True)
    brief_id = Column(UUID(as_uuid=True), ForeignKey("daily_briefs.id"), nullable=True)

    # Trace ID for correlating across pipeline stages
    trace_id = Column(String(36), nullable=True, index=True)

    # Entry-level tracking (for per-article observability)
    entry_url = Column(String(2048), nullable=True)
    entry_url_hash = Column(String(64), nullable=True, index=True)

    # Structured failure reason (from ExtractionFailureReason enum)
    failure_reason = Column(String(64), nullable=True)

    # Retry tracking
    retry_count = Column(Integer, default=0)

    # Details
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    log_metadata = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_pipeline_logs_stage", "stage"),
        Index("ix_pipeline_logs_started_at", "started_at"),
        Index("ix_pipeline_logs_trace_id", "trace_id"),
        Index("ix_pipeline_logs_entry_url_hash", "entry_url_hash"),
    )


# -----------------------------------------------------------------------------
# PipelineRunSummary
# -----------------------------------------------------------------------------

class PipelineRunSummary(Base):
    """
    Summary of a complete pipeline run (ingest -> neutralize -> brief).

    Created after each full pipeline run to track overall health metrics
    and enable alerting when thresholds are breached.
    """
    __tablename__ = "pipeline_run_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    trace_id = Column(String(36), nullable=False, unique=True, index=True)

    # Timing
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=False)
    duration_ms = Column(Integer, nullable=False)

    # Ingestion stats
    ingest_total = Column(Integer, default=0, nullable=False)
    ingest_success = Column(Integer, default=0, nullable=False)
    ingest_body_downloaded = Column(Integer, default=0, nullable=False)
    ingest_body_failed = Column(Integer, default=0, nullable=False)
    ingest_skipped_duplicate = Column(Integer, default=0, nullable=False)

    # Classification stats
    classify_total = Column(Integer, default=0, nullable=False)
    classify_success = Column(Integer, default=0, nullable=False)
    classify_llm = Column(Integer, default=0, nullable=False)
    classify_keyword_fallback = Column(Integer, default=0, nullable=False)
    classify_failed = Column(Integer, default=0, nullable=False)

    # Neutralization stats
    neutralize_total = Column(Integer, default=0, nullable=False)
    neutralize_success = Column(Integer, default=0, nullable=False)
    neutralize_skipped_no_body = Column(Integer, default=0, nullable=False)
    neutralize_failed = Column(Integer, default=0, nullable=False)

    # Brief stats
    brief_story_count = Column(Integer, default=0, nullable=False)
    brief_section_count = Column(Integer, default=0, nullable=False)

    # Overall status
    status = Column(String(20), nullable=False)  # "completed", "partial", "failed"

    # Alerts triggered (list of alert codes)
    alerts = Column(JSONB, default=[], nullable=False)

    # Trigger info
    trigger = Column(String(20), nullable=False)  # "scheduled", "manual", "api"

    __table_args__ = (
        Index("ix_pipeline_run_summaries_finished_at", "finished_at"),
        Index("ix_pipeline_run_summaries_status", "status"),
    )


# -----------------------------------------------------------------------------
# Prompt
# -----------------------------------------------------------------------------

class Prompt(Base):
    """
    Prompts for LLM operations - stored in DB for hot-reload without redeploy.

    For fast iteration during development. Version column tracks changes
    but we overwrite rather than insert (true versioning comes later).

    The model column allows per-model prompt tuning (e.g., different prompts
    for gpt-4o-mini vs gemini-2.0-flash). NULL model = generic fallback.
    """
    __tablename__ = "prompts"
    __table_args__ = (
        UniqueConstraint('name', 'model', name='prompts_name_model_key'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(64), nullable=False)  # e.g., "system_prompt", "user_prompt"
    model = Column(String(64), nullable=True)  # e.g., "gpt-4o-mini", "gemini-2.0-flash", NULL=generic
    content = Column(Text, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
