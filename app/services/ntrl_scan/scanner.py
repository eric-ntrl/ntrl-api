# app/services/ntrl_scan/scanner.py
"""
NTRL Scanner: Orchestrates parallel detection across all detectors.

This is the main entry point for the ntrl-scan phase. It:
1. Runs lexical, structural, and semantic detectors in parallel
2. Merges and deduplicates results
3. Applies severity scoring with segment multipliers
4. Returns a unified ScanResult

Target latency: ~400ms total (dominated by semantic detector)
"""

import asyncio
import time
from typing import Optional
from dataclasses import dataclass, field

from .types import (
    DetectionInstance,
    ScanResult,
    MergedScanResult,
    ArticleSegment,
    DetectorSource,
    SEGMENT_MULTIPLIERS,
)
from .lexical_detector import LexicalDetector, get_lexical_detector
from .structural_detector import StructuralDetector, get_structural_detector
from .semantic_detector import SemanticDetector, create_semantic_detector


@dataclass
class ScannerConfig:
    """Configuration for the NTRL Scanner."""

    # Which detectors to run
    enable_lexical: bool = True
    enable_structural: bool = True
    enable_semantic: bool = True

    # Semantic detector settings
    semantic_provider: str = "auto"  # "anthropic", "openai", "mock", "auto"
    semantic_model: Optional[str] = None

    # Performance settings
    timeout_seconds: float = 10.0  # Max time for all detectors

    # Deduplication settings
    overlap_threshold: float = 0.5  # Min overlap ratio to consider duplicate


