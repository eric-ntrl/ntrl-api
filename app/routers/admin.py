# app/routers/admin.py
"""
Admin pipeline endpoints.

POST /v1/ingest/run - Trigger RSS ingestion
POST /v1/neutralize/run - Trigger neutralization
POST /v1/brief/run - Trigger brief assembly
POST /v1/pipeline/run - Run full pipeline (ingest + neutralize + brief)
GET  /v1/status - Get system status and configuration
"""

import os
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.admin import (
    IngestRunRequest,
    IngestRunResponse,
    IngestSourceResult,
    NeutralizeRunRequest,
    NeutralizeRunResponse,
    NeutralizeStoryResult,
    BriefRunRequest,
    BriefRunResponse,
    BriefSectionResult,
)
from app.services.ingestion import IngestionService
from app.services.neutralizer import NeutralizerService, get_neutralizer_provider
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


class StatusResponse(BaseModel):
    """System status response."""
    status: str = "ok"
    neutralizer_provider: str
    neutralizer_model: str
    has_google_api_key: bool
    has_openai_api_key: bool
    has_anthropic_api_key: bool
    total_articles_ingested: int = 0
    total_articles_neutralized: int = 0
    total_sources: int = 0
    last_ingest: Optional[LastRunInfo] = None
    last_neutralize: Optional[LastRunInfo] = None
    last_brief: Optional[LastRunInfo] = None


@router.get("/status", response_model=StatusResponse)
def get_status(
    db: Session = Depends(get_db),
) -> StatusResponse:
    """
    Get system status and current LLM configuration.

    Returns which neutralizer provider and model are active,
    plus timestamps of last pipeline runs.
    """
    from app import models

    provider = get_neutralizer_provider()

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

    return StatusResponse(
        status="ok",
        neutralizer_provider=provider.name,
        neutralizer_model=provider.model_name,
        has_google_api_key=bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")),
        has_openai_api_key=bool(os.getenv("OPENAI_API_KEY")),
        has_anthropic_api_key=bool(os.getenv("ANTHROPIC_API_KEY")),
        total_articles_ingested=total_ingested,
        total_articles_neutralized=total_neutralized,
        total_sources=total_sources,
        last_ingest=get_last_run("ingest"),
        last_neutralize=get_last_run("neutralize"),
        last_brief=get_last_run("brief_assemble"),
    )


def require_admin_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> None:
    """Validate admin API key."""
    expected_key = os.getenv("ADMIN_API_KEY")

    # Allow no auth in development if key not set
    if not expected_key:
        return

    if not x_api_key or x_api_key != expected_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key",
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
    service = NeutralizerService()
    result = service.neutralize_pending(
        db,
        story_ids=request.story_ids,
        force=request.force,
        limit=request.limit,
        max_workers=request.max_workers,
    )

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

    # Stage 2: Neutralize
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

    # Stage 3: Brief assembly
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

    return PipelineRunResponse(
        status=overall_status,
        started_at=started_at,
        finished_at=finished_at,
        total_duration_ms=total_duration_ms,
        stages=stages,
        summary={
            'articles_ingested': stages[0].details.get('total_ingested', 0) if stages else 0,
            'articles_neutralized': stages[1].details.get('total_processed', 0) if len(stages) > 1 else 0,
            'stories_in_brief': stages[2].details.get('total_stories', 0) if len(stages) > 2 else 0,
            'errors': errors,
        }
    )
