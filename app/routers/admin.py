# app/routers/admin.py
"""
Admin pipeline endpoints.

POST /v1/ingest/run - Trigger RSS ingestion
POST /v1/neutralize/run - Trigger neutralization
POST /v1/brief/run - Trigger brief assembly
POST /v1/pipeline/run - Run full pipeline (ingest + neutralize + brief)
POST /v1/pipeline/scheduled-run - Run full pipeline with observability (for Railway cron)
POST /v1/reset - Reset all article data (testing only, disabled in production)
GET  /v1/status - Get system status, config, and pipeline health metrics
"""

import logging
import os
import secrets
import uuid
from datetime import datetime
from typing import Dict, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

admin_logger = logging.getLogger(__name__)

from app.config import get_settings
from app.database import get_db
from app.schemas.admin import (
    IngestRunRequest,
    IngestRunResponse,
    IngestSourceResult,
    ClassifyRunRequest,
    ClassifyRunResponse,
    NeutralizeRunRequest,
    NeutralizeRunResponse,
    NeutralizeStoryResult,
    BriefRunRequest,
    BriefRunResponse,
    BriefSectionResult,
)
from app.schemas.grading import GradeRequest, GradeResponse, RuleResult
from app.services.ingestion import IngestionService
from app.services.neutralizer import NeutralizerService, get_neutralizer_provider, NeutralizerConfigError, get_active_model
from app.services.brief_assembly import BriefAssemblyService

router = APIRouter(prefix="/v1", tags=["admin"])


# -----------------------------------------------------------------------------
# Status endpoint
# -----------------------------------------------------------------------------

class LastRunInfo(BaseModel):
    """Info about last pipeline run."""
    stage: str
    status: str
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None


class PipelineHealthInfo(BaseModel):
    """Pipeline health metrics from latest run."""
    trace_id: Optional[str] = None
    finished_at: Optional[datetime] = None
    status: Optional[str] = None
    body_download_rate: Optional[float] = None
    neutralization_rate: Optional[float] = None
    brief_story_count: Optional[int] = None
    alerts: List[str] = Field(default_factory=list)


class AlertThresholds(BaseModel):
    """Alert threshold values."""
    body_download_rate_min: int = 70
    neutralization_rate_min: int = 90
    brief_story_count_min: int = 10


# Code version for deployment verification
# Increment this when making changes to verify Railway deploys new code
CODE_VERSION = "2026.01.31.1"


class StatusResponse(BaseModel):
    """System status response."""
    status: str = "ok"
    health: str = "unknown"
    code_version: str = CODE_VERSION
    neutralizer_provider: Optional[str] = None
    neutralizer_model: Optional[str] = None
    neutralizer_error: Optional[str] = None
    has_google_api_key: bool
    has_openai_api_key: bool
    has_anthropic_api_key: bool
    has_aws_credentials: bool = False
    s3_bucket: Optional[str] = None
    total_articles_ingested: int = 0
    total_articles_neutralized: int = 0
    total_sources: int = 0
    last_ingest: Optional[LastRunInfo] = None
    last_neutralize: Optional[LastRunInfo] = None
    last_brief: Optional[LastRunInfo] = None
    latest_pipeline_run: Optional[PipelineHealthInfo] = None
    thresholds: AlertThresholds = Field(default_factory=AlertThresholds)


def require_admin_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> None:
    """Validate admin API key. Fails closed if ADMIN_API_KEY is not set."""
    expected_key = os.getenv("ADMIN_API_KEY")

    if not expected_key:
        raise HTTPException(
            status_code=500,
            detail="Server misconfiguration: admin authentication not configured",
        )

    if not x_api_key or not secrets.compare_digest(x_api_key, expected_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
        )


