# app/services/ntrl_scan/lexical_detector.py
"""
Lexical Detector: Fast regex-based manipulation detection (~20ms).

This is the first line of detection in the NTRL-SCAN pipeline. It uses
compiled regex patterns from the taxonomy to quickly identify obvious
manipulation patterns.

Key features:
- Quote-aware: Skips content inside quotation marks
- Pattern caching: Compiles patterns once at startup
- Taxonomy-bound: All patterns map to canonical type IDs
"""

import re
import time
from functools import lru_cache
from typing import Optional

from app.taxonomy import (
    MANIPULATION_TAXONOMY,
    ManipulationType,
    get_types_with_patterns,
)
from .types import (
    DetectionInstance,
    ScanResult,
    ArticleSegment,
    DetectorSource,
    SpanAction,
)


class LexicalDetector:
    """
    Fast pattern matching for obvious manipulation.

    Uses regex patterns defined in the taxonomy to detect manipulation.
    Runs in ~20ms for typical article lengths.
    """

    # Regex to find quoted content (to skip during detection)
    # Matches: "...", '...', "..." (curly), '...' (curly)
    QUOTE_PATTERN = re.compile(r'"[^"]*"|\'[^\']*\'|\u201c[^\u201d]*\u201d|\u2018[^\u2019]*\u2019')

    def __init__(self):
        """Initialize detector with compiled patterns from taxonomy."""
        self._compiled_patterns: dict[str, list[tuple[re.Pattern, str]]] = {}
        self._type_metadata: dict[str, ManipulationType] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile all lexical patterns from taxonomy at startup."""
        types_with_patterns = get_types_with_patterns()

        for manip_type in types_with_patterns:
            type_id = manip_type.type_id
            self._type_metadata[type_id] = manip_type

            compiled = []
            for pattern in manip_type.lexical_patterns:
                try:
                    # Compile with case-insensitive flag
                    compiled.append((
                        re.compile(pattern, re.IGNORECASE),
                        pattern  # Keep original for debugging
                    ))
                except re.error as e:
                    # Log but don't fail on bad patterns
                    print(f"Warning: Invalid pattern for {type_id}: {pattern} - {e}")

            if compiled:
                self._compiled_patterns[type_id] = compiled

    def _find_quote_ranges(self, text: str) -> list[tuple[int, int]]:
        """Find all quoted regions in text to skip during detection."""
        ranges = []
        for match in self.QUOTE_PATTERN.finditer(text):
            ranges.append((match.start(), match.end()))
        return ranges

    def _is_inside_quote(self, pos: int, quote_ranges: list[tuple[int, int]]) -> bool:
        """Check if a position is inside a quoted region."""
        for start, end in quote_ranges:
            if start <= pos < end:
                return True
        return False

    def detect(
        self,
        text: str,
        segment: ArticleSegment = ArticleSegment.BODY,
        skip_quotes: bool = True,
    ) -> ScanResult:
        """
        Detect manipulation patterns in text.

        Args:
            text: The text to scan
            segment: Which article segment this text is from
            skip_quotes: Whether to skip matches inside quotation marks

        Returns:
            ScanResult with all detected manipulation instances
        """
        start_time = time.perf_counter()

        if not text or not text.strip():
            return ScanResult(
                spans=[],
                segment=segment,
                text_length=0,
                scan_duration_ms=0.0,
                detector_source=DetectorSource.LEXICAL,
            )

        # Find quote ranges for quote-aware detection
        quote_ranges = self._find_quote_ranges(text) if skip_quotes else []

        detections: list[DetectionInstance] = []
        seen_spans: set[tuple[int, int, str]] = set()  # Dedup overlapping matches

        # Run all patterns
        for type_id, patterns in self._compiled_patterns.items():
            manip_type = self._type_metadata[type_id]

            for compiled_pattern, original_pattern in patterns:
                for match in compiled_pattern.finditer(text):
                    span_start = match.start()
                    span_end = match.end()
                    matched_text = match.group()

                    # Skip if already detected this exact span for this type
                    span_key = (span_start, span_end, type_id)
                    if span_key in seen_spans:
                        continue
                    seen_spans.add(span_key)

                    # Check if inside quote
                    inside_quote = self._is_inside_quote(span_start, quote_ranges)
                    exemptions = ["inside_quote"] if inside_quote else []

                    # Determine action based on type and quote status
                    if inside_quote:
                        # Preserve quotes, but still record for transparency
                        action = SpanAction.ANNOTATE
                        confidence = manip_type.default_severity * 0.15  # Lower confidence
                    else:
                        action = manip_type.default_action
                        confidence = 0.95  # High confidence for pattern matches

                    detection = DetectionInstance(
                        type_id_primary=type_id,
                        segment=segment,
                        span_start=span_start,
                        span_end=span_end,
                        text=matched_text,
                        confidence=confidence,
                        severity=manip_type.default_severity,
                        detector_source=DetectorSource.LEXICAL,
                        recommended_action=action,
                        pattern_matched=original_pattern,
                        exemptions_applied=exemptions,
                        rationale=f"Matched pattern: {manip_type.label}",
                    )
                    detections.append(detection)

        # Sort by position in text
        detections.sort(key=lambda d: (d.span_start, d.span_end))

        scan_duration_ms = (time.perf_counter() - start_time) * 1000

        return ScanResult(
            spans=detections,
            segment=segment,
            text_length=len(text),
            scan_duration_ms=round(scan_duration_ms, 2),
            detector_source=DetectorSource.LEXICAL,
        )

    def detect_title(self, title: str) -> ScanResult:
        """Convenience method to scan a title."""
        return self.detect(title, segment=ArticleSegment.TITLE)

    def detect_body(self, body: str) -> ScanResult:
        """Convenience method to scan body text."""
        return self.detect(body, segment=ArticleSegment.BODY)

    @property
    def pattern_count(self) -> int:
        """Total number of compiled patterns."""
        return sum(len(patterns) for patterns in self._compiled_patterns.values())

    @property
    def type_count(self) -> int:
        """Number of taxonomy types with patterns."""
        return len(self._compiled_patterns)

    def get_patterns_for_type(self, type_id: str) -> list[str]:
        """Get the original pattern strings for a type ID."""
        if type_id not in self._compiled_patterns:
            return []
        return [original for _, original in self._compiled_patterns[type_id]]


@lru_cache(maxsize=1)
def get_lexical_detector() -> LexicalDetector:
    """Get or create the singleton lexical detector instance."""
    return LexicalDetector()
