# app/services/ntrl_fix/types.py
"""
Data types for NTRL-FIX rewriting module.
"""

from dataclasses import dataclass, field
from enum import Enum


class FixAction(str, Enum):
    """Action taken on a detected span."""

    REMOVED = "removed"
    REPLACED = "replaced"
    REWRITTEN = "rewritten"
    ANNOTATED = "annotated"
    PRESERVED = "preserved"


class ValidationStatus(str, Enum):
    """Status of a validation check."""

    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


class RiskLevel(str, Enum):
    """Risk level from validation."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ChangeRecord:
    """
    Record of a single change made during fixing.

    Attributes:
        detection_id: ID of the detection that triggered this change
        type_id: Manipulation type ID (e.g., "A.1.1")
        category_label: Human-readable category name
        type_label: Human-readable type name
        segment: Which article segment
        span_start: Original start position
        span_end: Original end position
        before: Original text
        after: Rewritten text (or None if removed)
        action: What action was taken
        severity: Original severity (1-5)
        confidence: Detection confidence
        rationale: Explanation of change
    """

    detection_id: str
    type_id: str
    category_label: str
    type_label: str
    segment: str
    span_start: int
    span_end: int
    before: str
    after: str | None
    action: FixAction
    severity: int
    confidence: float
    rationale: str


@dataclass
class CheckResult:
    """Result of a single validation check."""

    check_name: str
    status: ValidationStatus
    message: str = ""
    details: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == ValidationStatus.PASSED


@dataclass
class ValidationResult:
    """
    Result of red-line validation on rewritten content.

    Attributes:
        passed: Whether all critical checks passed
        checks: Individual check results
        failures: List of failed check names
        warnings: List of warning check names
        risk_level: Overall risk assessment
        summary: Human-readable summary
    """

    passed: bool
    checks: dict[str, CheckResult]
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.NONE
    summary: str = ""

    def __post_init__(self):
        """Calculate failures, warnings, and risk level."""
        if not self.failures:
            self.failures = [name for name, check in self.checks.items() if check.status == ValidationStatus.FAILED]
        if not self.warnings:
            self.warnings = [name for name, check in self.checks.items() if check.status == ValidationStatus.WARNING]
        if self.risk_level == RiskLevel.NONE:
            self.risk_level = self._compute_risk()
        if not self.summary:
            self.summary = self._generate_summary()

    def _compute_risk(self) -> RiskLevel:
        """Compute overall risk level from check results."""
        if len(self.failures) >= 3:
            return RiskLevel.CRITICAL
        elif len(self.failures) >= 2:
            return RiskLevel.HIGH
        elif len(self.failures) >= 1:
            return RiskLevel.MEDIUM
        elif len(self.warnings) >= 2:
            return RiskLevel.LOW
        return RiskLevel.NONE

    def _generate_summary(self) -> str:
        """Generate human-readable summary."""
        total = len(self.checks)
        passed = sum(1 for c in self.checks.values() if c.passed)

        if self.passed:
            return f"All {total} validation checks passed"
        else:
            return f"{passed}/{total} checks passed, {len(self.failures)} failed"


@dataclass
class FixResult:
    """
    Result of fixing/rewriting an article.

    Attributes:
        detail_full: Full neutralized article body
        detail_brief: Brief synthesis of the article
        feed_title: Neutralized title for feeds
        feed_summary: Short summary for feeds
        changes: List of all changes made
        validation: Validation results
        original_length: Length of original text
        fixed_length: Length of fixed text
        processing_time_ms: Time to process
    """

    detail_full: str
    detail_brief: str
    feed_title: str
    feed_summary: str
    changes: list[ChangeRecord]
    validation: ValidationResult
    original_length: int = 0
    fixed_length: int = 0
    processing_time_ms: float = 0.0

    @property
    def total_changes(self) -> int:
        """Total number of changes made."""
        return len(self.changes)

    @property
    def changes_by_action(self) -> dict[str, int]:
        """Count of changes by action type."""
        counts: dict[str, int] = {}
        for change in self.changes:
            action = change.action.value
            counts[action] = counts.get(action, 0) + 1
        return counts

    @property
    def length_ratio(self) -> float:
        """Ratio of fixed length to original length."""
        if self.original_length == 0:
            return 1.0
        return self.fixed_length / self.original_length


@dataclass
class GeneratorConfig:
    """Configuration for content generators."""

    # LLM settings
    provider: str = "auto"  # "anthropic", "openai", "mock", "auto"
    model: str | None = None
    temperature: float = 0.3  # Lower for more deterministic output
    max_tokens: int = 4096
    timeout: float = 60.0

    # Content settings
    preserve_quotes: bool = True
    preserve_numbers: bool = True
    preserve_names: bool = True

    # Length settings
    min_length_ratio: float = 0.7  # Output should be at least 70% of input
    max_length_ratio: float = 1.1  # Output should be at most 110% of input


@dataclass
class SpanContext:
    """
    Context for a span to be fixed, formatted for LLM prompt.

    Attributes:
        detection_id: Unique ID for tracking
        type_id: Manipulation type
        type_label: Human-readable type name
        span_start: Start position in text
        span_end: End position in text
        text: The flagged text
        action: Recommended action
        severity: Severity level
        rationale: Why this was flagged
    """

    detection_id: str
    type_id: str
    type_label: str
    span_start: int
    span_end: int
    text: str
    action: str
    severity: int
    rationale: str

    def to_prompt_line(self) -> str:
        """Format for inclusion in LLM prompt."""
        return (
            f'- [{self.span_start}:{self.span_end}] "{self.text}" '
            f"| Type: {self.type_id} ({self.type_label}) "
            f"| Action: {self.action} | Severity: {self.severity}/5"
        )
