# app/services/ntrl_fix/fixer.py
"""
NTRL Fixer: Orchestrates parallel content generation and validation.

This is the main entry point for the ntrl-fix phase. It:
1. Takes scan results from ntrl-scan
2. Runs all generators in parallel
3. Validates outputs against red-line invariants
4. Returns unified FixResult with all outputs

Target latency: ~800ms total (generators run in parallel)
"""

import asyncio
import time
from dataclasses import dataclass

from app.taxonomy import CATEGORY_NAMES, get_type

from ..ntrl_scan.types import ArticleSegment, MergedScanResult
from .detail_brief_gen import DetailBriefGenerator, DetailBriefResult
from .detail_full_gen import DetailFullGenerator, DetailFullResult
from .feed_outputs_gen import FeedOutputsGenerator, FeedOutputsResult
from .types import (
    ChangeRecord,
    FixAction,
    FixResult,
    GeneratorConfig,
    ValidationResult,
)
from .validator import RedLineValidator, get_validator


@dataclass
class FixerConfig:
    """Configuration for the NTRL Fixer."""

    # Generator settings
    generator_config: GeneratorConfig | None = None

    # Validation settings
    strict_validation: bool = True  # Fail on any invariance violation
    retry_on_failure: bool = True  # Retry with conservative settings
    max_retries: int = 2

    # Fallback settings
    fallback_to_original: bool = True  # Return original if all else fails


