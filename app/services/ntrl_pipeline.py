# app/services/ntrl_pipeline.py
"""
NTRL Pipeline: Unified orchestrator for detection and rewriting.

This is the main entry point for NTRL Filter v2, connecting:
- Phase 1: ntrl-scan (parallel detection)
- Phase 2: ntrl-fix (span-guided rewriting)

Target latency: 1-2 seconds per article
- Detection: ~400ms
- Rewriting: ~800ms

Usage:
    from app.services.ntrl_pipeline import NTRLPipeline, PipelineConfig

    pipeline = NTRLPipeline()
    result = await pipeline.process(
        body="Article body...",
        title="Article title...",
    )
"""

import asyncio
import time
import hashlib
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum

from .ntrl_scan import (
    NTRLScanner,
    ScannerConfig,
    MergedScanResult,
    ArticleSegment,
)
from .ntrl_fix import (
    NTRLFixer,
    FixerConfig,
    FixResult,
    GeneratorConfig,
    ChangeRecord,
    ValidationResult,
)


class ProcessingMode(str, Enum):
    """Processing mode for the pipeline."""
    REALTIME = "realtime"      # Single article, lowest latency
    BACKGROUND = "background"  # Batch processing, higher throughput
    SCAN_ONLY = "scan_only"    # Detection only, no rewriting


@dataclass
class PipelineConfig:
    """Configuration for the NTRL Pipeline."""

    # Processing mode
    mode: ProcessingMode = ProcessingMode.REALTIME

    # Scanner configuration
    scanner_config: Optional[ScannerConfig] = None

    # Fixer configuration
    fixer_config: Optional[FixerConfig] = None

    # Caching
    enable_cache: bool = True
    cache_ttl_seconds: int = 3600  # 1 hour

    # Performance
    timeout_seconds: float = 30.0

    # Output options
    generate_transparency: bool = True


@dataclass
class TransparencyPackage:
    """
    Rich transparency output for ntrl-view UI.

    Contains all information needed to show users what was changed and why.
    """
    # Summary statistics
    total_detections: int
    detections_by_category: dict[str, int]
    detections_by_severity: dict[int, int]
    manipulation_density: float

    # Per-span details
    changes: list[ChangeRecord]

    # Epistemic risk flags
    epistemic_flags: list[str]

    # Validation result
    validation: ValidationResult

    # Audit trail
    filter_version: str
    models_used: dict[str, str]
    processing_time_ms: float


@dataclass
class PipelineResult:
    """
    Complete result from the NTRL pipeline.

    Contains all outputs needed for the app:
    - Neutralized content (5 fields)
    - Transparency package
    - Processing metadata
    """
    # Original content
    original_body: str
    original_title: str

    # Neutralized content
    detail_full: str          # Full neutralized article
    detail_brief: str         # Brief synthesis
    feed_title: str           # Neutralized title
    feed_summary: str         # Short summary

    # Detection results
    body_scan: MergedScanResult
    title_scan: Optional[MergedScanResult]

    # Fix results
    fix_result: Optional[FixResult]

    # Transparency
    transparency: Optional[TransparencyPackage]

    # Processing metadata
    total_processing_time_ms: float
    scan_time_ms: float
    fix_time_ms: float
    cache_hit: bool = False
    content_hash: str = ""

    @property
    def total_changes(self) -> int:
        """Total number of changes made."""
        if self.fix_result:
            return self.fix_result.total_changes
        return 0

    @property
    def passed_validation(self) -> bool:
        """Whether the output passed validation."""
        if self.fix_result:
            return self.fix_result.validation.passed
        return True