@router.get("/status", response_model=StatusResponse)
def get_status(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> StatusResponse:
    """
    Get system status, LLM configuration, and pipeline health metrics.

    Returns which neutralizer provider and model are active,
    timestamps of last pipeline runs, and health metrics from
    the latest pipeline run (body download rate, alerts, etc.).
    """
    from app import models

    # Try to get the neutralizer provider (may fail if not configured)
    provider_name = None
    model_name = None
    config_error = None

    try:
        provider = get_neutralizer_provider()
        provider_name = provider.name
        model_name = provider.model_name
    except NeutralizerConfigError as e:
        config_error = str(e)

    # Get last run for each stage
    def get_last_run(stage: str) -> Optional[LastRunInfo]:
        log = (
            db.query(models.PipelineLog)
            .filter(models.PipelineLog.stage == stage)
            .order_by(models.PipelineLog.finished_at.desc())
            .first()
        )
        if log:
            return LastRunInfo(
                stage=log.stage,
                status=log.status,
                finished_at=log.finished_at,
                duration_ms=log.duration_ms,
            )
        return None

    # Get counts
    total_ingested = db.query(models.StoryRaw).count()
    total_neutralized = db.query(models.StoryNeutralized).filter(
        models.StoryNeutralized.is_current == True
    ).count()
    total_sources = db.query(models.Source).filter(
        models.Source.is_active == True
    ).count()

    # Get latest pipeline run summary for health metrics
    latest_run = (
        db.query(models.PipelineRunSummary)
        .order_by(models.PipelineRunSummary.finished_at.desc())
        .first()
    )

    pipeline_health = None
    health = "unknown"

    if latest_run:
        body_download_rate = (
            latest_run.ingest_body_downloaded / latest_run.ingest_total * 100
            if latest_run.ingest_total > 0 else 0
        )
        neutralization_rate = (
            latest_run.neutralize_success / latest_run.neutralize_total * 100
            if latest_run.neutralize_total > 0 else 0
        )

        pipeline_health = PipelineHealthInfo(
            trace_id=latest_run.trace_id,
            finished_at=latest_run.finished_at,
            status=latest_run.status,
            body_download_rate=round(body_download_rate, 1),
            neutralization_rate=round(neutralization_rate, 1),
            brief_story_count=latest_run.brief_story_count,
            alerts=latest_run.alerts or [],
        )

        # Determine overall health
        if latest_run.status == "completed" and not latest_run.alerts:
            health = "healthy"
        elif latest_run.status == "failed":
            health = "unhealthy"
        else:
            health = "degraded"

    return StatusResponse(
        status="ok" if not config_error else "error",
        health=health,
        neutralizer_provider=provider_name,
        neutralizer_model=model_name,
        neutralizer_error=config_error,
        has_google_api_key=bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")),
        has_openai_api_key=bool(os.getenv("OPENAI_API_KEY")),
        has_anthropic_api_key=bool(os.getenv("ANTHROPIC_API_KEY")),
        has_aws_credentials=bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")),
        s3_bucket=os.getenv("S3_BUCKET"),
        total_articles_ingested=total_ingested,
        total_articles_neutralized=total_neutralized,
        total_sources=total_sources,
        last_ingest=get_last_run("ingest"),
        last_neutralize=get_last_run("neutralize"),
        last_brief=get_last_run("brief_assemble"),
        latest_pipeline_run=pipeline_health,
        thresholds=AlertThresholds(),
    )


# -----------------------------------------------------------------------------
# Debug endpoint for reason mapping verification
# -----------------------------------------------------------------------------

@router.get("/debug/span-pipeline")
def debug_span_pipeline(
    story_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> dict:
    """
    Debug endpoint to trace the full span detection pipeline.

    Runs the PRODUCTION span detection path (not debug) and returns
    detailed info about what reasons are assigned at each stage.
    """
    import os
    from app import models
    from app.services.neutralizer import _detect_spans_with_config

    # Get the story
    story = db.query(models.StoryRaw).filter(models.StoryRaw.id == story_id).first()
    if not story:
        return {"error": f"Story {story_id} not found"}

    # Get body from storage
    from app.storage.factory import get_storage_provider
    storage = get_storage_provider()
    result = storage.download(story.raw_content_uri) if story.raw_content_uri else None
    body = result.content.decode("utf-8") if result and result.exists else None

    if not body:
        return {"error": "Could not retrieve article body"}

    # Run production span detection
    api_key = os.environ.get("OPENAI_API_KEY")

    # Also run raw LLM call to see what reasons it returns
    from app.services.neutralizer import detect_spans_via_llm_openai, SPAN_DETECTION_SYSTEM_PROMPT, build_span_detection_prompt
    import json
    from openai import OpenAI

    # Prepare combined text like production does
    title_separator = "\n\n---ARTICLE BODY---\n\n"
    combined_text = f"HEADLINE: {story.original_title}{title_separator}{body}" if story.original_title else body

    # Get settings
    from app.config import get_settings
    settings = get_settings()
    span_detection_model = settings.SPAN_DETECTION_MODEL  # Should be gpt-4o by default

    # Call detect_spans_via_llm_openai directly with BODY ONLY
    body_only_spans = detect_spans_via_llm_openai(body, api_key, span_detection_model)
    body_only_reasons = [s.reason.value if hasattr(s.reason, 'value') else str(s.reason) for s in body_only_spans] if body_only_spans else []

    # Call detect_spans_with_mode directly (isolate the position adjustment)
    from app.services.neutralizer import detect_spans_with_mode
    mode_spans = detect_spans_with_mode(
        body=body,
        mode="single",
        openai_api_key=api_key,
        openai_model=span_detection_model,
        title=story.original_title,
    )
    mode_reasons = [s.reason.value if hasattr(s.reason, 'value') else str(s.reason) for s in mode_spans] if mode_spans else []

    # Run _detect_spans_with_config (production path) and collect all reasons
    spans = _detect_spans_with_config(
        body=body,
        provider_api_key=api_key,
        provider_type="openai",
        provider_model="gpt-4o-mini",
        title=story.original_title,
    )
    all_span_reasons = [s.reason.value if hasattr(s.reason, 'value') else str(s.reason) for s in spans] if spans else []

    # Collect span reasons
    from collections import Counter
    reason_values = [s.reason.value if hasattr(s.reason, 'value') else str(s.reason) for s in spans]
    reason_counts = Counter(reason_values)

    span_details = [
        {
            "phrase": s.original_text[:50],
            "reason": s.reason.value if hasattr(s.reason, 'value') else str(s.reason),
            "field": s.field,
        }
        for s in spans[:15]
    ]

    return {
        "code_version": CODE_VERSION,
        "story_id": story_id,
        "title": story.original_title[:80] if story.original_title else None,
        "body_length": len(body),
        "combined_text_length": len(combined_text),
        "span_detection_model": span_detection_model,
        "test1_body_only_llm": body_only_reasons,  # detect_spans_via_llm_openai with body only
        "test1_count": len(body_only_spans) if body_only_spans else 0,
        "test2_mode_with_title": mode_reasons,  # detect_spans_with_mode (with title combination)
        "test2_count": len(mode_spans) if mode_spans else 0,
        "test3_config": all_span_reasons,  # _detect_spans_with_config
        "test3_count": len(spans),
        "reason_counts": dict(reason_counts),
        "span_details": span_details,
    }


@router.get("/debug/reason-mapping")
def debug_reason_mapping(
    _: None = Depends(require_admin_key),
) -> dict:
    """
    Debug endpoint to verify span reason mapping is working correctly.

    Tests that all canonical reasons and aliases map to the correct SpanReason enum.
    Use this to verify deployment after code changes.
    """
    from app.services.neutralizer import _parse_span_reason
    from app.models import SpanReason

    test_cases = {
        # Canonical reasons
        "agenda_signaling": "agenda_signaling",
        "editorial_voice": "editorial_voice",
        "emotional_trigger": "emotional_trigger",
        "rhetorical_framing": "rhetorical_framing",
        "clickbait": "clickbait",
        "urgency_inflation": "urgency_inflation",
        "selling": "selling",
        # Aliases that should map correctly
        "loaded_verbs": "rhetorical_framing",
        "agenda_framing": "agenda_signaling",
        "emotional": "emotional_trigger",
    }

    results = {}
    all_correct = True

    for input_reason, expected_output in test_cases.items():
        result = _parse_span_reason(input_reason)
        actual_output = result.value if hasattr(result, 'value') else str(result)
        is_correct = actual_output == expected_output
        if not is_correct:
            all_correct = False
        results[input_reason] = {
            "expected": expected_output,
            "actual": actual_output,
            "correct": is_correct,
        }

    return {
        "code_version": CODE_VERSION,
        "all_tests_passed": all_correct,
        "reason_mapping_tests": results,
    }


# -----------------------------------------------------------------------------
# Grading endpoint
# -----------------------------------------------------------------------------

@router.post("/grade", response_model=GradeResponse)
def grade_text(
    request: GradeRequest,
    _: None = Depends(require_admin_key),
) -> GradeResponse:
    """
    Grade neutralized text against canon rules.

    Runs deterministic grader checks on provided original and neutral text.
    Returns binary pass/fail for each rule plus overall pass status.
    No authentication required - useful for development iteration.
    """
    from app.services.grader import grade_article

    result = grade_article(
        original_text=request.original_text,
        neutral_text=request.neutral_text,
        original_headline=request.original_headline,
        neutral_headline=request.neutral_headline,
    )

    return GradeResponse(
        overall_pass=result["overall_pass"],
        results=[RuleResult(**r) for r in result["results"]],
    )


@router.post("/ingest/run", response_model=IngestRunResponse)
def run_ingest(
    request: IngestRunRequest = IngestRunRequest(),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> IngestRunResponse:
    """
    Trigger RSS ingestion from configured sources.

    Fetches articles from RSS feeds, normalizes, deduplicates,
    and stores raw articles.
    """
    service = IngestionService()
    result = service.ingest_all(
        db,
        source_slugs=request.source_slugs,
        max_items_per_source=request.max_items_per_source,
    )

    return IngestRunResponse(
        status=result['status'],
        started_at=result['started_at'],
        finished_at=result['finished_at'],
        duration_ms=result['duration_ms'],
        sources_processed=result['sources_processed'],
        total_ingested=result['total_ingested'],
        total_skipped_duplicate=result['total_skipped_duplicate'],
        source_results=[
            IngestSourceResult(**sr) for sr in result['source_results']
        ],
        errors=result['errors'],
    )


@router.post("/classify/run", response_model=ClassifyRunResponse)
def run_classify(
    request: ClassifyRunRequest = ClassifyRunRequest(),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> ClassifyRunResponse:
    """
    Trigger LLM-based article classification.

    Classifies articles into 20 internal domains, maps to 10 user-facing
    feed categories. Uses multi-model retry chain (gpt-4o-mini → gemini-flash)
    with keyword fallback.
    """
    from app.services.llm_classifier import LLMClassifier

    started_at = datetime.utcnow()
    classifier = LLMClassifier()

    try:
        if request.force:
            result = classifier.reclassify_all(db, limit=request.limit)
        else:
            result = classifier.classify_pending(db, limit=request.limit)

        finished_at = datetime.utcnow()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        status = "completed"
        if result.total == 0:
            status = "empty"
        elif result.failed > 0 and result.success == 0:
            status = "failed"

        return ClassifyRunResponse(
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            classify_total=result.total,
            classify_success=result.success,
            classify_llm=result.llm,
            classify_keyword_fallback=result.keyword_fallback,
            classify_failed=result.failed,
            errors=result.errors,
        )
    except Exception as e:
        finished_at = datetime.utcnow()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        return ClassifyRunResponse(
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            errors=[str(e)],
        )


@router.post("/neutralize/run", response_model=NeutralizeRunResponse)
def run_neutralize(
    request: NeutralizeRunRequest = NeutralizeRunRequest(),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> NeutralizeRunResponse:
    """
    Trigger neutralization of pending stories.

    Runs the neutralization pipeline on stories that haven't
    been processed yet (or all if force=true).
    """
    try:
        service = NeutralizerService()
        result = service.neutralize_pending(
            db,
            story_ids=request.story_ids,
            force=request.force,
            limit=request.limit,
            max_workers=request.max_workers,
        )
    except NeutralizerConfigError as e:
        import logging
        logging.getLogger(__name__).error(f"Neutralizer config error: {e}")
        raise HTTPException(status_code=500, detail="Neutralizer configuration error")

    return NeutralizeRunResponse(
        status=result['status'],
        started_at=result['started_at'],
        finished_at=result['finished_at'],
        duration_ms=result['duration_ms'],
        total_processed=result['total_processed'],
        total_skipped=result['total_skipped'],
        total_failed=result['total_failed'],
        story_results=[
            NeutralizeStoryResult(**sr) for sr in result['story_results']
        ],
    )


@router.post("/brief/run", response_model=BriefRunResponse)
def run_brief(
    request: BriefRunRequest = BriefRunRequest(),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> BriefRunResponse:
    """
    Trigger daily brief assembly.

    Assembles a deterministic daily brief from neutralized stories.
    Stories are organized by section and ordered by time.
    """
    service = BriefAssemblyService()
    result = service.assemble_brief(
        db,
        cutoff_hours=request.cutoff_hours,
        force=request.force,
    )

    # Invalidate brief cache after assembly
    from app.routers.brief import invalidate_brief_cache
    invalidate_brief_cache()

    return BriefRunResponse(
        status=result['status'],
        started_at=result['started_at'],
        finished_at=result['finished_at'],
        duration_ms=result['duration_ms'],
        brief_id=result.get('brief_id'),
        brief_date=result.get('brief_date'),
        cutoff_time=result.get('cutoff_time'),
        total_stories=result.get('total_stories', 0),
        is_empty=result.get('is_empty', False),
        empty_reason=result.get('empty_reason'),
        sections=[
            BriefSectionResult(**s) for s in result.get('sections', [])
        ],
        error=result.get('error'),
    )


# -----------------------------------------------------------------------------
# Combined pipeline endpoint
# -----------------------------------------------------------------------------

class PipelineStageResult(BaseModel):
    """Result for a single pipeline stage."""
    stage: str
    status: str
    duration_ms: int
    details: dict = Field(default_factory=dict)


class PipelineRunRequest(BaseModel):
    """Request to run full pipeline."""
    max_items_per_source: int = Field(20, ge=1, le=100, description="Max items to ingest per source")
    classify_limit: int = Field(200, ge=1, le=500, description="Max stories to classify")
    neutralize_limit: int = Field(100, ge=1, le=500, description="Max stories to neutralize")
    max_workers: int = Field(5, ge=1, le=10, description="Parallel workers for neutralization")
    cutoff_hours: int = Field(24, ge=1, le=72, description="Hours to look back for brief")


class PipelineRunResponse(BaseModel):
    """Response from full pipeline run."""
    status: str
    started_at: datetime
    finished_at: datetime
    total_duration_ms: int
    stages: List[PipelineStageResult]
    summary: dict


@router.post("/pipeline/run", response_model=PipelineRunResponse)
def run_pipeline(
    request: PipelineRunRequest = PipelineRunRequest(),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> PipelineRunResponse:
    """
    Run the full pipeline: ingest -> neutralize -> brief.

    This is a convenience endpoint that runs all three stages in sequence.
    Useful for cron jobs or manual refreshes.
    """
    started_at = datetime.utcnow()
    stages = []
    errors = []

    # Stage 1: Ingest
    try:
        ingest_service = IngestionService()
        ingest_result = ingest_service.ingest_all(
            db,
            max_items_per_source=request.max_items_per_source,
        )
        stages.append(PipelineStageResult(
            stage="ingest",
            status=ingest_result['status'],
            duration_ms=ingest_result['duration_ms'],
            details={
                'total_ingested': ingest_result['total_ingested'],
                'total_skipped': ingest_result['total_skipped_duplicate'],
                'sources_processed': ingest_result['sources_processed'],
            }
        ))
    except Exception as e:
        stages.append(PipelineStageResult(
            stage="ingest",
            status="failed",
            duration_ms=0,
            details={'error': str(e)}
        ))
        errors.append(f"Ingest failed: {e}")

    # Stage 2: Classify
    try:
        from app.services.llm_classifier import LLMClassifier
        classify_started = datetime.utcnow()
        classifier = LLMClassifier()
        classify_result = classifier.classify_pending(db, limit=request.classify_limit)
        classify_finished = datetime.utcnow()
        classify_duration = int((classify_finished - classify_started).total_seconds() * 1000)
        stages.append(PipelineStageResult(
            stage="classify",
            status="completed",
            duration_ms=classify_duration,
            details={
                'total': classify_result.total,
                'success': classify_result.success,
                'llm': classify_result.llm,
                'keyword_fallback': classify_result.keyword_fallback,
                'failed': classify_result.failed,
            }
        ))
    except Exception as e:
        stages.append(PipelineStageResult(
            stage="classify",
            status="failed",
            duration_ms=0,
            details={'error': str(e)}
        ))
        errors.append(f"Classify failed: {e}")

    # Stage 3: Neutralize
    try:
        neutralize_service = NeutralizerService()
        neutralize_result = neutralize_service.neutralize_pending(
            db,
            limit=request.neutralize_limit,
            max_workers=request.max_workers,
        )
        stages.append(PipelineStageResult(
            stage="neutralize",
            status=neutralize_result['status'],
            duration_ms=neutralize_result['duration_ms'],
            details={
                'total_processed': neutralize_result['total_processed'],
                'total_skipped': neutralize_result['total_skipped'],
                'total_failed': neutralize_result['total_failed'],
            }
        ))
    except Exception as e:
        stages.append(PipelineStageResult(
            stage="neutralize",
            status="failed",
            duration_ms=0,
            details={'error': str(e)}
        ))
        errors.append(f"Neutralize failed: {e}")

    # Stage 4: Brief assembly
    try:
        brief_service = BriefAssemblyService()
        brief_result = brief_service.assemble_brief(
            db,
            cutoff_hours=request.cutoff_hours,
            force=True,
        )
        stages.append(PipelineStageResult(
            stage="brief",
            status=brief_result['status'],
            duration_ms=brief_result['duration_ms'],
            details={
                'total_stories': brief_result.get('total_stories', 0),
                'brief_id': brief_result.get('brief_id'),
                'is_empty': brief_result.get('is_empty', False),
            }
        ))
    except Exception as e:
        stages.append(PipelineStageResult(
            stage="brief",
            status="failed",
            duration_ms=0,
            details={'error': str(e)}
        ))
        errors.append(f"Brief failed: {e}")

    finished_at = datetime.utcnow()
    total_duration_ms = int((finished_at - started_at).total_seconds() * 1000)

    # Determine overall status
    if errors:
        overall_status = "partial" if any(s.status == "completed" for s in stages) else "failed"
    else:
        overall_status = "completed"

    # Build summary from named stages
    def _stage_detail(name: str, key: str, default=0):
        for s in stages:
            if s.stage == name:
                return s.details.get(key, default)
        return default

    return PipelineRunResponse(
        status=overall_status,
        started_at=started_at,
        finished_at=finished_at,
        total_duration_ms=total_duration_ms,
        stages=stages,
        summary={
            'articles_ingested': _stage_detail('ingest', 'total_ingested'),
            'articles_classified': _stage_detail('classify', 'success'),
            'articles_neutralized': _stage_detail('neutralize', 'total_processed'),
            'stories_in_brief': _stage_detail('brief', 'total_stories'),
            'errors': errors,
        }
    )


# -----------------------------------------------------------------------------
# Scheduled pipeline endpoint (for Railway cron)
# -----------------------------------------------------------------------------

class ScheduledRunRequest(BaseModel):
    """Request for scheduled pipeline run."""
    # DEVELOPMENT MODE: Using low limits to conserve resources
    # Before production: increase max_items_per_source to 50+, neutralize_limit to 100+
    max_items_per_source: int = Field(25, ge=1, le=100, description="Max items to ingest per source")
    classify_limit: int = Field(200, ge=1, le=500, description="Max stories to classify")
    neutralize_limit: int = Field(25, ge=1, le=500, description="Max stories to neutralize")
    max_workers: int = Field(5, ge=1, le=10, description="Parallel workers for neutralization")
    cutoff_hours: int = Field(24, ge=1, le=72, description="Hours to look back for brief")

    # Evaluation options
    enable_evaluation: bool = Field(False, description="Run teacher evaluation after pipeline")
    teacher_model: str = Field("gpt-4o", description="Model to use for evaluation")
    eval_sample_size: int = Field(10, ge=1, le=50, description="Number of articles to evaluate")
    enable_auto_optimize: bool = Field(False, description="Auto-apply prompt improvements")


class EvaluationSummary(BaseModel):
    """Summary of evaluation results for scheduled run response."""
    evaluation_run_id: Optional[str] = None
    classification_accuracy: Optional[float] = None
    avg_neutralization_score: Optional[float] = None
    overall_quality_score: Optional[float] = None
    prompts_updated: int = 0
    rollback_triggered: bool = False
    estimated_cost_usd: float = 0.0


class ScheduledRunResponse(BaseModel):
    """Response from scheduled pipeline run with summary stats."""
    status: str
    trace_id: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    ingest_total: int
    ingest_body_downloaded: int
    ingest_body_failed: int
    ingest_skipped_duplicate: int
    classify_total: int = 0
    classify_success: int = 0
    classify_llm: int = 0
    classify_keyword_fallback: int = 0
    classify_failed: int = 0
    neutralize_total: int
    neutralize_success: int
    neutralize_skipped_no_body: int
    neutralize_failed: int
    brief_story_count: int
    brief_section_count: int
    alerts: List[str]
    evaluation: Optional[EvaluationSummary] = None


@router.post("/pipeline/scheduled-run", response_model=ScheduledRunResponse)
def run_scheduled_pipeline(
    request: ScheduledRunRequest = ScheduledRunRequest(),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> ScheduledRunResponse:
    """
    Run the full pipeline with observability for scheduled/cron execution.

    This endpoint runs ingest -> neutralize -> brief and creates a
    PipelineRunSummary record with health metrics and alerts.

    Designed to be called by Railway cron on a configurable schedule.
    The endpoint returns detailed metrics that can be used for monitoring.
    """
    import uuid as uuid_module
    from app import models
    from app.services.alerts import check_alerts

    started_at = datetime.utcnow()
    trace_id = str(uuid_module.uuid4())

    # Initialize counters
    ingest_total = 0
    ingest_success = 0
    ingest_body_downloaded = 0
    ingest_body_failed = 0
    ingest_skipped_duplicate = 0
    neutralize_total = 0
    neutralize_success = 0
    neutralize_skipped_no_body = 0
    neutralize_failed = 0
    brief_story_count = 0
    brief_section_count = 0
    errors = []

    # Stage 1: Ingest
    try:
        ingest_service = IngestionService()
        ingest_result = ingest_service.ingest_all(
            db,
            max_items_per_source=request.max_items_per_source,
            trace_id=trace_id,
        )
        ingest_success = ingest_result.get('total_ingested', 0)
        ingest_total = ingest_success + ingest_result.get('total_skipped_duplicate', 0)
        ingest_body_downloaded = ingest_result.get('total_body_downloaded', 0)
        ingest_body_failed = ingest_result.get('total_body_failed', 0)
        ingest_skipped_duplicate = ingest_result.get('total_skipped_duplicate', 0)
    except Exception as e:
        errors.append(f"Ingest failed: {e}")

    # Stage 2: Classify
    classify_total = 0
    classify_success = 0
    classify_llm = 0
    classify_keyword_fallback = 0
    classify_failed = 0
    try:
        from app.services.llm_classifier import LLMClassifier
        classifier = LLMClassifier()
        classify_result = classifier.classify_pending(db, limit=request.classify_limit)
        classify_total = classify_result.total
        classify_success = classify_result.success
        classify_llm = classify_result.llm
        classify_keyword_fallback = classify_result.keyword_fallback
        classify_failed = classify_result.failed
    except Exception as e:
        errors.append(f"Classify failed: {e}")

    # Stage 3: Neutralize
    try:
        neutralize_service = NeutralizerService()
        neutralize_result = neutralize_service.neutralize_pending(
            db,
            limit=request.neutralize_limit,
            max_workers=request.max_workers,
        )
        neutralize_total = neutralize_result.get('total_processed', 0) + neutralize_result.get('total_skipped', 0)
        neutralize_success = neutralize_result.get('total_processed', 0) - neutralize_result.get('total_failed', 0)
        neutralize_skipped_no_body = neutralize_result.get('skipped_no_body', 0)
        neutralize_failed = neutralize_result.get('total_failed', 0)
    except Exception as e:
        errors.append(f"Neutralize failed: {e}")

    # Stage 4: Brief assembly
    try:
        brief_service = BriefAssemblyService()
        brief_result = brief_service.assemble_brief(
            db,
            cutoff_hours=request.cutoff_hours,
            force=True,
        )
        brief_story_count = brief_result.get('total_stories', 0)
        brief_section_count = len(brief_result.get('sections', []))
    except Exception as e:
        errors.append(f"Brief failed: {e}")

    # Cleanup: Not needed — brief_assembly filters by published_at >= cutoff_time (24h),
    # so stale articles are excluded from the UI without explicit deactivation.
    # If retention-based cleanup is needed later, implement as a separate periodic job.

    finished_at = datetime.utcnow()
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)

    # Determine overall status
    if errors and ingest_total == 0 and neutralize_total == 0:
        overall_status = "failed"
    elif errors:
        overall_status = "partial"
    else:
        overall_status = "completed"

    # Create PipelineRunSummary record
    summary = models.PipelineRunSummary(
        id=uuid_module.uuid4(),
        trace_id=trace_id,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        ingest_total=ingest_total,
        ingest_success=ingest_success,
        ingest_body_downloaded=ingest_body_downloaded,
        ingest_body_failed=ingest_body_failed,
        ingest_skipped_duplicate=ingest_skipped_duplicate,
        classify_total=classify_total,
        classify_success=classify_success,
        classify_llm=classify_llm,
        classify_keyword_fallback=classify_keyword_fallback,
        classify_failed=classify_failed,
        neutralize_total=neutralize_total,
        neutralize_success=neutralize_success,
        neutralize_skipped_no_body=neutralize_skipped_no_body,
        neutralize_failed=neutralize_failed,
        brief_story_count=brief_story_count,
        brief_section_count=brief_section_count,
        status=overall_status,
        alerts=[],
        trigger="scheduled",
    )

    # Check alerts based on the summary
    alerts = check_alerts(summary)
    summary.alerts = alerts

    db.add(summary)
    db.commit()

    # Stage 5: Evaluation (optional)
    evaluation_summary = None
    if request.enable_evaluation:
        try:
            from app.services.evaluation_service import EvaluationService
            from app.services.prompt_optimizer import PromptOptimizer
            from app.services.rollback_service import RollbackService

            settings = get_settings()

            # Use config defaults, allow request to override
            eval_model = request.teacher_model
            if eval_model == "gpt-4o":  # Schema default, use config instead
                eval_model = settings.EVAL_MODEL
            optimizer_model = settings.OPTIMIZER_MODEL

            eval_service = EvaluationService(teacher_model=eval_model)
            eval_result = eval_service.run_evaluation(
                db,
                pipeline_run_id=str(summary.id),
                sample_size=request.eval_sample_size,
            )

            prompts_updated_count = 0
            rollback_triggered = False

            # Check for rollback if previous evaluation exists
            rollback_service = RollbackService()
            rollback_result = rollback_service.check_and_rollback(
                db,
                current_eval_id=eval_result.evaluation_run_id,
                auto_rollback=True,
            )
            if rollback_result and rollback_result.success:
                rollback_triggered = True
                alerts.append(f"ROLLBACK_TRIGGERED: {rollback_result.prompt_name}")

            # Auto-optimize if enabled and no rollback occurred
            if request.enable_auto_optimize and not rollback_triggered:
                optimizer = PromptOptimizer(teacher_model=optimizer_model)
                opt_result = optimizer.analyze_and_improve(
                    db,
                    evaluation_run_id=eval_result.evaluation_run_id,
                    auto_apply=True,
                )
                prompts_updated_count = len([p for p in opt_result.prompts_updated if p.get("applied")])

            evaluation_summary = EvaluationSummary(
                evaluation_run_id=eval_result.evaluation_run_id,
                classification_accuracy=eval_result.classification_accuracy,
                avg_neutralization_score=eval_result.avg_neutralization_score,
                overall_quality_score=eval_result.overall_quality_score,
                prompts_updated=prompts_updated_count,
                rollback_triggered=rollback_triggered,
                estimated_cost_usd=eval_result.estimated_cost_usd,
            )

            admin_logger.info(
                f"[SCHEDULED-RUN] Evaluation complete: accuracy={eval_result.classification_accuracy:.2%}, "
                f"quality={eval_result.overall_quality_score:.1f}/10, cost=${eval_result.estimated_cost_usd:.2f}"
            )

            # Stage 6: Send email notification
            if evaluation_summary and evaluation_summary.evaluation_run_id:
                try:
                    from app.services.email_service import EmailService
                    email_service = EmailService()
                    email_result = email_service.send_evaluation_results(
                        db, evaluation_summary.evaluation_run_id
                    )
                    if email_result.get("status") == "sent":
                        admin_logger.info(
                            f"[SCHEDULED-RUN] Email notification sent to {email_result.get('recipient')}"
                        )
                    elif email_result.get("status") == "skipped":
                        admin_logger.info(
                            f"[SCHEDULED-RUN] Email notification skipped: {email_result.get('reason')}"
                        )
                except Exception as email_error:
                    admin_logger.error(f"[SCHEDULED-RUN] Email notification failed: {email_error}")
                    alerts.append(f"EMAIL_NOTIFICATION_FAILED: {str(email_error)}")

        except Exception as e:
            admin_logger.error(f"[SCHEDULED-RUN] Evaluation failed: {e}")
            alerts.append(f"EVALUATION_FAILED: {str(e)}")

    # Update summary with final alerts
    summary.alerts = alerts
    db.commit()

    return ScheduledRunResponse(
        status=overall_status,
        trace_id=trace_id,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        ingest_total=ingest_total,
        ingest_body_downloaded=ingest_body_downloaded,
        ingest_body_failed=ingest_body_failed,
        ingest_skipped_duplicate=ingest_skipped_duplicate,
        classify_total=classify_total,
        classify_success=classify_success,
        classify_llm=classify_llm,
        classify_keyword_fallback=classify_keyword_fallback,
        classify_failed=classify_failed,
        neutralize_total=neutralize_total,
        neutralize_success=neutralize_success,
        neutralize_skipped_no_body=neutralize_skipped_no_body,
        neutralize_failed=neutralize_failed,
        brief_story_count=brief_story_count,
        brief_section_count=brief_section_count,
        alerts=alerts,
        evaluation=evaluation_summary,
    )


# -----------------------------------------------------------------------------
# Prompt management endpoints
# -----------------------------------------------------------------------------

def _get_active_model_from_db(db: Session) -> Optional[str]:
    """Get the currently active model from the active system_prompt in DB."""
    from app import models
    prompt = db.query(models.Prompt).filter(
        models.Prompt.name == "system_prompt",
        models.Prompt.is_active == True
    ).first()
    return prompt.model if prompt else None


class PromptResponse(BaseModel):
    """Response for a single prompt."""
    name: str
    model: Optional[str] = None
    content: str
    version: int
    is_active: bool = True
    updated_at: Optional[datetime] = None


class PromptUpdateRequest(BaseModel):
    """Request to update a prompt."""
    content: str
    model: Optional[str] = None  # Optional - None for model-agnostic prompts
    change_reason: Optional[str] = None  # Optional reason for the change (for audit trail)


class PromptListResponse(BaseModel):
    """Response for listing all prompts."""
    prompts: List[PromptResponse]
    active_model: Optional[str] = None


@router.get("/prompts", response_model=PromptListResponse)
def list_prompts(
    model: Optional[str] = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> PromptListResponse:
    """
    List all prompts. Optionally filter by model.
    Returns the currently active model for reference.
    """
    from app import models

    query = db.query(models.Prompt)
    if model:
        query = query.filter(models.Prompt.model == model)

    prompts = query.order_by(models.Prompt.name, models.Prompt.model).all()
    active_model = _get_active_model_from_db(db)

    return PromptListResponse(
        prompts=[
            PromptResponse(
                name=p.name,
                model=p.model,
                content=p.content,
                version=p.version,
                is_active=p.is_active,
                updated_at=p.updated_at,
            )
            for p in prompts
        ],
        active_model=active_model,
    )


@router.get("/prompts/{name}", response_model=PromptResponse)
def get_prompt(
    name: str,
    model: Optional[str] = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> PromptResponse:
    """
    Get a specific prompt by name.
    If model not specified, returns the currently active prompt for that name.
    """
    from app import models

    if model:
        # Get specific model's prompt
        prompt = db.query(models.Prompt).filter(
            models.Prompt.name == name,
            models.Prompt.model == model,
        ).first()
    else:
        # Get the active prompt for this name
        prompt = db.query(models.Prompt).filter(
            models.Prompt.name == name,
            models.Prompt.is_active == True,
        ).first()

    if not prompt:
        detail = f"Prompt '{name}' not found"
        if model:
            detail += f" for model '{model}'"
        raise HTTPException(status_code=404, detail=detail)

    return PromptResponse(
        name=prompt.name,
        model=prompt.model,
        content=prompt.content,
        version=prompt.version,
        is_active=prompt.is_active,
        updated_at=prompt.updated_at,
    )


@router.put("/prompts/{name}", response_model=PromptResponse)
def update_prompt(
    name: str,
    request: PromptUpdateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> PromptResponse:
    """
    Update or create a prompt for a specific model.
    Model must be specified in the request body.
    If this is a new prompt, it will be set as active (deactivating other prompts with same name).
    """
    from app import models
    from app.services.neutralizer import clear_prompt_cache

    target_model = request.model

    prompt = db.query(models.Prompt).filter(
        models.Prompt.name == name,
        models.Prompt.model == target_model
    ).first()

    if prompt:
        # Update existing
        old_version = prompt.version
        new_version = old_version + 1

        # Create version record for audit trail
        version_entry = models.PromptVersion(
            id=uuid.uuid4(),
            prompt_id=prompt.id,
            version=new_version,
            content=request.content,
            change_reason=request.change_reason or "Manual update",
            change_source=models.ChangeSource.MANUAL.value,
            parent_version_id=prompt.current_version_id,
            avg_score_at_creation=None,
        )
        db.add(version_entry)

        prompt.content = request.content
        prompt.version = new_version
        prompt.current_version_id = version_entry.id
        prompt.updated_at = datetime.utcnow()
    else:
        # Deactivate other prompts with same name (only one active per name)
        db.query(models.Prompt).filter(
            models.Prompt.name == name,
            models.Prompt.is_active == True
        ).update({"is_active": False})

        # Create new for this model (set as active)
        prompt = models.Prompt(
            name=name,
            model=target_model,
            content=request.content,
            version=1,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(prompt)

    db.commit()
    db.refresh(prompt)

    # Clear prompt cache to pick up new value immediately
    clear_prompt_cache()

    return PromptResponse(
        name=prompt.name,
        model=prompt.model,
        content=prompt.content,
        version=prompt.version,
        is_active=prompt.is_active,
        updated_at=prompt.updated_at,
    )


@router.post("/prompts/{name}/activate", response_model=PromptResponse)
def activate_prompt(
    name: str,
    model: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> PromptResponse:
    """
    Activate a specific prompt (by name and model).
    Deactivates all other prompts with the same name.
    This is how you switch models without redeploying.
    """
    from app import models
    from app.services.neutralizer import clear_prompt_cache

    # Find the prompt to activate
    prompt = db.query(models.Prompt).filter(
        models.Prompt.name == name,
        models.Prompt.model == model
    ).first()

    if not prompt:
        raise HTTPException(
            status_code=404,
            detail=f"Prompt '{name}' for model '{model}' not found"
        )

    # Deactivate all other prompts with same name
    db.query(models.Prompt).filter(
        models.Prompt.name == name,
        models.Prompt.id != prompt.id
    ).update({"is_active": False})

    # Activate this prompt
    prompt.is_active = True
    prompt.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(prompt)

    # Clear cache to pick up change immediately
    clear_prompt_cache()

    return PromptResponse(
        name=prompt.name,
        model=prompt.model,
        content=prompt.content,
        version=prompt.version,
        is_active=prompt.is_active,
        updated_at=prompt.updated_at,
    )


# -----------------------------------------------------------------------------
# Prompt testing endpoint
# -----------------------------------------------------------------------------

class TestPromptRequest(BaseModel):
    """Request to test prompts on sample articles."""
    limit: int = Field(10, ge=1, le=50, description="Number of articles to test")
    system_prompt: Optional[str] = Field(None, description="Override system prompt for this test only")
    user_prompt_template: Optional[str] = Field(None, description="Override user prompt template for this test only")


class ArticleTestResult(BaseModel):
    """Result for a single article test."""
    story_id: str
    source: str
    original_title: str
    original_description: Optional[str]
    feed_title: str
    feed_summary: str
    has_manipulative_content: bool


class TestPromptResponse(BaseModel):
    """Response from prompt testing."""
    prompt_version: int
    articles_tested: int
    duration_ms: int
    results: List[ArticleTestResult]


@router.post("/prompts/test", response_model=TestPromptResponse)
def test_prompts(
    request: TestPromptRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> TestPromptResponse:
    """
    Test current (or provided) prompts on sample articles.

    Returns neutralization results WITHOUT saving to database.
    Useful for iterating on prompt quality.
    """
    from app import models
    from app.services.neutralizer import (
        get_neutralizer_provider,
        _prompt_cache,
    )
    import logging
    logger = logging.getLogger(__name__)

    started_at = datetime.utcnow()

    # If custom prompts provided, temporarily update cache
    original_cache = _prompt_cache.copy()
    if request.system_prompt:
        _prompt_cache["system_prompt"] = request.system_prompt
    if request.user_prompt_template:
        _prompt_cache["user_prompt_template"] = request.user_prompt_template

    try:
        # Get sample articles (recent, not duplicates)
        stories = (
            db.query(models.StoryRaw)
            .filter(models.StoryRaw.is_duplicate == False)
            .order_by(models.StoryRaw.published_at.desc())
            .limit(request.limit)
            .all()
        )

        if not stories:
            raise HTTPException(status_code=404, detail="No articles found to test")

        # Get the provider
        provider = get_neutralizer_provider()

        results = []
        for story in stories:
            try:
                result = provider.neutralize(
                    title=story.original_title,
                    description=story.original_description,
                    body=None,  # Skip body for speed
                )
                results.append(ArticleTestResult(
                    story_id=str(story.id),
                    source=story.source.name if story.source else "Unknown",
                    original_title=story.original_title,
                    original_description=story.original_description,
                    feed_title=result.feed_title,
                    feed_summary=result.feed_summary,
                    has_manipulative_content=result.has_manipulative_content,
                ))
            except Exception as e:
                logger.error(f"Failed to neutralize story {story.id}: {e}")
                continue

        finished_at = datetime.utcnow()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        # Get current prompt version
        prompt = db.query(models.Prompt).filter(
            models.Prompt.name == "system_prompt"
        ).first()
        prompt_version = prompt.version if prompt else 0

        return TestPromptResponse(
            prompt_version=prompt_version,
            articles_tested=len(results),
            duration_ms=duration_ms,
            results=results,
        )

    finally:
        # Restore original cache
        _prompt_cache.clear()
        _prompt_cache.update(original_cache)


# -----------------------------------------------------------------------------
# Reset endpoint (for testing)
# -----------------------------------------------------------------------------

class ResetResponse(BaseModel):
    """Response for reset operation."""
    status: str
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    db_deleted: dict
    storage_deleted: int
    warning: Optional[str] = None


@router.post("/reset", response_model=ResetResponse)
def reset_all_data(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> ResetResponse:
    """
    Reset all article data for testing.

    WARNING: This permanently deletes all stories, neutralizations,
    briefs, and stored content. Only use in staging/testing environments.

    Protected by admin API key.
    """
    from app import models
    from app.storage.factory import get_storage_provider
    import os

    started_at = datetime.utcnow()

    # Safety check - refuse to run in production
    env = os.getenv("ENVIRONMENT", "development").lower()
    if env == "production":
        raise HTTPException(
            status_code=403,
            detail="Reset is disabled in production environment",
        )

    db_deleted = {
        "transparency_spans": 0,
        "daily_brief_items": 0,
        "story_neutralized": 0,
        "pipeline_logs": 0,
        "daily_briefs": 0,
        "story_raw": 0,
    }

    try:
        # Delete in order respecting foreign key constraints
        db_deleted["transparency_spans"] = db.query(models.TransparencySpan).delete()
        db_deleted["daily_brief_items"] = db.query(models.DailyBriefItem).delete()
        db_deleted["story_neutralized"] = db.query(models.StoryNeutralized).delete()
        db_deleted["pipeline_logs"] = db.query(models.PipelineLog).delete()
        db_deleted["daily_briefs"] = db.query(models.DailyBrief).delete()
        db_deleted["story_raw"] = db.query(models.StoryRaw).delete()

        db.commit()
    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Database reset failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Database reset failed",
        )

    # Delete all objects from storage
    storage_deleted = 0
    warning = None
    try:
        storage = get_storage_provider()
        storage_deleted = storage.delete_all(prefix="raw/")
    except Exception as e:
        warning = f"Storage cleanup failed: {str(e)}"

    finished_at = datetime.utcnow()
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)

    return ResetResponse(
        status="completed",
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        db_deleted=db_deleted,
        storage_deleted=storage_deleted,
        warning=warning,
    )


# -----------------------------------------------------------------------------
# Evaluation endpoints
# -----------------------------------------------------------------------------

from app.schemas.evaluation import (
    EvaluationRunRequest,
    EvaluationRunResponse,
    EvaluationRunSummary,
    EvaluationRunListResponse,
    ArticleEvaluationResult,
    PromptVersionResponse,
    PromptVersionListResponse,
    RollbackRequest,
    RollbackResponse,
    AutoOptimizeConfigRequest,
    AutoOptimizeConfigResponse,
    ScoreComparison,
    MissedItemsSummary,
    PromptChangeDetail,
)


# -----------------------------------------------------------------------------
# Evaluation helper functions
# -----------------------------------------------------------------------------

def _get_score_comparison(
    db: Session,
    current_run: "models.EvaluationRun",
) -> Optional[ScoreComparison]:
    """Compare current evaluation with the most recent previous run."""
    from app import models

    # Find the previous completed evaluation run
    prev_run = (
        db.query(models.EvaluationRun)
        .filter(models.EvaluationRun.status == "completed")
        .filter(models.EvaluationRun.id != current_run.id)
        .filter(models.EvaluationRun.finished_at < current_run.started_at)
        .order_by(models.EvaluationRun.finished_at.desc())
        .first()
    )

    if not prev_run:
        return None

    def safe_delta(current: Optional[float], prev: Optional[float]) -> Optional[float]:
        if current is not None and prev is not None:
            return round(current - prev, 4)
        return None

    def improved(current: Optional[float], prev: Optional[float]) -> Optional[bool]:
        if current is not None and prev is not None:
            return current > prev
        return None

    return ScoreComparison(
        previous_run_id=str(prev_run.id),
        classification_accuracy_prev=prev_run.classification_accuracy,
        classification_accuracy_delta=safe_delta(
            current_run.classification_accuracy, prev_run.classification_accuracy
        ),
        classification_improved=improved(
            current_run.classification_accuracy, prev_run.classification_accuracy
        ),
        neutralization_score_prev=prev_run.avg_neutralization_score,
        neutralization_score_delta=safe_delta(
            current_run.avg_neutralization_score, prev_run.avg_neutralization_score
        ),
        neutralization_improved=improved(
            current_run.avg_neutralization_score, prev_run.avg_neutralization_score
        ),
        span_precision_prev=prev_run.avg_span_precision,
        span_precision_delta=safe_delta(
            current_run.avg_span_precision, prev_run.avg_span_precision
        ),
        span_recall_prev=prev_run.avg_span_recall,
        span_recall_delta=safe_delta(
            current_run.avg_span_recall, prev_run.avg_span_recall
        ),
        overall_score_prev=prev_run.overall_quality_score,
        overall_score_delta=safe_delta(
            current_run.overall_quality_score, prev_run.overall_quality_score
        ),
        overall_improved=improved(
            current_run.overall_quality_score, prev_run.overall_quality_score
        ),
    )


def _aggregate_missed_items(
    article_evals: List["models.ArticleEvaluation"],
) -> MissedItemsSummary:
    """Aggregate missed manipulations and false positives across articles."""
    all_missed = []
    all_false_positives = []
    category_counts: Dict[str, int] = {}

    for ae in article_evals:
        if ae.missed_manipulations:
            for item in ae.missed_manipulations:
                all_missed.append(item)
                cat = item.get("category", "other")
                category_counts[cat] = category_counts.get(cat, 0) + 1

        if ae.false_positives:
            all_false_positives.extend(ae.false_positives)

    return MissedItemsSummary(
        total_missed_count=len(all_missed),
        missed_by_category=category_counts,
        top_missed_phrases=all_missed[:10],  # Top 10 missed phrases
        total_false_positives=len(all_false_positives),
        top_false_positives=all_false_positives[:10],  # Top 10 false positives
    )


@router.post("/evaluation/run", response_model=EvaluationRunResponse)
def run_evaluation(
    request: EvaluationRunRequest = EvaluationRunRequest(),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> EvaluationRunResponse:
    """
    Run a teacher LLM evaluation on a pipeline run.

    Uses configurable teacher model (default: Claude 3.5 Sonnet) to evaluate
    classification, neutralization, and span detection quality.
    Uses separate optimizer model (default: GPT-4o) for prompt improvements.
    """
    from app import models
    from app.services.evaluation_service import EvaluationService
    from app.services.prompt_optimizer import PromptOptimizer

    settings = get_settings()

    # Use config defaults if request uses schema defaults
    eval_model = request.teacher_model
    if eval_model == "gpt-4o":  # Schema default, use config instead
        eval_model = settings.EVAL_MODEL
    optimizer_model = settings.OPTIMIZER_MODEL

    # Determine pipeline run to evaluate
    if request.pipeline_run_id:
        pipeline_run_id = request.pipeline_run_id
    else:
        # Get most recent completed pipeline run
        latest = (
            db.query(models.PipelineRunSummary)
            .filter(models.PipelineRunSummary.status == "completed")
            .order_by(models.PipelineRunSummary.finished_at.desc())
            .first()
        )
        if not latest:
            raise HTTPException(status_code=404, detail="No completed pipeline runs found")
        pipeline_run_id = str(latest.id)

    # Run evaluation with configured eval model
    eval_service = EvaluationService(teacher_model=eval_model)
    result = eval_service.run_evaluation(
        db,
        pipeline_run_id=pipeline_run_id,
        sample_size=request.sample_size,
    )

    # Optionally run auto-optimization with configured optimizer model
    prompts_updated = None
    prompt_changes_detail = None
    if request.enable_auto_optimize and result.status == "completed":
        optimizer = PromptOptimizer(teacher_model=optimizer_model)
        opt_result = optimizer.analyze_and_improve(
            db,
            evaluation_run_id=result.evaluation_run_id,
            auto_apply=True,
        )
        # Convert to PromptUpdate schema (only include applied changes)
        if opt_result.prompts_updated:
            from app.schemas.evaluation import PromptUpdate
            prompts_updated = [
                PromptUpdate(
                    prompt_name=p["prompt_name"],
                    old_version=p["old_version"],
                    new_version=p["new_version"],
                    change_reason=p["change_reason"],
                )
                for p in opt_result.prompts_updated
                if p.get("applied")
            ]
            # Build detailed prompt change info
            prompt_changes_detail = [
                PromptChangeDetail(
                    prompt_name=p["prompt_name"],
                    old_version=p["old_version"],
                    new_version=p["new_version"],
                    change_reason=p["change_reason"],
                    changes_made=p.get("changes_made", []),
                    content_diff_summary=p.get("content_diff_summary"),
                )
                for p in opt_result.prompts_updated
                if p.get("applied")
            ]

    # Get article evaluations for response
    eval_run = db.query(models.EvaluationRun).filter(
        models.EvaluationRun.id == result.evaluation_run_id
    ).first()

    article_evals = None
    score_comparison = None
    missed_items_summary = None

    if eval_run:
        # Compute score comparison with previous run
        score_comparison = _get_score_comparison(db, eval_run)

        # Aggregate missed items from article evaluations
        if eval_run.article_evaluations:
            missed_items_summary = _aggregate_missed_items(eval_run.article_evaluations)

            article_evals = [
                ArticleEvaluationResult(
                    story_raw_id=str(ae.story_raw_id),
                    original_title=ae.story_raw.original_title if ae.story_raw else None,
                    classification_correct=ae.classification_correct,
                    expected_domain=ae.expected_domain,
                    expected_feed_category=ae.expected_feed_category,
                    classification_feedback=ae.classification_feedback,
                    neutralization_score=ae.neutralization_score,
                    meaning_preservation_score=ae.meaning_preservation_score,
                    neutrality_score=ae.neutrality_score,
                    grammar_score=ae.grammar_score,
                    rule_violations=ae.rule_violations,
                    neutralization_feedback=ae.neutralization_feedback,
                    span_precision=ae.span_precision,
                    span_recall=ae.span_recall,
                    missed_manipulations=ae.missed_manipulations,
                    false_positives=ae.false_positives,
                    span_feedback=ae.span_feedback,
                )
                for ae in eval_run.article_evaluations
            ]

    return EvaluationRunResponse(
        id=result.evaluation_run_id,
        pipeline_run_id=pipeline_run_id,
        teacher_model=eval_model,
        sample_size=result.sample_size,
        status=result.status,
        started_at=eval_run.started_at if eval_run else datetime.utcnow(),
        finished_at=eval_run.finished_at if eval_run else None,
        duration_ms=eval_run.duration_ms if eval_run else None,
        classification_accuracy=result.classification_accuracy,
        avg_neutralization_score=result.avg_neutralization_score,
        avg_span_precision=result.avg_span_precision,
        avg_span_recall=result.avg_span_recall,
        overall_quality_score=result.overall_quality_score,
        score_comparison=score_comparison,
        missed_items_summary=missed_items_summary,
        recommendations=result.recommendations,
        prompts_updated=prompts_updated,
        prompt_changes_detail=prompt_changes_detail,
        rollback_triggered=False,
        rollback_details=None,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        estimated_cost_usd=result.estimated_cost_usd,
        article_evaluations=article_evals,
    )


@router.get("/evaluation/runs", response_model=EvaluationRunListResponse)
def list_evaluation_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> EvaluationRunListResponse:
    """List recent evaluation runs."""
    from app import models

    runs = (
        db.query(models.EvaluationRun)
        .order_by(models.EvaluationRun.started_at.desc())
        .limit(limit)
        .all()
    )

    return EvaluationRunListResponse(
        evaluations=[
            EvaluationRunSummary(
                id=str(r.id),
                pipeline_run_id=str(r.pipeline_run_id),
                teacher_model=r.teacher_model,
                sample_size=r.sample_size,
                status=r.status,
                started_at=r.started_at,
                finished_at=r.finished_at,
                duration_ms=r.duration_ms,
                classification_accuracy=r.classification_accuracy,
                avg_neutralization_score=r.avg_neutralization_score,
                overall_quality_score=r.overall_quality_score,
                prompts_updated_count=len(r.prompts_updated) if r.prompts_updated else 0,
                rollback_triggered=r.rollback_triggered,
                estimated_cost_usd=r.estimated_cost_usd,
            )
            for r in runs
        ],
        total=len(runs),
    )


class SendEmailRequest(BaseModel):
    """Request to send evaluation email."""
    recipient: Optional[str] = Field(None, description="Override recipient email address")


class SendEmailResponse(BaseModel):
    """Response from sending evaluation email."""
    status: str
    message_id: Optional[str] = None
    recipient: Optional[str] = None
    error: Optional[str] = None


@router.post("/evaluation/runs/{run_id}/email", response_model=SendEmailResponse)
def send_evaluation_email(
    run_id: str,
    request: SendEmailRequest = SendEmailRequest(),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> SendEmailResponse:
    """
    Manually send or re-send evaluation results email.

    Useful for testing email delivery or re-sending after configuration changes.
    """
    from app.services.email_service import EmailService

    email_service = EmailService()
    result = email_service.send_evaluation_results(
        db,
        evaluation_run_id=run_id,
        recipient=request.recipient,
    )

    return SendEmailResponse(
        status=result.get("status", "unknown"),
        message_id=result.get("message_id"),
        recipient=result.get("recipient"),
        error=result.get("error") or result.get("reason"),
    )


@router.get("/evaluation/runs/{run_id}", response_model=EvaluationRunResponse)
def get_evaluation_run(
    run_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> EvaluationRunResponse:
    """Get detailed evaluation run by ID."""
    from app import models
    import uuid as uuid_module

    eval_run = db.query(models.EvaluationRun).filter(
        models.EvaluationRun.id == uuid_module.UUID(run_id)
    ).first()

    if not eval_run:
        raise HTTPException(status_code=404, detail=f"Evaluation run {run_id} not found")

    # Compute score comparison with previous run
    score_comparison = _get_score_comparison(db, eval_run)

    # Aggregate missed items from article evaluations
    missed_items_summary = None
    if eval_run.article_evaluations:
        missed_items_summary = _aggregate_missed_items(eval_run.article_evaluations)

    article_evals = [
        ArticleEvaluationResult(
            story_raw_id=str(ae.story_raw_id),
            original_title=ae.story_raw.original_title if ae.story_raw else None,
            classification_correct=ae.classification_correct,
            expected_domain=ae.expected_domain,
            expected_feed_category=ae.expected_feed_category,
            classification_feedback=ae.classification_feedback,
            neutralization_score=ae.neutralization_score,
            meaning_preservation_score=ae.meaning_preservation_score,
            neutrality_score=ae.neutrality_score,
            grammar_score=ae.grammar_score,
            rule_violations=ae.rule_violations,
            neutralization_feedback=ae.neutralization_feedback,
            span_precision=ae.span_precision,
            span_recall=ae.span_recall,
            missed_manipulations=ae.missed_manipulations,
            false_positives=ae.false_positives,
            span_feedback=ae.span_feedback,
        )
        for ae in eval_run.article_evaluations
    ]

    # Build prompt_changes_detail from prompts_updated if available
    prompt_changes_detail = None
    if eval_run.prompts_updated:
        prompt_changes_detail = [
            PromptChangeDetail(
                prompt_name=p.get("prompt_name", ""),
                old_version=p.get("old_version", 0),
                new_version=p.get("new_version", 0),
                change_reason=p.get("change_reason", ""),
                changes_made=p.get("changes_made", []),
                content_diff_summary=p.get("content_diff_summary"),
            )
            for p in eval_run.prompts_updated
            if p.get("applied", True)  # Include if applied flag missing (old data)
        ]

    return EvaluationRunResponse(
        id=str(eval_run.id),
        pipeline_run_id=str(eval_run.pipeline_run_id),
        teacher_model=eval_run.teacher_model,
        sample_size=eval_run.sample_size,
        status=eval_run.status,
        started_at=eval_run.started_at,
        finished_at=eval_run.finished_at,
        duration_ms=eval_run.duration_ms,
        classification_accuracy=eval_run.classification_accuracy,
        avg_neutralization_score=eval_run.avg_neutralization_score,
        avg_span_precision=eval_run.avg_span_precision,
        avg_span_recall=eval_run.avg_span_recall,
        overall_quality_score=eval_run.overall_quality_score,
        score_comparison=score_comparison,
        missed_items_summary=missed_items_summary,
        recommendations=eval_run.recommendations,
        prompts_updated=eval_run.prompts_updated,
        prompt_changes_detail=prompt_changes_detail,
        rollback_triggered=eval_run.rollback_triggered,
        rollback_details=eval_run.rollback_details,
        input_tokens=eval_run.input_tokens,
        output_tokens=eval_run.output_tokens,
        estimated_cost_usd=eval_run.estimated_cost_usd,
        article_evaluations=article_evals,
    )


# -----------------------------------------------------------------------------
# Prompt version history endpoints
# -----------------------------------------------------------------------------

@router.get("/prompts/{name}/versions", response_model=PromptVersionListResponse)
def get_prompt_versions(
    name: str,
    model: Optional[str] = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> PromptVersionListResponse:
    """Get version history for a prompt."""
    from app import models
    from app.services.prompt_optimizer import get_prompt_versions

    # Get the prompt
    query = db.query(models.Prompt).filter(models.Prompt.name == name)
    if model:
        query = query.filter(models.Prompt.model == model)
    else:
        query = query.filter(models.Prompt.model.is_(None))

    prompt = query.first()
    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")

    versions = get_prompt_versions(db, name, model)

    return PromptVersionListResponse(
        prompt_name=name,
        prompt_id=str(prompt.id),
        current_version=prompt.version,
        versions=[
            PromptVersionResponse(
                id=str(v.id),
                version=v.version,
                content=v.content,
                change_reason=v.change_reason,
                change_source=v.change_source,
                parent_version_id=str(v.parent_version_id) if v.parent_version_id else None,
                avg_score_at_creation=v.avg_score_at_creation,
                created_at=v.created_at,
            )
            for v in versions
        ],
    )


@router.post("/prompts/{name}/rollback", response_model=RollbackResponse)
def rollback_prompt(
    name: str,
    request: RollbackRequest = RollbackRequest(),
    model: Optional[str] = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> RollbackResponse:
    """Rollback a prompt to a previous version."""
    from app.services.rollback_service import RollbackService

    service = RollbackService()
    result = service.execute_rollback(
        db,
        prompt_name=name,
        model=model,
        target_version=request.target_version,
        reason=request.reason or "Manual rollback",
    )

    return RollbackResponse(
        status="completed" if result.success else "failed",
        prompt_name=result.prompt_name,
        previous_version=result.from_version,
        new_version=result.to_version,
        rollback_reason=result.reason,
        created_at=datetime.utcnow(),
        error=result.error,
    )


@router.post("/prompts/{name}/auto-optimize", response_model=AutoOptimizeConfigResponse)
def configure_auto_optimize(
    name: str,
    request: AutoOptimizeConfigRequest,
    model: Optional[str] = None,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> AutoOptimizeConfigResponse:
    """Configure auto-optimization settings for a prompt."""
    from app import models

    # Get the prompt
    query = db.query(models.Prompt).filter(models.Prompt.name == name)
    if model:
        query = query.filter(models.Prompt.model == model)
    else:
        query = query.filter(models.Prompt.model.is_(None))

    prompt = query.first()
    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")

    # Update settings
    prompt.auto_optimize_enabled = request.enabled
    if request.min_score_threshold is not None:
        prompt.min_score_threshold = request.min_score_threshold
    if request.rollback_threshold is not None:
        prompt.rollback_threshold = request.rollback_threshold
    prompt.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(prompt)

    return AutoOptimizeConfigResponse(
        prompt_name=prompt.name,
        prompt_id=str(prompt.id),
        auto_optimize_enabled=prompt.auto_optimize_enabled,
        min_score_threshold=prompt.min_score_threshold,
        rollback_threshold=prompt.rollback_threshold,
        current_version=prompt.version,
        updated_at=prompt.updated_at,
    )
