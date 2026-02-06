# app/services/quality_gate.py
"""
Quality Control gate for the NTRL pipeline.

Runs between NEUTRALIZE and BRIEF_ASSEMBLE. Articles must pass all QC checks
to appear in the user-facing brief. Failed articles are marked with structured
reason codes for debugging and remediation.

Usage:
    service = QualityGateService()
    result = service.check_article(story_raw, story_neutralized, source)

Batch usage (pipeline stage):
    result = service.run_batch(db, trace_id="abc-123")
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app import models
from app.constants import QualityGateDefaults
from app.models import FeedCategory, PipelineStage, PipelineStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class QCStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"


class QCCategory(str, Enum):
    REQUIRED_FIELDS = "required_fields"
    CONTENT_QUALITY = "content_quality"
    PIPELINE_INTEGRITY = "pipeline_integrity"
    VIEW_COMPLETENESS = "view_completeness"


@dataclass
class QCCheckResult:
    """Result from a single QC check."""
    check: str
    passed: bool
    category: str
    reason: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {"check": self.check, "category": self.category, "reason": self.reason}
        if self.details:
            d["details"] = self.details
        return d


@dataclass
class QCResult:
    """Aggregate result from all QC checks for one article."""
    status: QCStatus
    checks: List[QCCheckResult]
    failures: List[QCCheckResult]
    checked_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class QCCheckDefinition:
    """A registered QC check."""
    name: str
    category: QCCategory
    description: str
    check_fn: Callable
    enabled: bool = True


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class QCConfig:
    """Configurable thresholds for QC checks."""
    min_detail_brief_words: int = QualityGateDefaults.MIN_DETAIL_BRIEF_WORDS
    min_detail_full_words: int = QualityGateDefaults.MIN_DETAIL_FULL_WORDS
    max_feed_title_chars: int = QualityGateDefaults.MAX_FEED_TITLE_CHARS
    min_feed_title_chars: int = QualityGateDefaults.MIN_FEED_TITLE_CHARS
    max_feed_summary_chars: int = QualityGateDefaults.MAX_FEED_SUMMARY_CHARS
    min_feed_summary_chars: int = QualityGateDefaults.MIN_FEED_SUMMARY_CHARS
    future_publish_buffer_hours: int = QualityGateDefaults.FUTURE_PUBLISH_BUFFER_HOURS
    repeated_word_run_threshold: int = QualityGateDefaults.REPEATED_WORD_RUN_THRESHOLD
    min_original_body_chars: int = QualityGateDefaults.MIN_ORIGINAL_BODY_CHARS


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class QualityGateService:
    """
    Runs QC checks on neutralized articles.

    Each check is a pure function: (raw, neutralized, source, config) -> QCCheckResult.
    The service runs all enabled checks and returns an aggregate pass/fail result.
    """

    def __init__(self, config: Optional[QCConfig] = None):
        self.config = config or QCConfig()
        self._checks: List[QCCheckDefinition] = []
        self._register_default_checks()

    def _register_default_checks(self) -> None:
        """Register all built-in QC checks."""
        # A. Required Fields
        self._register("required_feed_title", QCCategory.REQUIRED_FIELDS,
                        "Feed title is present", self._check_required_feed_title)
        self._register("required_feed_summary", QCCategory.REQUIRED_FIELDS,
                        "Feed summary is present", self._check_required_feed_summary)
        self._register("required_source", QCCategory.REQUIRED_FIELDS,
                        "Source record exists", self._check_required_source)
        self._register("required_published_at", QCCategory.REQUIRED_FIELDS,
                        "Published timestamp is valid", self._check_required_published_at)
        self._register("required_original_url", QCCategory.REQUIRED_FIELDS,
                        "Original URL is valid format", self._check_required_original_url)
        self._register("required_feed_category", QCCategory.REQUIRED_FIELDS,
                        "Feed category is set and valid", self._check_required_feed_category)

        self._register("source_name_not_generic", QCCategory.REQUIRED_FIELDS,
                        "Source is a real publisher name", self._check_source_name_not_generic)

        # B. Content Quality
        self._register("original_body_complete", QCCategory.CONTENT_QUALITY,
                        "Original body is complete (not truncated)", self._check_original_body_complete)
        self._register("original_body_sufficient", QCCategory.CONTENT_QUALITY,
                        "Original body has sufficient content (not a snippet)", self._check_original_body_sufficient)
        self._register("min_body_length", QCCategory.CONTENT_QUALITY,
                        "Neutralized content meets minimum length", self._check_min_body_length)
        self._register("feed_title_bounds", QCCategory.CONTENT_QUALITY,
                        "Feed title is within length bounds", self._check_feed_title_bounds)
        self._register("feed_summary_bounds", QCCategory.CONTENT_QUALITY,
                        "Feed summary is within length bounds", self._check_feed_summary_bounds)
        self._register("no_garbled_output", QCCategory.CONTENT_QUALITY,
                        "No garbled LLM output detected", self._check_no_garbled_output)
        self._register("no_llm_refusal", QCCategory.CONTENT_QUALITY,
                        "No LLM refusal/apology messages in content", self._check_no_llm_refusal)

        # C. Pipeline Integrity
        self._register("neutralization_success", QCCategory.PIPELINE_INTEGRITY,
                        "Neutralization completed successfully", self._check_neutralization_success)
        self._register("not_duplicate", QCCategory.PIPELINE_INTEGRITY,
                        "Article is not a duplicate", self._check_not_duplicate)

        # D. View Completeness
        self._register("views_renderable", QCCategory.VIEW_COMPLETENESS,
                        "All article views can render", self._check_views_renderable)

    def _register(self, name: str, category: QCCategory, description: str,
                  check_fn: Callable, enabled: bool = True) -> None:
        self._checks.append(QCCheckDefinition(name, category, description, check_fn, enabled))

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def check_article(
        self,
        story_raw: models.StoryRaw,
        story_neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
    ) -> QCResult:
        """Run all enabled checks against a single article."""
        results = []
        for check_def in self._checks:
            if not check_def.enabled:
                continue
            result = check_def.check_fn(story_raw, story_neutralized, source, self.config)
            results.append(result)

        failures = [r for r in results if not r.passed]
        status = QCStatus.PASSED if not failures else QCStatus.FAILED

        return QCResult(status=status, checks=results, failures=failures)

    def run_batch(
        self,
        db: Session,
        trace_id: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """
        Run QC on all articles that need checking.

        Args:
            db: Database session
            trace_id: Pipeline trace ID for log correlation
            force: If True, re-check articles that already have a qc_status

        Returns:
            Dict with total_checked, passed, failed, failures_by_check
        """
        started_at = datetime.utcnow()

        # Query articles needing QC
        query = (
            db.query(models.StoryNeutralized, models.StoryRaw, models.Source)
            .join(models.StoryRaw, models.StoryNeutralized.story_raw_id == models.StoryRaw.id)
            .outerjoin(models.Source, models.StoryRaw.source_id == models.Source.id)
            .filter(models.StoryNeutralized.is_current == True)
        )

        if not force:
            query = query.filter(models.StoryNeutralized.qc_status.is_(None))

        articles = query.all()

        total_checked = 0
        passed = 0
        failed = 0
        failures_by_check: Dict[str, int] = {}
        failures_by_category: Dict[str, int] = {}

        for neutralized, story_raw, source in articles:
            result = self.check_article(story_raw, neutralized, source)
            total_checked += 1

            neutralized.qc_status = result.status.value
            neutralized.qc_checked_at = result.checked_at

            if result.status == QCStatus.PASSED:
                passed += 1
                neutralized.qc_failures = None
            else:
                failed += 1
                neutralized.qc_failures = [f.to_dict() for f in result.failures]

                # Aggregate failure stats
                for failure in result.failures:
                    failures_by_check[failure.check] = failures_by_check.get(failure.check, 0) + 1
                    failures_by_category[failure.category] = failures_by_category.get(failure.category, 0) + 1

                # Log individual failure
                self._log_article_failure(db, story_raw, neutralized, result, trace_id)

        db.commit()

        # Log batch summary
        duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
        self._log_batch_summary(
            db, trace_id, started_at, total_checked, passed, failed,
            failures_by_check, failures_by_category, duration_ms,
        )

        logger.info(
            f"Quality check complete: {total_checked} checked, {passed} passed, {failed} failed",
            extra={
                "event": "quality_check_batch",
                "trace_id": trace_id,
                "total_checked": total_checked,
                "passed": passed,
                "failed": failed,
                "duration_ms": duration_ms,
            },
        )

        return {
            "total_checked": total_checked,
            "passed": passed,
            "failed": failed,
            "failures_by_check": failures_by_check,
            "failures_by_category": failures_by_category,
            "duration_ms": duration_ms,
        }

    # -----------------------------------------------------------------------
    # Check implementations
    # -----------------------------------------------------------------------

    @staticmethod
    def _check_required_feed_title(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        title = neutralized.feed_title
        if not title or not title.strip():
            return QCCheckResult(
                check="required_feed_title", passed=False,
                category=QCCategory.REQUIRED_FIELDS.value,
                reason="feed_title is empty or missing",
            )
        return QCCheckResult(
            check="required_feed_title", passed=True,
            category=QCCategory.REQUIRED_FIELDS.value,
        )

    @staticmethod
    def _check_required_feed_summary(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        summary = neutralized.feed_summary
        if not summary or not summary.strip():
            return QCCheckResult(
                check="required_feed_summary", passed=False,
                category=QCCategory.REQUIRED_FIELDS.value,
                reason="feed_summary is empty or missing",
            )
        return QCCheckResult(
            check="required_feed_summary", passed=True,
            category=QCCategory.REQUIRED_FIELDS.value,
        )

    @staticmethod
    def _check_required_source(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        if not raw.source_id or source is None:
            return QCCheckResult(
                check="required_source", passed=False,
                category=QCCategory.REQUIRED_FIELDS.value,
                reason="No source record linked to article",
            )
        if not source.name or not source.name.strip():
            return QCCheckResult(
                check="required_source", passed=False,
                category=QCCategory.REQUIRED_FIELDS.value,
                reason="Source record has empty name",
            )
        return QCCheckResult(
            check="required_source", passed=True,
            category=QCCategory.REQUIRED_FIELDS.value,
        )

    @staticmethod
    def _check_required_published_at(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        if raw.published_at is None:
            return QCCheckResult(
                check="required_published_at", passed=False,
                category=QCCategory.REQUIRED_FIELDS.value,
                reason="published_at is not set",
            )
        # Check not too far in the future
        buffer = timedelta(hours=config.future_publish_buffer_hours)
        if raw.published_at > datetime.utcnow() + buffer:
            return QCCheckResult(
                check="required_published_at", passed=False,
                category=QCCategory.REQUIRED_FIELDS.value,
                reason=f"published_at is in the future: {raw.published_at.isoformat()}",
                details={"published_at": raw.published_at.isoformat()},
            )
        return QCCheckResult(
            check="required_published_at", passed=True,
            category=QCCategory.REQUIRED_FIELDS.value,
        )

    @staticmethod
    def _check_required_original_url(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        url = raw.original_url
        if not url or not url.strip():
            return QCCheckResult(
                check="required_original_url", passed=False,
                category=QCCategory.REQUIRED_FIELDS.value,
                reason="original_url is empty or missing",
            )
        if not url.startswith("http://") and not url.startswith("https://"):
            return QCCheckResult(
                check="required_original_url", passed=False,
                category=QCCategory.REQUIRED_FIELDS.value,
                reason=f"original_url has invalid scheme: {url[:50]}",
                details={"url_prefix": url[:50]},
            )
        return QCCheckResult(
            check="required_original_url", passed=True,
            category=QCCategory.REQUIRED_FIELDS.value,
        )

    @staticmethod
    def _check_required_feed_category(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        if not raw.feed_category:
            return QCCheckResult(
                check="required_feed_category", passed=False,
                category=QCCategory.REQUIRED_FIELDS.value,
                reason="feed_category is not set (article not classified)",
            )
        # Validate against known categories
        valid_categories = {c.value for c in FeedCategory}
        if raw.feed_category not in valid_categories:
            return QCCheckResult(
                check="required_feed_category", passed=False,
                category=QCCategory.REQUIRED_FIELDS.value,
                reason=f"feed_category '{raw.feed_category}' is not a valid FeedCategory",
                details={"feed_category": raw.feed_category},
            )
        return QCCheckResult(
            check="required_feed_category", passed=True,
            category=QCCategory.REQUIRED_FIELDS.value,
        )

    # Generic API source names that indicate missing publisher data
    GENERIC_SOURCE_NAMES = {"Perigon News API", "NewsData.io"}

    # Patterns indicating LLM refusal/apology instead of real content.
    # Anchored to start of text to avoid false positives from articles quoting AI.
    LLM_REFUSAL_PATTERNS = [
        re.compile(r"^\s*I'?m sorry[,.]?\s+(?:but\s+)?I\s+(?:can'?t|cannot|am unable to)", re.IGNORECASE),
        re.compile(r"^\s*I apologize[,.]?\s+(?:but\s+)?I\s+(?:can'?t|cannot|am unable to)", re.IGNORECASE),
        re.compile(r"^\s*I'?m unable to\s+(?:provide|process|neutralize|summarize|create|generate)", re.IGNORECASE),
        re.compile(r"^\s*I (?:can'?t|cannot) (?:provide|process|neutralize|summarize|create|generate)", re.IGNORECASE),
        re.compile(r"^\s*As an AI(?:\s+language model)?[,.]?\s+I", re.IGNORECASE),
        re.compile(r"^\s*I don'?t have (?:access to|enough information)", re.IGNORECASE),
        re.compile(r"^\s*Unfortunately[,.]?\s+I\s+(?:can'?t|cannot|am unable to)", re.IGNORECASE),
        re.compile(r"^\s*The (?:article|text|content) (?:provided |you (?:provided|shared) )?(?:is|appears to be|seems)\s+(?:too short|incomplete|not available|empty|insufficient)", re.IGNORECASE),
    ]

    @staticmethod
    def _check_source_name_not_generic(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        """Source name must be a real publisher, not a generic API name."""
        if source and source.name and source.name.strip() in QualityGateService.GENERIC_SOURCE_NAMES:
            return QCCheckResult(
                check="source_name_not_generic", passed=False,
                category=QCCategory.REQUIRED_FIELDS.value,
                reason=f"Generic API source name: '{source.name}'",
                details={"source_slug": source.slug},
            )
        return QCCheckResult(
            check="source_name_not_generic", passed=True,
            category=QCCategory.REQUIRED_FIELDS.value,
        )

    @staticmethod
    def _check_original_body_complete(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        """Original body must be available and not truncated."""
        if not raw.raw_content_available:
            return QCCheckResult(
                check="original_body_complete", passed=False,
                category=QCCategory.CONTENT_QUALITY.value,
                reason="Original body not available in storage",
            )
        if getattr(raw, 'body_is_truncated', False):
            return QCCheckResult(
                check="original_body_complete", passed=False,
                category=QCCategory.CONTENT_QUALITY.value,
                reason="Original body was truncated by source API",
                details={"source_type": raw.source_type},
            )
        return QCCheckResult(
            check="original_body_complete", passed=True,
            category=QCCategory.CONTENT_QUALITY.value,
        )

    @staticmethod
    def _check_original_body_sufficient(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        """Detect paywalled/snippet sources where the raw body is too short."""
        if not raw.raw_content_available:
            return QCCheckResult(
                check="original_body_sufficient", passed=True,
                category=QCCategory.CONTENT_QUALITY.value,
            )

        body_size = getattr(raw, 'raw_content_size', None)
        if body_size is None:
            return QCCheckResult(
                check="original_body_sufficient", passed=True,
                category=QCCategory.CONTENT_QUALITY.value,
            )

        min_size = config.min_original_body_chars
        if body_size < min_size:
            return QCCheckResult(
                check="original_body_sufficient", passed=False,
                category=QCCategory.CONTENT_QUALITY.value,
                reason=(
                    f"Original body is {body_size} bytes (min {min_size}), "
                    f"likely a paywall snippet"
                ),
                details={
                    "raw_content_size": body_size,
                    "min_required": min_size,
                    "source_type": raw.source_type,
                },
            )
        return QCCheckResult(
            check="original_body_sufficient", passed=True,
            category=QCCategory.CONTENT_QUALITY.value,
        )

    @staticmethod
    def _check_min_body_length(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        brief = neutralized.detail_brief or ""
        full = neutralized.detail_full or ""
        brief_words = len(brief.split())
        full_words = len(full.split())

        brief_ok = brief_words >= config.min_detail_brief_words
        full_ok = full_words >= config.min_detail_full_words

        issues = []
        if not brief_ok:
            issues.append(
                f"detail_brief has {brief_words} words (min {config.min_detail_brief_words})"
            )
        if not full_ok:
            issues.append(
                f"detail_full has {full_words} words (min {config.min_detail_full_words})"
            )

        if issues:
            return QCCheckResult(
                check="min_body_length", passed=False,
                category=QCCategory.CONTENT_QUALITY.value,
                reason="; ".join(issues),
                details={
                    "brief_words": brief_words,
                    "full_words": full_words,
                    "brief_ok": brief_ok,
                    "full_ok": full_ok,
                },
            )
        return QCCheckResult(
            check="min_body_length", passed=True,
            category=QCCategory.CONTENT_QUALITY.value,
        )

    @staticmethod
    def _check_feed_title_bounds(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        title = neutralized.feed_title or ""
        length = len(title.strip())

        if length < config.min_feed_title_chars:
            return QCCheckResult(
                check="feed_title_bounds", passed=False,
                category=QCCategory.CONTENT_QUALITY.value,
                reason=f"feed_title is {length} chars (min {config.min_feed_title_chars})",
                details={"length": length},
            )
        if length > config.max_feed_title_chars:
            return QCCheckResult(
                check="feed_title_bounds", passed=False,
                category=QCCategory.CONTENT_QUALITY.value,
                reason=f"feed_title is {length} chars (max {config.max_feed_title_chars})",
                details={"length": length, "title_preview": title[:80]},
            )
        return QCCheckResult(
            check="feed_title_bounds", passed=True,
            category=QCCategory.CONTENT_QUALITY.value,
        )

    @staticmethod
    def _check_feed_summary_bounds(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        summary = neutralized.feed_summary or ""
        length = len(summary.strip())

        if length < config.min_feed_summary_chars:
            return QCCheckResult(
                check="feed_summary_bounds", passed=False,
                category=QCCategory.CONTENT_QUALITY.value,
                reason=f"feed_summary is {length} chars (min {config.min_feed_summary_chars})",
                details={"length": length},
            )
        if length > config.max_feed_summary_chars:
            return QCCheckResult(
                check="feed_summary_bounds", passed=False,
                category=QCCategory.CONTENT_QUALITY.value,
                reason=f"feed_summary is {length} chars (max {config.max_feed_summary_chars})",
                details={"length": length, "summary_preview": summary[:100]},
            )
        return QCCheckResult(
            check="feed_summary_bounds", passed=True,
            category=QCCategory.CONTENT_QUALITY.value,
        )

    @staticmethod
    def _check_no_garbled_output(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        """Detect garbled LLM output: placeholders, repeated words, artifacts."""
        fields_to_check = [
            ("feed_title", neutralized.feed_title),
            ("feed_summary", neutralized.feed_summary),
            ("detail_brief", neutralized.detail_brief),
        ]
        issues = []

        for field_name, text in fields_to_check:
            if not text:
                continue

            # Placeholder markers
            if re.search(r'\[(?:TITLE|SUMMARY|BRIEF|INSERT|HEADLINE|BODY)\]|{{.*?}}', text):
                issues.append(f"{field_name} contains placeholder markers")

            # Repeated word runs
            words = text.split()
            threshold = config.repeated_word_run_threshold
            for i in range(len(words) - threshold + 1):
                window = words[i:i + threshold]
                if len(set(w.lower() for w in window)) == 1 and len(window[0]) > 2:
                    issues.append(f"{field_name} has repeated word run: '{window[0]}'")
                    break

            # Raw JSON/code artifacts in user-facing text
            if re.search(r'^\s*[{\["]', text) and re.search(r'[}\]"]\s*$', text):
                issues.append(f"{field_name} looks like raw JSON/code, not prose")

        if issues:
            return QCCheckResult(
                check="no_garbled_output", passed=False,
                category=QCCategory.CONTENT_QUALITY.value,
                reason="; ".join(issues),
                details={"issues": issues},
            )
        return QCCheckResult(
            check="no_garbled_output", passed=True,
            category=QCCategory.CONTENT_QUALITY.value,
        )

    @staticmethod
    def _check_no_llm_refusal(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        """Detect LLM refusal/apology messages in content fields."""
        fields_to_check = [
            ("feed_title", neutralized.feed_title),
            ("feed_summary", neutralized.feed_summary),
            ("detail_brief", neutralized.detail_brief),
            ("detail_full", neutralized.detail_full),
        ]
        issues = []

        for field_name, text in fields_to_check:
            if not text or not text.strip():
                continue
            for pattern in QualityGateService.LLM_REFUSAL_PATTERNS:
                if pattern.search(text):
                    preview = text[:120].replace("\n", " ")
                    issues.append(f"{field_name} contains LLM refusal: '{preview}...'")
                    break

        if issues:
            return QCCheckResult(
                check="no_llm_refusal", passed=False,
                category=QCCategory.CONTENT_QUALITY.value,
                reason="; ".join(issues),
                details={"issues": issues},
            )
        return QCCheckResult(
            check="no_llm_refusal", passed=True,
            category=QCCategory.CONTENT_QUALITY.value,
        )

    @staticmethod
    def _check_neutralization_success(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        if neutralized.neutralization_status != "success":
            return QCCheckResult(
                check="neutralization_success", passed=False,
                category=QCCategory.PIPELINE_INTEGRITY.value,
                reason=f"neutralization_status is '{neutralized.neutralization_status}'",
                details={"status": neutralized.neutralization_status,
                         "failure_reason": neutralized.failure_reason},
            )
        return QCCheckResult(
            check="neutralization_success", passed=True,
            category=QCCategory.PIPELINE_INTEGRITY.value,
        )

    @staticmethod
    def _check_not_duplicate(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        if raw.is_duplicate:
            return QCCheckResult(
                check="not_duplicate", passed=False,
                category=QCCategory.PIPELINE_INTEGRITY.value,
                reason="Article is marked as duplicate",
                details={"duplicate_of_id": str(raw.duplicate_of_id) if raw.duplicate_of_id else None},
            )
        return QCCheckResult(
            check="not_duplicate", passed=True,
            category=QCCategory.PIPELINE_INTEGRITY.value,
        )

    @staticmethod
    def _check_views_renderable(
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        source: Optional[models.Source],
        config: QCConfig,
    ) -> QCCheckResult:
        """Ensure all three article views can render without blank content."""
        issues = []

        # Brief or Full must have content for the detail view
        has_brief = neutralized.detail_brief and neutralized.detail_brief.strip()
        has_full = neutralized.detail_full and neutralized.detail_full.strip()
        if not has_brief and not has_full:
            issues.append("Neither detail_brief nor detail_full has content")

        # If manipulative content was flagged, disclosure must be set for Ntrl view
        if neutralized.has_manipulative_content:
            if not neutralized.disclosure or not neutralized.disclosure.strip():
                issues.append("has_manipulative_content is True but disclosure is empty")

        if issues:
            return QCCheckResult(
                check="views_renderable", passed=False,
                category=QCCategory.VIEW_COMPLETENESS.value,
                reason="; ".join(issues),
                details={"has_brief": bool(has_brief), "has_full": bool(has_full),
                         "has_manipulative": neutralized.has_manipulative_content},
            )
        return QCCheckResult(
            check="views_renderable", passed=True,
            category=QCCategory.VIEW_COMPLETENESS.value,
        )

    # -----------------------------------------------------------------------
    # Logging helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _log_article_failure(
        db: Session,
        raw: models.StoryRaw,
        neutralized: models.StoryNeutralized,
        result: QCResult,
        trace_id: Optional[str],
    ) -> None:
        """Log a per-article QC failure to PipelineLog."""
        failure_checks = [f.check for f in result.failures]
        primary_failure = failure_checks[0] if failure_checks else "unknown"

        log_entry = models.PipelineLog(
            stage=PipelineStage.QUALITY_CHECK.value,
            status=PipelineStatus.FAILED.value,
            story_raw_id=raw.id,
            trace_id=trace_id,
            failure_reason=primary_failure,
            started_at=result.checked_at,
            finished_at=result.checked_at,
            duration_ms=0,
            log_metadata={
                "all_failures": failure_checks,
                "story_title": (raw.original_title or "")[:100],
                "source_name": neutralized.feed_title[:50] if neutralized.feed_title else None,
                "qc_failures": [f.to_dict() for f in result.failures],
            },
        )
        db.add(log_entry)

    @staticmethod
    def _log_batch_summary(
        db: Session,
        trace_id: Optional[str],
        started_at: datetime,
        total_checked: int,
        passed: int,
        failed: int,
        failures_by_check: Dict[str, int],
        failures_by_category: Dict[str, int],
        duration_ms: int,
    ) -> None:
        """Log the batch QC summary to PipelineLog."""
        log_entry = models.PipelineLog(
            stage=PipelineStage.QUALITY_CHECK.value,
            status=PipelineStatus.COMPLETED.value if failed == 0 else PipelineStatus.COMPLETED.value,
            trace_id=trace_id,
            started_at=started_at,
            finished_at=datetime.utcnow(),
            duration_ms=duration_ms,
            log_metadata={
                "total_checked": total_checked,
                "passed": passed,
                "failed": failed,
                "failures_by_check": failures_by_check,
                "failures_by_category": failures_by_category,
            },
        )
        db.add(log_entry)
        db.commit()
