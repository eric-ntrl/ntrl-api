# app/constants.py
"""
Centralized magic constants organized by domain.

All hardcoded numbers/strings used throughout the codebase should be
defined here with documentation explaining their purpose.
"""


class TextLimits:
    """Character and word limits for LLM-generated text outputs."""

    # Feed title (displayed in article list)
    FEED_TITLE_TARGET_CHARS = 55        # Ideal length
    FEED_TITLE_MAX_CHARS = 65           # Hard cap
    FEED_TITLE_MAX_WORDS = 12           # Max words in headline

    # Feed summary (displayed below title in list)
    FEED_SUMMARY_TARGET_CHARS = 105     # Ideal length
    FEED_SUMMARY_SOFT_MAX_CHARS = 115   # Soft max
    FEED_SUMMARY_HARD_MAX_CHARS = 130   # Hard cap (truncation point)

    # Detail title (article page headline)
    DETAIL_TITLE_MAX_CHARS = 100

    # Detail brief (article page summary)
    DETAIL_BRIEF_MIN_PARAGRAPHS = 3
    DETAIL_BRIEF_MAX_PARAGRAPHS = 5

    # Body truncation for classification
    CLASSIFICATION_BODY_PREFIX_CHARS = 2000

    # Truncation for debug endpoints
    DEBUG_PREVIEW_CHARS = 500


class PipelineDefaults:
    """Default values for pipeline execution."""

    # Ingestion
    MAX_ITEMS_PER_SOURCE = 25           # Dev mode: max articles per RSS source
    FEED_FETCH_TIMEOUT_SECONDS = 30     # RSS feed fetch timeout

    # Classification
    CLASSIFY_BATCH_SIZE = 25            # Articles per classify run

    # Neutralization
    NEUTRALIZE_BATCH_SIZE = 25          # Articles per neutralize run
    NEUTRALIZE_MAX_WORKERS = 5          # Parallel workers
    MAX_RETRY_ATTEMPTS = 2              # Audit failure retries

    # Brief assembly
    BRIEF_CUTOFF_HOURS = 24             # Look-back window for brief
    BRIEF_MAX_CUTOFF_HOURS = 72         # Maximum look-back


class RetentionPolicy:
    """Data retention and lifecycle constants."""

    RAW_CONTENT_RETENTION_DAYS = 30     # S3 raw content expiry
    PARAGRAPH_DEDUP_MIN_CHARS = 50      # Min paragraph length for dedup


class RateLimits:
    """Rate limiting constants."""

    GLOBAL_DEFAULT = "100/minute"        # Default rate limit per IP
    ADMIN_ENDPOINTS = "10/minute"        # Admin endpoint limit
    PIPELINE_TRIGGERS = "5/minute"       # Pipeline trigger limit
    PUBLIC_READ = "200/minute"           # Public read endpoint limit


class AlertThresholds:
    """Pipeline health alert thresholds."""

    BODY_DOWNLOAD_RATE_MIN_PCT = 70      # Min body download success rate
    NEUTRALIZATION_RATE_MIN_PCT = 90     # Min neutralization success rate
    BRIEF_STORY_COUNT_MIN = 10           # Min stories in brief
    CLASSIFY_FALLBACK_RATE_MAX_PCT = 1   # Max keyword fallback rate


class CacheConfig:
    """Cache TTL and size constants."""

    BRIEF_TTL_SECONDS = 900             # 15 minutes
    BRIEF_MAX_ENTRIES = 10

    STORY_TTL_SECONDS = 3600            # 1 hour
    STORY_MAX_ENTRIES = 200

    TRANSPARENCY_TTL_SECONDS = 3600     # 1 hour
    TRANSPARENCY_MAX_ENTRIES = 200
