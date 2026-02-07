# app/routers/sources.py
"""
Source management endpoints.

GET    /v1/sources           - List all sources
POST   /v1/sources           - Add a source
DELETE /v1/sources/{slug}    - Remove a source
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import models
from app.database import get_db

router = APIRouter(prefix="/v1/sources", tags=["sources"])


# -----------------------------------------------------------------------------
# Schemas
# -----------------------------------------------------------------------------


class SourceCreate(BaseModel):
    """Request to create a new source."""

    name: str = Field(..., description="Display name", min_length=1, max_length=255)
    slug: str = Field(..., description="Unique identifier (e.g., 'npr', 'bbc')", min_length=1, max_length=64)
    rss_url: str = Field(..., description="RSS feed URL")
    default_section: str | None = Field(None, description="Default section: world, us, local, business, technology")
    is_active: bool = Field(True, description="Whether to ingest from this source")


class SourceResponse(BaseModel):
    """Source response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    rss_url: str
    default_section: str | None
    is_active: bool
    created_at: datetime


class SourceListResponse(BaseModel):
    """List of sources."""

    sources: list[SourceResponse]
    total: int


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------


@router.get("", response_model=SourceListResponse)
def list_sources(
    active_only: bool = False,
    db: Session = Depends(get_db),
) -> SourceListResponse:
    """List all sources."""
    query = db.query(models.Source)
    if active_only:
        query = query.filter(models.Source.is_active == True)

    sources = query.order_by(models.Source.name).all()

    return SourceListResponse(
        sources=[
            SourceResponse(
                id=str(s.id),
                name=s.name,
                slug=s.slug,
                rss_url=s.rss_url,
                default_section=s.default_section,
                is_active=s.is_active,
                created_at=s.created_at,
            )
            for s in sources
        ],
        total=len(sources),
    )


@router.post("", response_model=SourceResponse, status_code=201)
def create_source(
    request: SourceCreate,
    db: Session = Depends(get_db),
) -> SourceResponse:
    """Add a new source."""
    # Check if slug already exists
    existing = db.query(models.Source).filter(models.Source.slug == request.slug).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Source with slug '{request.slug}' already exists")

    # Validate section if provided
    valid_sections = ["world", "us", "local", "business", "technology"]
    if request.default_section and request.default_section not in valid_sections:
        raise HTTPException(status_code=400, detail=f"Invalid section. Must be one of: {', '.join(valid_sections)}")

    source = models.Source(
        id=uuid.uuid4(),
        name=request.name,
        slug=request.slug.lower().strip(),
        rss_url=request.rss_url,
        default_section=request.default_section,
        is_active=request.is_active,
        created_at=datetime.utcnow(),
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    return SourceResponse(
        id=str(source.id),
        name=source.name,
        slug=source.slug,
        rss_url=source.rss_url,
        default_section=source.default_section,
        is_active=source.is_active,
        created_at=source.created_at,
    )


@router.delete("/{slug}", status_code=204)
def delete_source(
    slug: str,
    db: Session = Depends(get_db),
):
    """
    Remove a source.

    If stories exist from this source, deactivates it instead of deleting.
    """
    source = db.query(models.Source).filter(models.Source.slug == slug).first()
    if not source:
        raise HTTPException(status_code=404, detail=f"Source '{slug}' not found")

    # Check if there are stories from this source
    story_count = db.query(models.StoryRaw).filter(models.StoryRaw.source_id == source.id).count()

    if story_count > 0:
        # Deactivate instead of delete to preserve data integrity
        source.is_active = False
        db.commit()
    else:
        db.delete(source)
        db.commit()

    return None
