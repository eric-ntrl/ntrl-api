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


# -----------------------------------------------------------------------------
# Prompt management endpoints
# -----------------------------------------------------------------------------

class PromptResponse(BaseModel):
    """Response for a single prompt."""
    name: str
    content: str
    version: int
    updated_at: Optional[datetime] = None


class PromptUpdateRequest(BaseModel):
    """Request to update a prompt."""
    content: str


class PromptListResponse(BaseModel):
    """Response for listing all prompts."""
    prompts: List[PromptResponse]


@router.get("/prompts", response_model=PromptListResponse)
def list_prompts(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> PromptListResponse:
    """
    List all active prompts.
    """
    from app import models

    prompts = db.query(models.Prompt).filter(models.Prompt.is_active == True).all()
    return PromptListResponse(
        prompts=[
            PromptResponse(
                name=p.name,
                content=p.content,
                version=p.version,
                updated_at=p.updated_at,
            )
            for p in prompts
        ]
    )


@router.get("/prompts/{name}", response_model=PromptResponse)
def get_prompt(
    name: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> PromptResponse:
    """
    Get a specific prompt by name.
    """
    from app import models

    prompt = db.query(models.Prompt).filter(
        models.Prompt.name == name,
        models.Prompt.is_active == True
    ).first()

    if not prompt:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")

    return PromptResponse(
        name=prompt.name,
        content=prompt.content,
        version=prompt.version,
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
    Update a prompt's content. Increments version automatically.
    Creates the prompt if it doesn't exist.
    """
    from app import models

    prompt = db.query(models.Prompt).filter(models.Prompt.name == name).first()

    if prompt:
        # Update existing
        prompt.content = request.content
        prompt.version += 1
        prompt.updated_at = datetime.utcnow()
    else:
        # Create new
        prompt = models.Prompt(
            name=name,
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
    from app.services.neutralizer import _prompt_cache
    _prompt_cache.clear()

    return PromptResponse(
        name=prompt.name,
        content=prompt.content,
        version=prompt.version,
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
    neutral_headline: str
    neutral_summary: str
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
                    neutral_headline=result.neutral_headline,
                    neutral_summary=result.neutral_summary,
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
