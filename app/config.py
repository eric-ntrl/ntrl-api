# app/config.py
"""
Centralized configuration with validation.

Uses pydantic-settings to load and validate all environment variables at startup.
Fail fast with clear error messages if required config is missing.
"""

from functools import lru_cache
from typing import ClassVar

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    DATABASE_URL: str = Field(
        ...,
        description="PostgreSQL connection URL",
    )

    # Authentication
    ADMIN_API_KEY: str = Field(
        ...,
        description="API key for admin endpoints",
    )

    # LLM Providers
    OPENAI_API_KEY: str | None = Field(
        default=None,
        description="OpenAI API key for neutralization",
    )
    GOOGLE_API_KEY: str | None = Field(
        default=None,
        description="Google/Gemini API key",
    )
    GEMINI_API_KEY: str | None = Field(
        default=None,
        description="Alternative Gemini API key env var",
    )
    ANTHROPIC_API_KEY: str | None = Field(
        default=None,
        description="Anthropic API key",
    )

    # Neutralizer
    NEUTRALIZER_PROVIDER: str = Field(
        default="openai",
        description="Active neutralizer provider: openai, gemini, anthropic, mock",
    )
    OPENAI_MODEL: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model to use for neutralization",
    )
    DETAIL_FULL_MODEL: str = Field(
        default="",
        description="Override model for detail_full neutralization (e.g., gpt-5-mini). Empty = use OPENAI_MODEL.",
    )
    SPAN_DETECTION_MODEL: str = Field(
        default="gpt-5-mini",
        description="OpenAI model for span detection (supports gpt-5-mini, gpt-5.1, gpt-4o-mini)",
    )

    # Classification
    CLASSIFICATION_MODEL: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model for article classification",
    )

    # Teacher LLM Configuration
    EVAL_MODEL: str = Field(
        default="claude-opus-4-5",
        description="Model for evaluation/grading (supports claude-opus-4-5, claude-sonnet-4-5-20250929, claude-haiku-4-5)",
    )
    OPTIMIZER_MODEL: str = Field(
        default="gpt-5-mini",
        description="Model for prompt improvement generation (supports gpt-5-mini, gpt-5.1, o3, o1-mini)",
    )

    # Span Detection Configuration
    SPAN_DETECTION_MODE: str = Field(
        default="multi_pass",
        description="Span detection mode: 'single' (original) or 'multi_pass' (99% recall target)",
    )
    SPAN_CHUNK_SIZE: int = Field(
        default=3000,
        description="Chunk size in characters for multi-pass detection",
    )
    SPAN_CHUNK_OVERLAP: int = Field(
        default=500,
        description="Overlap between chunks in characters",
    )
    HIGH_RECALL_MODEL: str = Field(
        default="claude-haiku-4-5",
        description="Model for high-recall first pass (Anthropic)",
    )
    ADVERSARIAL_MODEL: str = Field(
        default="gpt-5-mini",
        description="Model for adversarial second pass (OpenAI)",
    )

    # Storage
    STORAGE_PROVIDER: str = Field(
        default="s3",
        description="Storage provider: s3, local",
    )
    LOCAL_STORAGE_PATH: str = Field(
        default="./storage",
        description="Path for local storage provider",
    )
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    S3_BUCKET: str | None = None

    # CORS
    CORS_ORIGINS: str = Field(
        default="",
        description="Comma-separated list of allowed CORS origins",
    )

    # Application
    ENVIRONMENT: str = Field(
        default="development",
        description="Environment: development, staging, production",
    )
    RAW_CONTENT_RETENTION_DAYS: int = Field(
        default=30,
        description="Days to retain raw article content in storage",
    )

    # Email Notifications
    RESEND_API_KEY: str | None = Field(
        default=None,
        description="Resend API key for email notifications",
    )
    EMAIL_FROM: str = Field(
        default="NTRL <notifications@ntrl.news>",
        description="From address for email notifications",
    )
    EMAIL_RECIPIENT: str = Field(
        default="eric@ntrl.news",
        description="Default recipient for evaluation emails",
    )
    EMAIL_ENABLED: bool = Field(
        default=True,
        description="Enable email notifications after evaluations",
    )

    # Content Cleaning
    CONTENT_CLEANING_ENABLED: bool = Field(
        default=True,
        description="Enable content cleaning (UI artifact removal) before neutralization/classification",
    )

    # News API Sources (additive to RSS)
    PERIGON_API_KEY: str | None = Field(
        default=None,
        description="Perigon News API key for article ingestion",
    )
    PERIGON_ENABLED: bool = Field(
        default=False,
        description="Enable Perigon News API ingestion",
    )
    NEWSDATA_API_KEY: str | None = Field(
        default=None,
        description="NewsData.io API key for article ingestion",
    )
    NEWSDATA_ENABLED: bool = Field(
        default=False,
        description="Enable NewsData.io API ingestion",
    )

    # Deprecated models that will be retired or have been retired
    DEPRECATED_MODELS: ClassVar[set[str]] = {"gpt-4o", "gpt-4o-2024-08-06", "gpt-4-turbo"}

    @field_validator("SPAN_DETECTION_MODEL", "OPTIMIZER_MODEL", "OPENAI_MODEL", "CLASSIFICATION_MODEL")
    @classmethod
    def warn_deprecated_model(cls, v: str) -> str:
        """Log a warning if a deprecated/retiring model is configured."""
        import logging

        if v in cls.DEPRECATED_MODELS:
            logging.getLogger(__name__).warning(
                f"Model '{v}' is deprecated or retiring soon. Consider switching to gpt-5-mini or gpt-5.1."
            )
        return v

    @field_validator("DATABASE_URL")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        """Railway provides postgresql:// but SQLAlchemy needs postgresql+psycopg2://"""
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+psycopg2://", 1)
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings. Call at startup to validate config."""
    return Settings()
