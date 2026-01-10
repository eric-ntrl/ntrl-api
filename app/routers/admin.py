# app/routers/admin.py
"""
Admin pipeline endpoints.

POST /v1/ingest/run - Trigger RSS ingestion
POST /v1/neutralize/run - Trigger neutralization
POST /v1/brief/run - Trigger brief assembly
GET  /v1/status - Get system status and configuration
"""

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
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

class StatusResponse(BaseModel):
    """System status response."""
    status: str = "ok"
    neutralizer_provider: str
    neutralizer_model: str
    has_google_api_key: bool
    has_openai_api_key: bool
    has_anthropic_api_key: bool


@router.get("/status", response_model=StatusResponse)
def get_status() -> StatusResponse:
    """
    Get system status and current LLM configuration.

    Returns which neutralizer provider and model are active.
    """
    provider = get_neutralizer_provider()

    return StatusResponse(
        status="ok",
        neutralizer_provider=provider.name,
        neutralizer_model=provider.model_name,
        has_google_api_key=bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")),
        has_openai_api_key=bool(os.getenv("OPENAI_API_KEY")),
        has_anthropic_api_key=bool(os.getenv("ANTHROPIC_API_KEY")),
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
