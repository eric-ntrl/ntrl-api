# app/config.py
"""
Centralized configuration with validation.

Uses pydantic-settings to load and validate all environment variables at startup.
Fail fast with clear error messages if required config is missing.
"""

import os
from functools import lru_cache
from typing import Optional

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
    OPENAI_API_KEY: Optional[str] = Field(
        default=None,
        description="OpenAI API key for neutralization",
    )
    GOOGLE_API_KEY: Optional[str] = Field(
        default=None,
        description="Google/Gemini API key",
    )
    GEMINI_API_KEY: Optional[str] = Field(
        default=None,
        description="Alternative Gemini API key env var",
    )
    ANTHROPIC_API_KEY: Optional[str] = Field(
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

    # Teacher LLM Configuration
    EVAL_MODEL: str = Field(
        default="claude-sonnet-4-5",
        description="Model for evaluation/grading (supports claude-sonnet-4-5, claude-haiku-4-5, claude-opus-4-5, gpt-4o)",
    )
    OPTIMIZER_MODEL: str = Field(
        default="gpt-4o",
        description="Model for prompt improvement generation (supports gpt-4o, o3, o1-mini, o1)",
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
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    S3_BUCKET: Optional[str] = None

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
