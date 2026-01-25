# app/services/ntrl_scan/types.py
"""
Data types for NTRL-SCAN detection module.
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import uuid


class DetectorSource(str, Enum):
    """Which detector found this manipulation."""
    LEXICAL = "lexical"
    STRUCTURAL = "structural"
    SEMANTIC = "semantic"


class ArticleSegment(str, Enum):
    """Segments of an article for detection."""
    TITLE = "title"
    DECK = "deck"
    LEDE = "lede"
    BODY = "body"
    CAPTION = "caption"
    PULLQUOTE = "pullquote"
    EMBED = "embed"
    TABLE = "table"


class SpanAction(str, Enum):
    """Action to take on a detected manipulation span."""
    REMOVE = "remove"
    REPLACE = "replace"
    REWRITE = "rewrite"
    ANNOTATE = "annotate"
    PRESERVE = "preserve"


# Segment severity multipliers (title manipulation is worse than body)
SEGMENT_MULTIPLIERS = {
    ArticleSegment.TITLE: 1.5,
    ArticleSegment.DECK: 1.3,
    ArticleSegment.LEDE: 1.2,
    ArticleSegment.CAPTION: 1.2,
    ArticleSegment.BODY: 1.0,
    ArticleSegment.PULLQUOTE: 0.6,
    ArticleSegment.EMBED: 1.0,
    ArticleSegment.TABLE: 1.0,
}


@dataclass
class DetectionInstance:
    """
    A single detected manipulation instance in text.

    Attributes:
        detection_id: Unique identifier for this detection
        type_id_primary: Primary manipulation type ID (e.g., "A.1.1")
        segment: Which part of article this was found in
        span_start: Character start position in segment
        span_end: Character end position (exclusive)
        text: The exact text that was flagged
        confidence: Detection confidence (0-1)
        severity: Impact severity (1-5)
        detector_source: Which detector found this
        type_ids_secondary: Additional type IDs (multi-label)
        severity_weighted: After segment multiplier applied
        rationale: Brief explanation of why this was flagged
        recommended_action: Suggested action to take
        pattern_matched: The regex pattern that matched (for lexical)
        exemptions_applied: Any guardrails that prevented action
    """
    type_id_primary: str
    segment: ArticleSegment
    span_start: int
    span_end: int
    text: str
    confidence: float
    severity: int
    detector_source: DetectorSource
    detection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type_ids_secondary: list[str] = field(default_factory=list)
    severity_weighted: float = 0.0
    rationale: str = ""
    recommended_action: SpanAction = SpanAction.REWRITE
    pattern_matched: Optional[str] = None
    exemptions_applied: list[str] = field(default_factory=list)

    def __post_init__(self):
        """Calculate weighted severity after initialization."""
        if self.severity_weighted == 0.0:
            multiplier = SEGMENT_MULTIPLIERS.get(self.segment, 1.0)
            self.severity_weighted = self.severity * multiplier

    def is_inside_quote(self) -> bool:
        """Check if 'inside_quote' exemption is applied."""
        return "inside_quote" in self.exemptions_applied


@dataclass
class ScanResult:
    """
    Result of scanning an article or segment for manipulation.

    Attributes:
        spans: List of detected manipulation instances
        segment: Which segment was scanned
        text_length: Length of the scanned text
        scan_duration_ms: How long the scan took
        detector_source: Which detector produced this result
        summary_stats: Aggregated statistics
    """
    spans: list[DetectionInstance]
    segment: ArticleSegment
    text_length: int
    scan_duration_ms: float = 0.0
    detector_source: Optional[DetectorSource] = None
    summary_stats: dict = field(default_factory=dict)

    def __post_init__(self):
        """Calculate summary statistics."""
        if not self.summary_stats:
            self.summary_stats = self._compute_stats()

    def _compute_stats(self) -> dict:
        """Compute summary statistics for the scan result."""
        if not self.spans:
            return {
                "total_detections": 0,
                "by_category": {},
                "by_severity": {},
                "manipulation_density": 0.0,
            }

        # Count by category (first letter of type_id)
        by_category: dict[str, int] = {}
        for span in self.spans:
            cat = span.type_id_primary[0]  # e.g., "A" from "A.1.1"
            by_category[cat] = by_category.get(cat, 0) + 1

        # Count by severity
        by_severity: dict[int, int] = {}
        for span in self.spans:
            sev = span.severity
            by_severity[sev] = by_severity.get(sev, 0) + 1

        # Manipulation density (detections per 100 words, approx)
        word_count = self.text_length / 5  # Rough estimate
        density = (len(self.spans) / word_count * 100) if word_count > 0 else 0.0

        return {
            "total_detections": len(self.spans),
            "by_category": by_category,
            "by_severity": by_severity,
            "manipulation_density": round(density, 2),
        }

    @property
    def total_detections(self) -> int:
        """Total number of detections."""
        return len(self.spans)

    @property
    def high_severity_count(self) -> int:
        """Count of severity 4-5 detections."""
        return sum(1 for s in self.spans if s.severity >= 4)


@dataclass
class MergedScanResult:
    """
    Combined result from multiple detectors.

    Attributes:
        spans: Deduplicated list of all detections
        segment: Which segment was scanned
        text_length: Length of the scanned text
        total_scan_duration_ms: Total time across all detectors
        detector_durations: Time per detector
        summary_stats: Aggregated statistics
    """
    spans: list[DetectionInstance]
    segment: ArticleSegment
    text_length: int
    total_scan_duration_ms: float = 0.0
    detector_durations: dict[str, float] = field(default_factory=dict)
    summary_stats: dict = field(default_factory=dict)

    def __post_init__(self):
        """Calculate summary statistics."""
        if not self.summary_stats:
            # Reuse the same logic as ScanResult
            result = ScanResult(
                spans=self.spans,
                segment=self.segment,
                text_length=self.text_length
            )
            self.summary_stats = result.summary_stats

    @property
    def total_detections(self) -> int:
        """Total number of detections."""
        return len(self.spans)

    @property
    def high_severity_count(self) -> int:
        """Count of severity 4-5 detections."""
        return sum(1 for s in self.spans if s.severity >= 4)
