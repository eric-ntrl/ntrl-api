# app/routers/admin_retention.py
"""
Admin endpoints for retention policy management.

GET  /v1/admin/retention/status - Current retention stats
GET  /v1/admin/retention/policy - Active retention policy
PUT  /v1/admin/retention/policy - Update retention policy
POST /v1/admin/retention/archive - Trigger manual archive
POST /v1/admin/retention/purge - Trigger manual purge
POST /v1/admin/retention/dry-run - Preview what would be archived/purged
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_admin_key
from app.database import get_db
from app.services.retention import (
    archive_batch,
    dry_run_purge,
    ensure_default_policies,
    get_active_policy,
    purge_development_mode,
    purge_expired_content,
    set_policy,
)
from app.services.retention.archive_service import get_retention_stats
from app.services.retention.policy_service import list_policies, update_policy
from app.services.retention.purge_service import cleanup_orphaned_records, get_purge_preview

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/retention", tags=["admin-retention"])


# -----------------------------------------------------------------------------
# Response Models
# -----------------------------------------------------------------------------


class PolicyResponse(BaseModel):
    """Retention policy details."""

    name: str
    active_days: int
    compliance_days: int
    auto_archive: bool
    hard_delete_mode: bool
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class RetentionStatsResponse(BaseModel):
    """Retention statistics."""

    total: int
    by_tier: dict[str, int]
    policy: dict[str, Any]


class ArchiveResponse(BaseModel):
    """Archive operation result."""

    success: bool
    dry_run: bool
    stories_processed: int
    stories_archived: int
    stories_skipped: int
    stories_failed: int
    errors: list[str]


class PurgeResponse(BaseModel):
    """Purge operation result."""

    success: bool
    dry_run: bool
    stories_soft_deleted: int
    stories_hard_deleted: int
    stories_skipped: int
    protected_by_brief: int
    protected_by_hold: int
    related_records_deleted: dict[str, int]
    errors: list[str]


class DryRunResponse(BaseModel):
    """Dry run preview result."""

    dry_run: bool = True
    mode: str
    policy: str | None
    would_soft_delete: int
    would_hard_delete: int
    would_skip: int
    protected_by_brief: int
    protected_by_hold: int


class PolicyUpdateRequest(BaseModel):
    """Request to update or switch policy."""

    name: str | None = Field(None, description="Switch to policy by name")
    active_days: int | None = Field(None, ge=1, le=30, description="Days in active tier")
    compliance_days: int | None = Field(None, ge=7, le=730, description="Days in compliance tier")
    auto_archive: bool | None = Field(None, description="Enable auto archival")
    hard_delete_mode: bool | None = Field(None, description="Skip archival, hard delete")


class ArchiveRequest(BaseModel):
    """Request to trigger archive."""

    batch_size: int = Field(100, ge=1, le=1000, description="Max stories to archive")
    dry_run: bool = Field(False, description="Preview only, don't archive")


class PurgeRequest(BaseModel):
    """Request to trigger purge."""

    batch_size: int = Field(100, ge=1, le=1000, description="Max stories to purge")
    development_mode: bool = Field(False, description="Use development mode (hard delete)")
    days: int | None = Field(None, ge=1, le=365, description="Days threshold for dev mode")
    dry_run: bool = Field(False, description="Preview only, don't purge")
    confirm: bool = Field(False, description="Required confirmation for non-dry-run")


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------


@router.get("/status", response_model=RetentionStatsResponse)
def get_retention_status(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> RetentionStatsResponse:
    """
    Get current retention statistics.

    Returns counts of stories by retention tier (active, compliance,
    pending_deletion, preserved, deleted).
    """
    # Ensure default policies exist
    ensure_default_policies(db)

    stats = get_retention_stats(db)
    if "error" in stats:
        raise HTTPException(status_code=500, detail=stats["error"])

    return RetentionStatsResponse(**stats)


@router.get("/policy", response_model=PolicyResponse)
def get_policy(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> PolicyResponse:
    """
    Get the currently active retention policy.
    """
    ensure_default_policies(db)
    policy = get_active_policy(db)

    if not policy:
        raise HTTPException(status_code=404, detail="No active retention policy")

    return PolicyResponse(
        name=policy.name,
        active_days=policy.active_days,
        compliance_days=policy.compliance_days,
        auto_archive=policy.auto_archive,
        hard_delete_mode=policy.hard_delete_mode,
        is_active=policy.is_active,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


@router.get("/policies")
def list_all_policies(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> list[PolicyResponse]:
    """
    List all available retention policies.
    """
    ensure_default_policies(db)
    policies = list_policies(db)

    return [
        PolicyResponse(
            name=p.name,
            active_days=p.active_days,
            compliance_days=p.compliance_days,
            auto_archive=p.auto_archive,
            hard_delete_mode=p.hard_delete_mode,
            is_active=p.is_active,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in policies
    ]


@router.put("/policy", response_model=PolicyResponse)
def update_retention_policy(
    request: PolicyUpdateRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> PolicyResponse:
    """
    Update or switch the active retention policy.

    To switch policies, provide just the `name` field.
    To update the current policy, provide other fields without `name`.
    """
    ensure_default_policies(db)

    if request.name:
        # Switch to named policy
        try:
            policy = set_policy(db, request.name)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    else:
        # Update current policy
        current = get_active_policy(db)
        if not current:
            raise HTTPException(status_code=404, detail="No active policy to update")

        try:
            policy = update_policy(
                db,
                current.name,
                active_days=request.active_days,
                compliance_days=request.compliance_days,
                auto_archive=request.auto_archive,
                hard_delete_mode=request.hard_delete_mode,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    return PolicyResponse(
        name=policy.name,
        active_days=policy.active_days,
        compliance_days=policy.compliance_days,
        auto_archive=policy.auto_archive,
        hard_delete_mode=policy.hard_delete_mode,
        is_active=policy.is_active,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


@router.post("/archive", response_model=ArchiveResponse)
def trigger_archive(
    request: ArchiveRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> ArchiveResponse:
    """
    Trigger manual archival of expired content.

    Archives stories that have passed the active retention window
    but are still within the compliance window.
    """
    ensure_default_policies(db)

    result = archive_batch(
        db,
        batch_size=request.batch_size,
        initiated_by="admin",
        dry_run=request.dry_run,
    )

    return ArchiveResponse(
        success=result.success,
        dry_run=result.dry_run,
        stories_processed=result.stories_processed,
        stories_archived=result.stories_archived,
        stories_skipped=result.stories_skipped,
        stories_failed=result.stories_failed,
        errors=result.errors,
    )


@router.post("/purge", response_model=PurgeResponse)
def trigger_purge(
    request: PurgeRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> PurgeResponse:
    """
    Trigger manual purge of expired content.

    **WARNING**: This permanently deletes data.

    In production mode:
    - Soft deletes stories past compliance window
    - Hard deletes stories that were soft-deleted 24+ hours ago

    In development mode:
    - Hard deletes all stories older than `days` (default 3)
    - No soft delete grace period

    Requires `confirm: true` for non-dry-run operations.
    """
    ensure_default_policies(db)

    if not request.dry_run and not request.confirm:
        raise HTTPException(
            status_code=400,
            detail="Purge requires 'confirm: true' for non-dry-run operations",
        )

    if request.development_mode:
        result = purge_development_mode(
            db,
            days=request.days or 3,
            batch_size=request.batch_size,
            initiated_by="admin",
            dry_run=request.dry_run,
        )
    else:
        result = purge_expired_content(
            db,
            batch_size=request.batch_size,
            initiated_by="admin",
            dry_run=request.dry_run,
        )

    return PurgeResponse(
        success=result.success,
        dry_run=result.dry_run,
        stories_soft_deleted=result.stories_soft_deleted,
        stories_hard_deleted=result.stories_hard_deleted,
        stories_skipped=result.stories_skipped,
        protected_by_brief=result.protected_by_brief,
        protected_by_hold=result.protected_by_hold,
        related_records_deleted=result.related_records_deleted,
        errors=result.errors,
    )


@router.post("/dry-run", response_model=DryRunResponse)
def preview_purge(
    development_mode: bool = Query(False, description="Use development mode"),
    days: int | None = Query(None, ge=1, le=365, description="Days for dev mode"),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> DryRunResponse:
    """
    Preview what would be purged without making changes.

    Returns counts of stories that would be affected by a purge operation.
    """
    ensure_default_policies(db)

    result = dry_run_purge(
        db,
        days=days,
        development_mode=development_mode,
    )

    return DryRunResponse(**result)


@router.get("/preview")
def get_preview(
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> dict:
    """
    Get a preview of current retention state.

    Shows how many stories are pending soft/hard delete and
    how many are protected.
    """
    ensure_default_policies(db)
    return get_purge_preview(db)


@router.post("/cleanup-orphans")
def cleanup_orphans(
    dry_run: bool = Query(True, description="Preview only"),
    db: Session = Depends(get_db),
    _: None = Depends(require_admin_key),
) -> dict:
    """
    Clean up orphaned records (records referencing deleted stories).

    Use dry_run=true (default) to preview what would be cleaned.
    """
    return cleanup_orphaned_records(db, dry_run=dry_run)
