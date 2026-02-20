# app/routers/pipeline.py
"""
API endpoints for NTRL Filter v2 pipeline.

Provides endpoints for:
- /v2/scan - Detection only
- /v2/fix - Rewriting with provided scan results
- /v2/process - Full pipeline (scan + fix)
- /v2/batch - Batch processing

These endpoints use the new two-phase architecture for improved performance.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.routers.admin import require_admin_key
from app.services.ntrl_batcher import (
    ArticleInput,
    NTRLBatcher,
)
from app.services.ntrl_fix import FixerConfig, GeneratorConfig
from app.services.ntrl_pipeline import (
    NTRLPipeline,
    PipelineConfig,
    ProcessingMode,
)
from app.services.ntrl_scan import ScannerConfig

router = APIRouter(prefix="/v2", tags=["ntrl-v2"])


# ============================================================================
# Request/Response Models
# ============================================================================


class ScanRequest(BaseModel):
    """Request for detection only."""

    body: str = Field(..., description="Article body text")
    title: str = Field("", description="Article title")
    enable_semantic: bool = Field(True, description="Enable LLM-based semantic detection")


class ScanResponse(BaseModel):
    """Response from detection."""

    model_config = ConfigDict(from_attributes=True)

    body_detections: int
    title_detections: int
    total_detections: int
    scan_time_ms: float
    detections_by_category: dict[str, int]
    detections_by_severity: dict[int, int]
    body_spans: list[dict]
    title_spans: list[dict]


class ProcessRequest(BaseModel):
    """Request for full pipeline processing."""

    body: str = Field(..., description="Article body text")
    title: str = Field("", description="Article title")
    deck: str | None = Field(None, description="Article deck/subheadline")
    enable_semantic: bool = Field(True, description="Enable semantic detection")
    mock_mode: bool = Field(False, description="Use mock LLM (for testing)")
    force: bool = Field(False, description="Force reprocessing (skip cache)")


class ProcessResponse(BaseModel):
    """Response from full pipeline."""

    model_config = ConfigDict(from_attributes=True)

    # Neutralized content
    detail_full: str
    detail_brief: str
    feed_title: str
    feed_summary: str

    # Statistics
    total_detections: int
    total_changes: int
    passed_validation: bool

    # Timing
    total_time_ms: float
    scan_time_ms: float
    fix_time_ms: float
    cache_hit: bool

    # Transparency summary
    detections_by_category: dict[str, int]
    changes_by_action: dict[str, int]


class BatchArticle(BaseModel):
    """Single article in batch request."""

    article_id: str
    body: str
    title: str = ""


class BatchRequest(BaseModel):
    """Request for batch processing."""

    articles: list[BatchArticle]
    enable_semantic: bool = Field(True, description="Enable semantic detection")
    mock_mode: bool = Field(False, description="Use mock LLM (for testing)")


class BatchResultItem(BaseModel):
    """Result for single article in batch."""

    article_id: str
    success: bool
    detail_full: str | None = None
    feed_title: str | None = None
    total_detections: int = 0
    total_changes: int = 0
    processing_time_ms: float = 0
    error: str | None = None


class BatchResponse(BaseModel):
    """Response from batch processing."""

    total_articles: int
    successful: int
    failed: int
    total_time_ms: float
    avg_time_per_article_ms: float
    results: list[BatchResultItem]


class TransparencyRequest(BaseModel):
    """Request for transparency data."""

    body: str
    title: str = ""


class TransparencyResponse(BaseModel):
    """Full transparency package response."""

    total_detections: int
    detections_by_category: dict[str, int]
    detections_by_severity: dict[int, int]
    manipulation_density: float
    epistemic_flags: list[str]
    validation_passed: bool
    changes: list[dict]
    filter_version: str


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/scan", response_model=ScanResponse)
async def scan_article(request: ScanRequest, _: None = Depends(require_admin_key)):
    """
    Scan article for manipulation (detection only, no rewriting).

    This endpoint runs the ntrl-scan phase to detect manipulation patterns
    using lexical, structural, and optionally semantic detectors.

    Returns detection statistics and span details.
    """
    config = PipelineConfig(
        mode=ProcessingMode.SCAN_ONLY,
        scanner_config=ScannerConfig(
            enable_semantic=request.enable_semantic,
            semantic_provider="mock" if not request.enable_semantic else "auto",
        ),
    )

    pipeline = NTRLPipeline(config=config)
    try:
        body_scan, title_scan = await pipeline.scan_only(
            body=request.body,
            title=request.title,
        )

        # Build response
        body_spans = [_span_to_dict(s) for s in body_scan.spans]
        title_spans = [_span_to_dict(s) for s in title_scan.spans] if title_scan else []

        # Aggregate stats
        all_spans = body_scan.spans + (title_scan.spans if title_scan else [])

        by_category = {}
        by_severity = {}
        for span in all_spans:
            cat = span.type_id_primary[0]
            by_category[cat] = by_category.get(cat, 0) + 1
            sev = span.severity
            by_severity[sev] = by_severity.get(sev, 0) + 1

        return ScanResponse(
            body_detections=len(body_scan.spans),
            title_detections=len(title_spans),
            total_detections=len(all_spans),
            scan_time_ms=body_scan.total_scan_duration_ms,
            detections_by_category=by_category,
            detections_by_severity=by_severity,
            body_spans=body_spans,
            title_spans=title_spans,
        )

    finally:
        await pipeline.close()


@router.post("/process", response_model=ProcessResponse)
async def process_article(request: ProcessRequest, _: None = Depends(require_admin_key)):
    """
    Process article through full NTRL pipeline (scan + fix).

    This endpoint runs both phases:
    1. ntrl-scan: Detect manipulation patterns
    2. ntrl-fix: Generate neutralized content

    Returns neutralized content and transparency data.
    """
    # Configure pipeline
    scanner_config = ScannerConfig(
        enable_semantic=request.enable_semantic,
        semantic_provider="mock" if request.mock_mode else "auto",
    )

    fixer_config = FixerConfig(
        generator_config=GeneratorConfig(
            provider="mock" if request.mock_mode else "auto",
        ),
        strict_validation=False,  # Be lenient in API responses
    )

    config = PipelineConfig(
        mode=ProcessingMode.REALTIME,
        scanner_config=scanner_config,
        fixer_config=fixer_config,
        generate_transparency=True,
    )

    pipeline = NTRLPipeline(config=config)
    try:
        result = await pipeline.process(
            body=request.body,
            title=request.title,
            deck=request.deck,
            force=request.force,
        )

        # Build response
        by_category = {}
        by_action = {}

        if result.transparency:
            by_category = result.transparency.detections_by_category
            for change in result.transparency.changes:
                action = change.action.value
                by_action[action] = by_action.get(action, 0) + 1

        return ProcessResponse(
            detail_full=result.detail_full,
            detail_brief=result.detail_brief,
            feed_title=result.feed_title,
            feed_summary=result.feed_summary,
            total_detections=result.body_scan.total_detections
            + (result.title_scan.total_detections if result.title_scan else 0),
            total_changes=result.total_changes,
            passed_validation=result.passed_validation,
            total_time_ms=result.total_processing_time_ms,
            scan_time_ms=result.scan_time_ms,
            fix_time_ms=result.fix_time_ms,
            cache_hit=result.cache_hit,
            detections_by_category=by_category,
            changes_by_action=by_action,
        )

    finally:
        await pipeline.close()


@router.post("/batch", response_model=BatchResponse)
async def process_batch(request: BatchRequest, _: None = Depends(require_admin_key)):
    """
    Process multiple articles in batch.

    Automatically selects optimal processing strategy based on batch size.
    Uses parallel processing with rate limiting.
    """
    if not request.articles:
        return BatchResponse(
            total_articles=0,
            successful=0,
            failed=0,
            total_time_ms=0,
            avg_time_per_article_ms=0,
            results=[],
        )

    if len(request.articles) > 100:
        raise HTTPException(status_code=400, detail="Maximum batch size is 100 articles")

    # Configure batcher
    pipeline_config = PipelineConfig(
        scanner_config=ScannerConfig(
            enable_semantic=request.enable_semantic,
            semantic_provider="mock" if request.mock_mode else "auto",
        ),
        fixer_config=FixerConfig(
            generator_config=GeneratorConfig(
                provider="mock" if request.mock_mode else "auto",
            ),
        ),
    )

    batcher = NTRLBatcher(pipeline_config=pipeline_config)
    try:
        # Convert to ArticleInput
        articles = [
            ArticleInput(
                article_id=a.article_id,
                body=a.body,
                title=a.title,
            )
            for a in request.articles
        ]

        batch_result = await batcher.process_batch(articles)

        # Build response
        result_items = []
        for article in request.articles:
            if article.article_id in batch_result.results:
                r = batch_result.results[article.article_id]
                result_items.append(
                    BatchResultItem(
                        article_id=article.article_id,
                        success=True,
                        detail_full=r.detail_full,
                        feed_title=r.feed_title,
                        total_detections=r.body_scan.total_detections,
                        total_changes=r.total_changes,
                        processing_time_ms=r.total_processing_time_ms,
                    )
                )
            else:
                error = batch_result.failures.get(article.article_id, "Unknown error")
                result_items.append(
                    BatchResultItem(
                        article_id=article.article_id,
                        success=False,
                        error=error,
                    )
                )

        return BatchResponse(
            total_articles=batch_result.total_articles,
            successful=batch_result.successful,
            failed=batch_result.failed,
            total_time_ms=batch_result.total_time_ms,
            avg_time_per_article_ms=batch_result.avg_time_per_article_ms,
            results=result_items,
        )

    finally:
        await batcher.close()


@router.post("/transparency", response_model=TransparencyResponse)
async def get_transparency(request: TransparencyRequest, _: None = Depends(require_admin_key)):
    """
    Get full transparency package for an article.

    Returns detailed information about what was changed and why,
    suitable for the ntrl-view UI.
    """
    config = PipelineConfig(
        generate_transparency=True,
        fixer_config=FixerConfig(
            generator_config=GeneratorConfig(provider="mock"),
        ),
        scanner_config=ScannerConfig(enable_semantic=False),
    )

    pipeline = NTRLPipeline(config=config)
    try:
        result = await pipeline.process(
            body=request.body,
            title=request.title,
        )

        if not result.transparency:
            raise HTTPException(status_code=500, detail="Failed to generate transparency data")

        return TransparencyResponse(
            total_detections=result.transparency.total_detections,
            detections_by_category=result.transparency.detections_by_category,
            detections_by_severity=result.transparency.detections_by_severity,
            manipulation_density=result.transparency.manipulation_density,
            epistemic_flags=result.transparency.epistemic_flags,
            validation_passed=result.transparency.validation.passed,
            changes=[_change_to_dict(c) for c in result.transparency.changes],
            filter_version=result.transparency.filter_version,
        )

    finally:
        await pipeline.close()


# ============================================================================
# Helper Functions
# ============================================================================


def _span_to_dict(span) -> dict:
    """Convert DetectionInstance to dict for API response."""
    return {
        "detection_id": span.detection_id,
        "type_id": span.type_id_primary,
        "span_start": span.span_start,
        "span_end": span.span_end,
        "text": span.text,
        "confidence": span.confidence,
        "severity": span.severity,
        "detector": span.detector_source.value,
        "rationale": span.rationale,
    }


def _change_to_dict(change) -> dict:
    """Convert ChangeRecord to dict for API response."""
    return {
        "detection_id": change.detection_id,
        "type_id": change.type_id,
        "category": change.category_label,
        "type_label": change.type_label,
        "segment": change.segment,
        "span_start": change.span_start,
        "span_end": change.span_end,
        "before": change.before,
        "after": change.after,
        "action": change.action.value,
        "severity": change.severity,
        "confidence": change.confidence,
        "rationale": change.rationale,
    }