class NTRLPipeline:
    """
    Main orchestrator for NTRL Filter v2.

    Coordinates detection (ntrl-scan) and rewriting (ntrl-fix) phases
    to produce neutralized news content.

    Usage:
        pipeline = NTRLPipeline()
        result = await pipeline.process(body="...", title="...")
    """

    VERSION = "2.0.0"

    def __init__(self, config: Optional[PipelineConfig] = None):
        """Initialize pipeline with configuration."""
        self.config = config or PipelineConfig()

        # Initialize components lazily
        self._scanner: Optional[NTRLScanner] = None
        self._fixer: Optional[NTRLFixer] = None

        # Simple in-memory cache (would use Redis in production)
        self._cache: dict[str, PipelineResult] = {}

    @property
    def scanner(self) -> NTRLScanner:
        """Get scanner instance."""
        if self._scanner is None:
            scanner_config = self.config.scanner_config or ScannerConfig()
            self._scanner = NTRLScanner(config=scanner_config)
        return self._scanner

    @property
    def fixer(self) -> NTRLFixer:
        """Get fixer instance."""
        if self._fixer is None:
            fixer_config = self.config.fixer_config or FixerConfig()
            self._fixer = NTRLFixer(config=fixer_config)
        return self._fixer

    async def process(
        self,
        body: str,
        title: str = "",
        deck: Optional[str] = None,
        force: bool = False,
    ) -> PipelineResult:
        """
        Process an article through the full NTRL pipeline.

        Args:
            body: Article body text
            title: Article title
            deck: Optional deck/subheadline
            force: Force reprocessing even if cached

        Returns:
            PipelineResult with all outputs
        """
        start_time = time.perf_counter()

        # Generate content hash for caching
        content_hash = self._hash_content(body, title)

        # Check cache
        if self.config.enable_cache and not force:
            cached = self._get_cached(content_hash)
            if cached:
                cached.cache_hit = True
                return cached

        # Handle empty input
        if not body or not body.strip():
            return self._empty_result(body, title, content_hash)

        # Phase 1: Detection (ntrl-scan)
        scan_start = time.perf_counter()
        body_scan, title_scan = await self._run_detection(body, title, deck)
        scan_time_ms = (time.perf_counter() - scan_start) * 1000

        # Phase 2: Rewriting (ntrl-fix) - skip if scan_only mode
        fix_start = time.perf_counter()
        if self.config.mode == ProcessingMode.SCAN_ONLY:
            fix_result = None
            detail_full = body
            detail_brief = ""
            feed_title = title
            feed_summary = ""
        else:
            fix_result = await self._run_fixing(body, title, body_scan, title_scan)
            detail_full = fix_result.detail_full
            detail_brief = fix_result.detail_brief
            feed_title = fix_result.feed_title
            feed_summary = fix_result.feed_summary
        fix_time_ms = (time.perf_counter() - fix_start) * 1000

        # Generate transparency package
        transparency = None
        if self.config.generate_transparency and fix_result:
            transparency = self._build_transparency(body_scan, title_scan, fix_result)

        total_time_ms = (time.perf_counter() - start_time) * 1000

        result = PipelineResult(
            original_body=body,
            original_title=title,
            detail_full=detail_full,
            detail_brief=detail_brief,
            feed_title=feed_title,
            feed_summary=feed_summary,
            body_scan=body_scan,
            title_scan=title_scan,
            fix_result=fix_result,
            transparency=transparency,
            total_processing_time_ms=round(total_time_ms, 2),
            scan_time_ms=round(scan_time_ms, 2),
            fix_time_ms=round(fix_time_ms, 2),
            cache_hit=False,
            content_hash=content_hash,
        )

        # Cache result
        if self.config.enable_cache:
            self._set_cached(content_hash, result)

        return result

    async def _run_detection(
        self,
        body: str,
        title: str,
        deck: Optional[str]
    ) -> tuple[MergedScanResult, Optional[MergedScanResult]]:
        """Run detection phase on all content."""
        # Run body and title scans in parallel
        tasks = [
            self.scanner.scan(body, ArticleSegment.BODY),
        ]

        if title:
            tasks.append(self.scanner.scan(title, ArticleSegment.TITLE))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Extract results
        body_scan = results[0] if not isinstance(results[0], Exception) else MergedScanResult(
            spans=[], segment=ArticleSegment.BODY, text_length=len(body)
        )

        title_scan = None
        if len(results) > 1 and not isinstance(results[1], Exception):
            title_scan = results[1]

        return body_scan, title_scan

    async def _run_fixing(
        self,
        body: str,
        title: str,
        body_scan: MergedScanResult,
        title_scan: Optional[MergedScanResult]
    ) -> FixResult:
        """Run fixing phase on detected content."""
        return await self.fixer.fix(
            body=body,
            title=title,
            body_scan=body_scan,
            title_scan=title_scan,
        )

    def _build_transparency(
        self,
        body_scan: MergedScanResult,
        title_scan: Optional[MergedScanResult],
        fix_result: FixResult
    ) -> TransparencyPackage:
        """Build transparency package from results."""
        # Combine scans
        all_spans = list(body_scan.spans)
        if title_scan:
            all_spans.extend(title_scan.spans)

        # Count by category
        by_category: dict[str, int] = {}
        for span in all_spans:
            cat = span.type_id_primary[0]
            by_category[cat] = by_category.get(cat, 0) + 1

        # Count by severity
        by_severity: dict[int, int] = {}
        for span in all_spans:
            sev = span.severity
            by_severity[sev] = by_severity.get(sev, 0) + 1

        # Calculate density
        total_words = body_scan.text_length / 5 if body_scan.text_length else 1
        density = len(all_spans) / total_words * 100 if total_words > 0 else 0

        # Detect epistemic flags
        epistemic_flags = self._detect_epistemic_flags(all_spans)

        # Models used
        models_used = {
            "scanner_semantic": self.scanner.config.semantic_provider,
        }
        if self.fixer.config.generator_config:
            models_used["fixer"] = self.fixer.config.generator_config.provider

        return TransparencyPackage(
            total_detections=len(all_spans),
            detections_by_category=by_category,
            detections_by_severity=by_severity,
            manipulation_density=round(density, 2),
            changes=fix_result.changes,
            epistemic_flags=epistemic_flags,
            validation=fix_result.validation,
            filter_version=self.VERSION,
            models_used=models_used,
            processing_time_ms=fix_result.processing_time_ms,
        )

    def _detect_epistemic_flags(self, spans: list) -> list[str]:
        """Detect epistemic risk flags from spans."""
        flags = []

        # Count anonymous sources (D.5.1 vague attribution)
        vague_attrs = sum(1 for s in spans if s.type_id_primary == "D.5.1")
        if vague_attrs >= 3:
            flags.append("anonymous_source_heavy")

        # Check for modality issues (C.2.x)
        certainty_issues = sum(1 for s in spans if s.type_id_primary.startswith("C.2"))
        if certainty_issues >= 2:
            flags.append("certainty_inflation")

        # Check for temporal vagueness (D.5.2)
        temporal_vague = sum(1 for s in spans if s.type_id_primary == "D.5.2")
        if temporal_vague >= 3:
            flags.append("temporal_vagueness")

        return flags

    def _hash_content(self, body: str, title: str) -> str:
        """Generate hash for content caching."""
        content = f"{title}|||{body}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _get_cached(self, content_hash: str) -> Optional[PipelineResult]:
        """Get cached result if available."""
        return self._cache.get(content_hash)

    def _set_cached(self, content_hash: str, result: PipelineResult):
        """Cache a result."""
        # Simple LRU-like behavior: limit cache size
        if len(self._cache) > 1000:
            # Remove oldest entries
            keys = list(self._cache.keys())[:500]
            for key in keys:
                del self._cache[key]

        self._cache[content_hash] = result

    def _empty_result(
        self,
        body: str,
        title: str,
        content_hash: str
    ) -> PipelineResult:
        """Return empty result for empty input."""
        empty_scan = MergedScanResult(
            spans=[],
            segment=ArticleSegment.BODY,
            text_length=0,
        )

        return PipelineResult(
            original_body=body,
            original_title=title,
            detail_full="",
            detail_brief="",
            feed_title="",
            feed_summary="",
            body_scan=empty_scan,
            title_scan=None,
            fix_result=None,
            transparency=None,
            total_processing_time_ms=0.0,
            scan_time_ms=0.0,
            fix_time_ms=0.0,
            cache_hit=False,
            content_hash=content_hash,
        )

    async def scan_only(
        self,
        body: str,
        title: str = "",
    ) -> tuple[MergedScanResult, Optional[MergedScanResult]]:
        """
        Run detection only (no rewriting).

        Useful for analysis or when rewriting is not needed.

        Args:
            body: Article body
            title: Article title

        Returns:
            Tuple of (body_scan, title_scan)
        """
        return await self._run_detection(body, title, None)

    async def close(self):
        """Clean up resources."""
        tasks = []
        if self._scanner:
            tasks.append(self._scanner.close())
        if self._fixer:
            tasks.append(self._fixer.close())

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Clear cache
        self._cache.clear()


# Convenience function for quick processing
async def process_article(
    body: str,
    title: str = "",
    config: Optional[PipelineConfig] = None,
) -> PipelineResult:
    """
    Convenience function to process an article.

    Args:
        body: Article body text
        title: Article title
        config: Pipeline configuration

    Returns:
        PipelineResult with all outputs
    """
    pipeline = NTRLPipeline(config=config)
    try:
        return await pipeline.process(body, title)
    finally:
        await pipeline.close()
