from datetime import datetime
import uuid

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    JSON,
    Integer,
    Float,
)

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Source(Base):
    __tablename__ = "sources"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    domain = Column(String(255), nullable=False, unique=True)
    api_identifier = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    articles = relationship("ArticleRaw", back_populates="source")


class ArticleRaw(Base):
    __tablename__ = "articles_raw"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = Column(UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False)
    external_id = Column(String(512), nullable=True)
    original_title = Column(Text, nullable=False)
    original_description = Column(Text, nullable=True)
    original_body = Column(Text, nullable=True)
    source_url = Column(Text, nullable=False)
    language = Column(String(10), default="en", nullable=False)
    published_at = Column(DateTime, nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    raw_payload = Column(JSON, nullable=True)

    source = relationship("Source", back_populates="articles")
    summaries = relationship("ArticleSummary", back_populates="article_raw")
    cluster_links = relationship("ClusterArticle", back_populates="article_raw")


class ArticleSummary(Base):
    __tablename__ = "article_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_raw_id = Column(
        UUID(as_uuid=True), ForeignKey("articles_raw.id"), nullable=False
    )

    # Pipeline / model metadata
    version_tag = Column(String(64), nullable=False)
    model_name = Column(String(128), nullable=False)
    prompt_version = Column(String(64), nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Neutral summaries
    neutral_title = Column(Text, nullable=False)
    neutral_summary_short = Column(Text, nullable=False)
    neutral_summary_extended = Column(Text, nullable=True)

    # Quality / safety flags
    tone_flag = Column(Boolean, default=False, nullable=False)
    tone_issues = Column(JSON, nullable=True)
    misinfo_flag = Column(Boolean, default=False, nullable=False)
    misinfo_notes = Column(JSON, nullable=True)
    is_current = Column(Boolean, default=False, nullable=False)

    # Neutrality scoring (Phase 2)
    neutrality_score = Column(Integer, nullable=True)
    bias_terms = Column(JSON, nullable=True)
    reading_level = Column(Integer, nullable=True)
    political_lean = Column(Float, nullable=True)

    # NEW: bias spans for “redline” highlighting later (nullable for now)
    # Example:
    # [
    #   {"start": 12, "end": 25, "label": "clickbait", "severity": 0.7, "text": "shocking"},
    #   {"start": 80, "end": 96, "label": "hyperbole", "severity": 0.6, "text": "you won’t believe"}
    # ]
    bias_spans = Column(JSON, nullable=True)

    article_raw = relationship("ArticleRaw", back_populates="summaries")


class ArticleCluster(Base):
    __tablename__ = "article_clusters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_title = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    articles = relationship("ClusterArticle", back_populates="cluster")


class ClusterArticle(Base):
    __tablename__ = "cluster_articles"

    cluster_id = Column(
        UUID(as_uuid=True), ForeignKey("article_clusters.id"), primary_key=True
    )
    article_raw_id = Column(
        UUID(as_uuid=True), ForeignKey("articles_raw.id"), primary_key=True
    )
    is_primary = Column(Boolean, default=False, nullable=False)
    added_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    cluster = relationship("ArticleCluster", back_populates="articles")
    article_raw = relationship("ArticleRaw", back_populates="cluster_links")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_raw_id = Column(
        UUID(as_uuid=True), ForeignKey("articles_raw.id"), nullable=False
    )
    stage = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    model_name = Column(String(128), nullable=True)
    prompt_version = Column(String(64), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    extra_metadata = Column(JSON, nullable=True)


class SystemPrompt(Base):
    __tablename__ = "system_prompts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(128), nullable=False)
    version_tag = Column(String(64), nullable=False)
    prompt_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