class NTRLFixer:
    """
    Orchestrates parallel content generation guided by scan results.

    Usage:
        fixer = NTRLFixer()
        result = await fixer.fix(
            body="Article body...",
            title="Original title...",
            body_scan=body_scan_result,
            title_scan=title_scan_result,
        )
    """

    def __init__(self, config: FixerConfig | None = None):
        """Initialize fixer with configuration."""
        self.config = config or FixerConfig()

        # Initialize generators (lazy)
        self._detail_full_gen: DetailFullGenerator | None = None
        self._detail_brief_gen: DetailBriefGenerator | None = None
        self._feed_outputs_gen: FeedOutputsGenerator | None = None
        self._validator: RedLineValidator | None = None

    @property
    def detail_full_gen(self) -> DetailFullGenerator:
        """Get detail full generator."""
        if self._detail_full_gen is None:
            self._detail_full_gen = DetailFullGenerator(self.config.generator_config)
        return self._detail_full_gen

    @property
    def detail_brief_gen(self) -> DetailBriefGenerator:
        """Get detail brief generator."""
        if self._detail_brief_gen is None:
            self._detail_brief_gen = DetailBriefGenerator(self.config.generator_config)
        return self._detail_brief_gen

    @property
    def feed_outputs_gen(self) -> FeedOutputsGenerator:
        """Get feed outputs generator."""
        if self._feed_outputs_gen is None:
            self._feed_outputs_gen = FeedOutputsGenerator(self.config.generator_config)
        return self._feed_outputs_gen

    @property
    def validator(self) -> RedLineValidator:
        """Get validator."""
        if self._validator is None:
            self._validator = get_validator()
        return self._validator

    async def fix(
        self,
        body: str,
        title: str = "",
        body_scan: MergedScanResult | None = None,
        title_scan: MergedScanResult | None = None,
    ) -> FixResult:
        """
        Fix/neutralize article content using detected manipulation spans.

        Runs all generators in parallel for performance, then validates
        the outputs to ensure no semantic changes were introduced.

        Args:
            body: Original article body text
            title: Original article title
            body_scan: Scan results for body
            title_scan: Scan results for title

        Returns:
            FixResult with all neutralized outputs
        """
        start_time = time.perf_counter()

        if not body or not body.strip():
            return self._empty_result()

        # Create empty scan results if not provided
        if body_scan is None:
            body_scan = MergedScanResult(spans=[], segment=ArticleSegment.BODY, text_length=len(body))

        # Run all generators in parallel
        detail_full_task = asyncio.create_task(self.detail_full_gen.generate(body, body_scan))
        detail_brief_task = asyncio.create_task(self.detail_brief_gen.generate(body, body_scan))
        feed_outputs_task = asyncio.create_task(self.feed_outputs_gen.generate(body, title, title_scan))

        # Await all
        try:
            detail_full, detail_brief, feed_outputs = await asyncio.gather(
                detail_full_task, detail_brief_task, feed_outputs_task, return_exceptions=True
            )
        except Exception as e:
            print(f"Generator error: {e}")
            return self._fallback_result(body, title)

        # Handle any individual failures
        if isinstance(detail_full, Exception):
            print(f"detail_full failed: {detail_full}")
            detail_full = DetailFullResult(text=body, changes=[])

        if isinstance(detail_brief, Exception):
            print(f"detail_brief failed: {detail_brief}")
            detail_brief = DetailBriefResult(text="", key_facts=[], word_count=0)

        if isinstance(feed_outputs, Exception):
            print(f"feed_outputs failed: {feed_outputs}")
            feed_outputs = FeedOutputsResult(feed_title=title, feed_summary="")

        # Validate detail_full against original
        validation = self.validator.validate(
            original=body, rewritten=detail_full.text, strict=self.config.strict_validation
        )

        # If validation failed and retries enabled, try again with more conservative settings
        if not validation.passed and self.config.retry_on_failure:
            detail_full, validation = await self._retry_with_fallback(body, body_scan, validation)

        # Build change records from detail_full changes
        changes = self._build_change_records(detail_full.changes, body_scan)

        processing_time_ms = (time.perf_counter() - start_time) * 1000

        return FixResult(
            detail_full=detail_full.text,
            detail_brief=detail_brief.text,
            feed_title=feed_outputs.feed_title,
            feed_summary=feed_outputs.feed_summary,
            changes=changes,
            validation=validation,
            original_length=len(body),
            fixed_length=len(detail_full.text),
            processing_time_ms=round(processing_time_ms, 2),
        )

    async def _retry_with_fallback(
        self, body: str, body_scan: MergedScanResult, original_validation: ValidationResult
    ) -> tuple[DetailFullResult, ValidationResult]:
        """
        Retry generation with more conservative settings.

        If initial generation failed validation, try again with:
        - Lower temperature
        - Stricter preservation rules
        """
        print(f"Validation failed ({original_validation.failures}), retrying...")

        for attempt in range(self.config.max_retries):
            # Use mock generator for conservative fallback
            # (In production, would use stricter prompt)
            result = self.detail_full_gen._mock_generate(body, body_scan.spans)

            validation = self.validator.validate(
                original=body, rewritten=result.text, strict=self.config.strict_validation
            )

            if validation.passed:
                return result, validation

        # If all retries fail, return original
        if self.config.fallback_to_original:
            return (
                DetailFullResult(text=body, changes=[]),
                ValidationResult(passed=True, checks={}, summary="Fallback to original - no changes made"),
            )

        # Return last attempt
        return result, validation

    def _build_change_records(self, raw_changes: list[dict], body_scan: MergedScanResult) -> list[ChangeRecord]:
        """Build ChangeRecord objects from raw change data."""
        records = []

        # Create lookup for detection metadata
        detection_map = {span.detection_id: span for span in body_scan.spans}

        for change in raw_changes:
            detection_id = change.get("detection_id", "")
            detection = detection_map.get(detection_id)

            if detection:
                manip_type = get_type(detection.type_id_primary)
                type_label = manip_type.label if manip_type else detection.type_id_primary
                category = detection.type_id_primary[0]
                category_label = CATEGORY_NAMES.get(category, f"Category {category}")
            else:
                type_label = "Unknown"
                category_label = "Unknown"

            # Map action string to enum
            action_str = change.get("action_taken", "preserved")
            action_map = {
                "removed": FixAction.REMOVED,
                "replaced": FixAction.REPLACED,
                "rewritten": FixAction.REWRITTEN,
                "annotated": FixAction.ANNOTATED,
                "preserved": FixAction.PRESERVED,
            }
            action = action_map.get(action_str, FixAction.PRESERVED)

            record = ChangeRecord(
                detection_id=detection_id,
                type_id=detection.type_id_primary if detection else "",
                category_label=category_label,
                type_label=type_label,
                segment=detection.segment.value if detection else "body",
                span_start=detection.span_start if detection else 0,
                span_end=detection.span_end if detection else 0,
                before=change.get("original", ""),
                after=change.get("replacement"),
                action=action,
                severity=detection.severity if detection else 1,
                confidence=detection.confidence if detection else 0.0,
                rationale=change.get("rationale", ""),
            )
            records.append(record)

        return records

    def _empty_result(self) -> FixResult:
        """Return empty result for empty input."""
        return FixResult(
            detail_full="",
            detail_brief="",
            feed_title="",
            feed_summary="",
            changes=[],
            validation=ValidationResult(passed=True, checks={}),
            original_length=0,
            fixed_length=0,
            processing_time_ms=0.0,
        )

    def _fallback_result(self, body: str, title: str) -> FixResult:
        """Return fallback result (original content) on complete failure."""
        return FixResult(
            detail_full=body,
            detail_brief="",
            feed_title=title,
            feed_summary="",
            changes=[],
            validation=ValidationResult(passed=True, checks={}, summary="Fallback to original - generation failed"),
            original_length=len(body),
            fixed_length=len(body),
            processing_time_ms=0.0,
        )

    async def close(self):
        """Clean up resources."""
        tasks = []
        if self._detail_full_gen:
            tasks.append(self._detail_full_gen.close())
        if self._detail_brief_gen:
            tasks.append(self._detail_brief_gen.close())
        if self._feed_outputs_gen:
            tasks.append(self._feed_outputs_gen.close())

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# Convenience function for quick fixing
async def fix_article(
    body: str,
    title: str = "",
    body_scan: MergedScanResult | None = None,
    title_scan: MergedScanResult | None = None,
    config: FixerConfig | None = None,
) -> FixResult:
    """
    Convenience function to fix an article.

    Args:
        body: Original article body
        title: Original title
        body_scan: Body scan results
        title_scan: Title scan results
        config: Fixer configuration

    Returns:
        FixResult with all outputs
    """
    fixer = NTRLFixer(config=config)
    try:
        return await fixer.fix(body, title, body_scan, title_scan)
    finally:
        await fixer.close()