class NTRLScanner:
    """
    Orchestrates parallel manipulation detection across all detectors.

    Usage:
        scanner = NTRLScanner()
        result = await scanner.scan("Article text here", segment=ArticleSegment.BODY)
    """

    def __init__(self, config: Optional[ScannerConfig] = None):
        """
        Initialize scanner with configuration.

        Args:
            config: Scanner configuration. If None, uses defaults.
        """
        self.config = config or ScannerConfig()

        # Initialize detectors lazily
        self._lexical: Optional[LexicalDetector] = None
        self._structural: Optional[StructuralDetector] = None
        self._semantic: Optional[SemanticDetector] = None

    @property
    def lexical(self) -> LexicalDetector:
        """Get lexical detector (lazy initialization)."""
        if self._lexical is None:
            self._lexical = get_lexical_detector()
        return self._lexical

    @property
    def structural(self) -> StructuralDetector:
        """Get structural detector (lazy initialization)."""
        if self._structural is None:
            self._structural = get_structural_detector()
        return self._structural

    @property
    def semantic(self) -> SemanticDetector:
        """Get semantic detector (lazy initialization)."""
        if self._semantic is None:
            self._semantic = create_semantic_detector(
                provider=self.config.semantic_provider,
                model=self.config.semantic_model,
            )
        return self._semantic

    async def scan(
        self,
        text: str,
        segment: ArticleSegment = ArticleSegment.BODY,
    ) -> MergedScanResult:
        """
        Scan text for manipulation using all enabled detectors.

        Runs detectors in parallel for performance.

        Args:
            text: The text to scan
            segment: Which article segment this is

        Returns:
            MergedScanResult with deduplicated detections
        """
        start_time = time.perf_counter()

        if not text or not text.strip():
            return MergedScanResult(
                spans=[],
                segment=segment,
                text_length=0,
                total_scan_duration_ms=0.0,
            )

        # Build list of detector tasks
        tasks = []
        task_names = []

        if self.config.enable_lexical:
            tasks.append(self._run_lexical(text, segment))
            task_names.append("lexical")

        if self.config.enable_structural:
            tasks.append(self._run_structural(text, segment))
            task_names.append("structural")

        if self.config.enable_semantic:
            tasks.append(self._run_semantic(text, segment))
            task_names.append("semantic")

        # Run all detectors in parallel with timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.config.timeout_seconds,
            )
        except asyncio.TimeoutError:
            # Return partial results on timeout
            results = []

        # Collect results and durations
        all_spans: list[DetectionInstance] = []
        detector_durations: dict[str, float] = {}

        for name, result in zip(task_names, results):
            if isinstance(result, Exception):
                print(f"Detector {name} failed: {result}")
                detector_durations[name] = 0.0
            elif isinstance(result, ScanResult):
                all_spans.extend(result.spans)
                detector_durations[name] = result.scan_duration_ms

        # Merge and deduplicate spans
        merged_spans = self._merge_spans(all_spans)

        # Apply segment multipliers to severity
        for span in merged_spans:
            multiplier = SEGMENT_MULTIPLIERS.get(segment, 1.0)
            span.severity_weighted = span.severity * multiplier

        # Sort by position
        merged_spans.sort(key=lambda s: (s.span_start, s.span_end))

        total_duration_ms = (time.perf_counter() - start_time) * 1000

        return MergedScanResult(
            spans=merged_spans,
            segment=segment,
            text_length=len(text),
            total_scan_duration_ms=round(total_duration_ms, 2),
            detector_durations=detector_durations,
        )

    async def _run_lexical(
        self,
        text: str,
        segment: ArticleSegment
    ) -> ScanResult:
        """Run lexical detector (sync, but wrapped for parallel execution)."""
        # Lexical is sync, run in thread pool to not block
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.lexical.detect(text, segment)
        )

    async def _run_structural(
        self,
        text: str,
        segment: ArticleSegment
    ) -> ScanResult:
        """Run structural detector (sync, but wrapped for parallel execution)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.structural.detect(text, segment)
        )

    async def _run_semantic(
        self,
        text: str,
        segment: ArticleSegment
    ) -> ScanResult:
        """Run semantic detector (async)."""
        return await self.semantic.detect(text, segment)

    def _merge_spans(
        self,
        spans: list[DetectionInstance]
    ) -> list[DetectionInstance]:
        """
        Merge and deduplicate overlapping spans.

        When spans overlap significantly:
        - Keep the one with higher confidence
        - If same confidence, keep the one from more reliable detector
        - Preserve secondary type IDs from removed span
        """
        if not spans:
            return []

        # Sort by position
        sorted_spans = sorted(spans, key=lambda s: (s.span_start, s.span_end))

        merged: list[DetectionInstance] = []

        for span in sorted_spans:
            # Check if this span overlaps with any existing merged span
            overlapping = None
            overlap_ratio = 0.0

            for existing in merged:
                ratio = self._compute_overlap(span, existing)
                if ratio > self.config.overlap_threshold:
                    overlapping = existing
                    overlap_ratio = ratio
                    break

            if overlapping is None:
                # No significant overlap, add span
                merged.append(span)
            else:
                # Significant overlap - decide which to keep
                if span.type_id_primary == overlapping.type_id_primary:
                    # Same type - keep higher confidence
                    if span.confidence > overlapping.confidence:
                        merged.remove(overlapping)
                        merged.append(span)
                else:
                    # Different types - keep both if not exact same span
                    if overlap_ratio < 0.9:
                        merged.append(span)
                    else:
                        # Very high overlap, keep higher severity
                        if span.severity > overlapping.severity:
                            # Add the existing type as secondary
                            span.type_ids_secondary.append(overlapping.type_id_primary)
                            merged.remove(overlapping)
                            merged.append(span)
                        else:
                            # Add new type as secondary to existing
                            overlapping.type_ids_secondary.append(span.type_id_primary)

        return merged

    def _compute_overlap(
        self,
        span1: DetectionInstance,
        span2: DetectionInstance
    ) -> float:
        """
        Compute overlap ratio between two spans.

        Returns ratio of intersection to smaller span length.
        """
        # Compute intersection
        start = max(span1.span_start, span2.span_start)
        end = min(span1.span_end, span2.span_end)
        intersection = max(0, end - start)

        # Compute smaller span length
        len1 = span1.span_end - span1.span_start
        len2 = span2.span_end - span2.span_start
        smaller = min(len1, len2)

        if smaller == 0:
            return 0.0

        return intersection / smaller

    async def scan_article(
        self,
        title: str,
        body: str,
        deck: Optional[str] = None,
    ) -> dict[ArticleSegment, MergedScanResult]:
        """
        Scan an entire article (title, deck, body) in parallel.

        Args:
            title: Article title
            body: Article body text
            deck: Optional deck/subheadline

        Returns:
            Dict mapping segment to scan results
        """
        tasks = [
            self.scan(title, ArticleSegment.TITLE),
            self.scan(body, ArticleSegment.BODY),
        ]

        if deck:
            tasks.append(self.scan(deck, ArticleSegment.DECK))

        results = await asyncio.gather(*tasks)

        output = {
            ArticleSegment.TITLE: results[0],
            ArticleSegment.BODY: results[1],
        }

        if deck:
            output[ArticleSegment.DECK] = results[2]

        return output

    async def close(self):
        """Clean up resources."""
        if self._semantic:
            await self._semantic.close()


# Convenience function for quick scanning
async def scan_text(
    text: str,
    segment: ArticleSegment = ArticleSegment.BODY,
    config: Optional[ScannerConfig] = None,
) -> MergedScanResult:
    """
    Quick scan of text using default scanner.

    Args:
        text: Text to scan
        segment: Article segment type
        config: Optional scanner configuration

    Returns:
        MergedScanResult with all detections
    """
    scanner = NTRLScanner(config=config)
    try:
        return await scanner.scan(text, segment)
    finally:
        await scanner.close()
