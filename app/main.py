# app/main.py

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Any

from fastapi import FastAPI, Depends, HTTPException, status, Header, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.pipeline_service import run_neutral_pipeline
from app.articles import router as articles_router
from app.rss_ingest import ingest_ap_topnews


app = FastAPI(title="Neutral News Backend")

# Includes /articles/{article_raw_id} with redline HTML
app.include_router(articles_router)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "neutral-news-backend"}


# ---------------------------------------------------------------------------
# API key helpers (admin + pipeline)
# ---------------------------------------------------------------------------

def _validate_api_key(
    db: Session,
    *,
    expected_name: str,
    provided_key: Optional[str],
) -> None:
    if not provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    prompt = (
        db.query(models.SystemPrompt)
        .filter(
            models.SystemPrompt.name == expected_name,
            models.SystemPrompt.is_active.is_(True),
        )
        .order_by(models.SystemPrompt.created_at.desc())
        .first()
    )

    if not prompt or prompt.prompt_text != provided_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )


def require_admin_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> None:
    _validate_api_key(db, expected_name="ADMIN_API_KEY", provided_key=x_api_key)


def require_pipeline_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> None:
    _validate_api_key(db, expected_name="PIPELINE_API_KEY", provided_key=x_api_key)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

class AdminPingResponse(BaseModel):
    status: str
    role: str


@app.get("/admin/ping", response_model=AdminPingResponse)
def admin_ping(_: None = Depends(require_admin_api_key)) -> AdminPingResponse:
    return AdminPingResponse(status="ok", role="admin")


# ---------------------------------------------------------------------------
# Pipeline endpoints
# ---------------------------------------------------------------------------

class PipelinePingResponse(BaseModel):
    status: str
    role: str


@app.get("/pipeline/ping", response_model=PipelinePingResponse)
def pipeline_ping(_: None = Depends(require_pipeline_api_key)) -> PipelinePingResponse:
    return PipelinePingResponse(status="ok", role="pipeline")


class PipelineRunRequest(BaseModel):
    source_name: str
    source_url: str
    published_at: datetime

    title: str
    description: Optional[str] = None
    body: Optional[str] = None


class PipelineRunResponse(BaseModel):
    status: str
    pipeline_run_id: str
    article_raw_id: str
    article_summary_id: str
    neutral_title: str
    neutral_summary_short: str
    neutrality_score: int
    bias_terms: List[Any]
    bias_spans: Optional[Any] = None
    reading_level: int
    political_lean: float


@app.post("/pipeline/run", response_model=PipelineRunResponse)
def pipeline_run(
    payload: PipelineRunRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_pipeline_api_key),
) -> PipelineRunResponse:
    try:
        result = run_neutral_pipeline(
            db,
            source_name=payload.source_name,
            source_url=payload.source_url,
            published_at=payload.published_at,
            title=payload.title,
            description=payload.description,
            body=payload.body,
            raw_payload=payload.model_dump(),  # pydantic v2 safe
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline failed: {exc}",
        )

    return PipelineRunResponse(
        status="completed",
        pipeline_run_id=result["pipeline_run_id"],
        article_raw_id=result["article_raw_id"],
        article_summary_id=result["article_summary_id"],
        neutral_title=result["neutral_title"],
        neutral_summary_short=result["neutral_summary_short"],
        neutrality_score=result["neutrality_score"],
        bias_terms=result["bias_terms"],
        bias_spans=result.get("bias_spans"),
        reading_level=result["reading_level"],
        political_lean=result["political_lean"],
    )


# ---------------------------------------------------------------------------
# RSS/Feed ingestion endpoint (AP)
# ---------------------------------------------------------------------------

class RssIngestResponse(BaseModel):
    status: str
    rss_url: Optional[str] = None
    used_rss_url: Optional[str] = None
    ingested: int
    skipped_existing: int
    max_items: int
    error: Optional[str] = None
    attempts: Optional[Any] = None
    errors: List[Any] = []


@app.post("/pipeline/ingest/ap", response_model=RssIngestResponse)
def pipeline_ingest_ap(
    db: Session = Depends(get_db),
    _: None = Depends(require_pipeline_api_key),
    max_items: int = Query(10, ge=1, le=50),
) -> RssIngestResponse:
    """
    Ingest AP Top News.
    Tries RSS candidates first; if RSS fails, falls back to scraping AP's tag page.
    Always returns a response that includes max_items (so it won't crash validation).
    """
    try:
        result = ingest_ap_topnews(db, max_items=max_items)
        # Make sure required fields exist even on weird failures
        result.setdefault("status", "error")
        result.setdefault("ingested", 0)
        result.setdefault("skipped_existing", 0)
        result.setdefault("max_items", max_items)
        result.setdefault("errors", [])
        return RssIngestResponse(**result)
    except Exception as exc:
        return RssIngestResponse(
            status="error",
            rss_url=None,
            used_rss_url=None,
            ingested=0,
            skipped_existing=0,
            max_items=max_items,
            error=f"AP ingest failed: {exc}",
            attempts=None,
            errors=[],
        )


# ---------------------------------------------------------------------------
# Feed (public read API for the mobile app)
# ---------------------------------------------------------------------------

class FeedItem(BaseModel):
    article_raw_id: str
    source_name: str
    source_domain: str
    source_url: str
    published_at: datetime

    neutral_title: str
    neutral_summary_short: str
    neutrality_score: Optional[int] = None
    bias_terms: Optional[Any] = None
    bias_spans: Optional[Any] = None


@app.get("/feed", response_model=List[FeedItem])
def get_feed(
    db: Session = Depends(get_db),
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> List[FeedItem]:
    rows = (
        db.query(models.ArticleSummary, models.ArticleRaw, models.Source)
        .join(models.ArticleRaw, models.ArticleSummary.article_raw_id == models.ArticleRaw.id)
        .join(models.Source, models.ArticleRaw.source_id == models.Source.id)
        .filter(models.ArticleSummary.is_current.is_(True))
        .order_by(models.ArticleRaw.published_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    out: List[FeedItem] = []
    for summary, raw, source in rows:
        out.append(
            FeedItem(
                article_raw_id=str(raw.id),
                source_name=source.name,
                source_domain=source.domain,
                source_url=raw.source_url,
                published_at=raw.published_at,
                neutral_title=summary.neutral_title,
                neutral_summary_short=summary.neutral_summary_short,
                neutrality_score=summary.neutrality_score,
                bias_terms=summary.bias_terms,
                bias_spans=getattr(summary, "bias_spans", None),
            )
        )
    return out
