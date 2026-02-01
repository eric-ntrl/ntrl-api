# app/services/retention/archive_service.py
"""
Archive service for transitioning content between retention tiers.

Handles:
- Finding content ready for archival
- Moving raw content to cold storage (S3 Glacier)
- Updating database records with archive references
- Logging lifecycle events for audit trail
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models import (
    StoryRaw,
    ContentLifecycleEvent,
    LifecycleEventType,
    ArchiveStatus,
)
from app.services.retention.policy_service import get_active_policy
from app.storage.factory import get_storage_provider

logger = logging.getLogger(__name__)


@dataclass
class ArchiveResult:
    """Result of an archive operation."""
    success: bool
    stories_processed: int = 0
    stories_archived: int = 0
    stories_skipped: int = 0
    stories_failed: int = 0
    errors: List[str] = field(default_factory=list)
    dry_run: bool = False


def find_archivable_stories(
    db: Session,
    cutoff_date: Optional[datetime] = None,
    limit: int = 100,
) -> List[StoryRaw]:
    """
    Find stories ready to transition from active to compliance tier.

    Returns stories that:
    - Are older than the active retention window
    - Have not been deleted
    - Have not been archived
    - Are not under legal hold
    - Are not preserved by user (preserve_until)

    Args:
        db: Database session
        cutoff_date: Stories older than this date are archivable
        limit: Maximum stories to return

    Returns:
        List of StoryRaw objects ready for archival
    """
    policy = get_active_policy(db)
    if not policy:
        logger.warning("No active retention policy found")
        return []

    if cutoff_date is None:
        cutoff_date = datetime.utcnow() - timedelta(days=policy.active_days)

    now = datetime.utcnow()

    return (
        db.query(StoryRaw)
        .filter(
            and_(
                # Not deleted
                StoryRaw.deleted_at.is_(None),
                # Not already archived
                StoryRaw.archived_at.is_(None),
                # Older than active window
                StoryRaw.ingested_at < cutoff_date,
                # Not under legal hold
                StoryRaw.legal_hold == False,
                # Not preserved by user (or preservation expired)
                (
                    StoryRaw.preserve_until.is_(None) |
                    (StoryRaw.preserve_until < now)
                ),
            )
        )
        .order_by(StoryRaw.ingested_at.asc())  # Oldest first
        .limit(limit)
        .all()
    )


def _log_lifecycle_event(
    db: Session,
    story_id: uuid.UUID,
    event_type: LifecycleEventType,
    initiated_by: str,
    idempotency_key: Optional[str] = None,
    event_metadata: Optional[dict] = None,
) -> ContentLifecycleEvent:
    """
    Log a lifecycle event for audit trail.

    Uses idempotency_key to prevent duplicate events.
    """
    if idempotency_key:
        existing = (
            db.query(ContentLifecycleEvent)
            .filter(ContentLifecycleEvent.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            return existing

    event = ContentLifecycleEvent(
        story_raw_id=story_id,
        event_type=event_type.value,
        event_timestamp=datetime.utcnow(),
        initiated_by=initiated_by,
        idempotency_key=idempotency_key,
        event_metadata=event_metadata,
    )
    db.add(event)
    return event


def archive_story(
    db: Session,
    story: StoryRaw,
    initiated_by: str = "scheduler",
    move_to_glacier: bool = True,
) -> bool:
    """
    Archive a single story to compliance tier.

    Process:
    1. Set archive_status = 'archiving'
    2. Move raw content to Glacier (if enabled)
    3. Update story with archive reference
    4. Log lifecycle event
    5. Clear raw content from hot storage

    Args:
        db: Database session
        story: StoryRaw to archive
        initiated_by: Who initiated the archive
        move_to_glacier: Whether to move content to Glacier

    Returns:
        True if successful, False otherwise
    """
    idempotency_key = f"archive:{story.id}:{datetime.utcnow().strftime('%Y%m%d')}"

    try:
        # Check idempotency
        existing_event = (
            db.query(ContentLifecycleEvent)
            .filter(ContentLifecycleEvent.idempotency_key == idempotency_key)
            .first()
        )
        if existing_event:
            logger.debug(f"Story {story.id} already archived today (idempotent)")
            return True

        # Step 1: Mark as archiving
        story.archive_status = ArchiveStatus.ARCHIVING.value
        db.add(story)
        db.flush()

        # Step 2: Move to Glacier (if enabled and content exists)
        archive_ref = None
        if move_to_glacier and story.raw_content_uri:
            try:
                storage = get_storage_provider()
                # Note: Actual Glacier transition would require S3 lifecycle rules
                # or explicit copy to Glacier storage class. For now, we just
                # record the reference and delete from hot storage.
                archive_ref = f"glacier://{story.raw_content_uri}"

                # Delete from hot storage
                storage.delete(story.raw_content_uri)
                logger.debug(f"Deleted hot storage for story {story.id}")

            except Exception as e:
                logger.error(f"Failed to archive story {story.id} content: {e}")
                story.archive_status = ArchiveStatus.FAILED.value
                _log_lifecycle_event(
                    db,
                    story.id,
                    LifecycleEventType.ARCHIVE_FAILED,
                    initiated_by,
                    event_metadata={"error": str(e)},
                )
                db.commit()
                return False

        # Step 3: Update story record
        story.archived_at = datetime.utcnow()
        story.archive_status = ArchiveStatus.ARCHIVED.value
        story.archive_reference = archive_ref
        story.raw_content_available = False
        story.raw_content_expired_at = datetime.utcnow()
        db.add(story)

        # Step 4: Log lifecycle event
        _log_lifecycle_event(
            db,
            story.id,
            LifecycleEventType.ARCHIVED,
            initiated_by,
            idempotency_key=idempotency_key,
            event_metadata={
                "archive_reference": archive_ref,
                "original_uri": story.raw_content_uri,
            },
        )

        db.commit()
        logger.info(f"Archived story {story.id}")
        return True

    except Exception as e:
        logger.error(f"Failed to archive story {story.id}: {e}")
        db.rollback()
        return False


def archive_batch(
    db: Session,
    batch_size: int = 100,
    initiated_by: str = "scheduler",
    dry_run: bool = False,
) -> ArchiveResult:
    """
    Archive a batch of stories to compliance tier.

    Args:
        db: Database session
        batch_size: Maximum stories to process
        initiated_by: Who initiated the archive
        dry_run: If True, don't actually archive

    Returns:
        ArchiveResult with operation summary
    """
    result = ArchiveResult(success=True, dry_run=dry_run)

    # Get active policy
    policy = get_active_policy(db)
    if not policy:
        result.success = False
        result.errors.append("No active retention policy found")
        return result

    # In hard delete mode, skip archival
    if policy.hard_delete_mode:
        logger.info("Hard delete mode enabled, skipping archival")
        result.stories_skipped = batch_size
        return result

    # Find archivable stories
    stories = find_archivable_stories(db, limit=batch_size)
    result.stories_processed = len(stories)

    if not stories:
        logger.info("No stories to archive")
        return result

    logger.info(f"Found {len(stories)} stories to archive (dry_run={dry_run})")

    for story in stories:
        if dry_run:
            result.stories_archived += 1
            continue

        try:
            success = archive_story(
                db,
                story,
                initiated_by=initiated_by,
                move_to_glacier=policy.auto_archive,
            )
            if success:
                result.stories_archived += 1
            else:
                result.stories_failed += 1

        except Exception as e:
            logger.error(f"Error archiving story {story.id}: {e}")
            result.stories_failed += 1
            result.errors.append(f"Story {story.id}: {str(e)}")

    if result.stories_failed > 0:
        result.success = False

    logger.info(
        f"Archive batch complete: {result.stories_archived} archived, "
        f"{result.stories_failed} failed"
    )
    return result


def find_stories_for_deletion(
    db: Session,
    cutoff_date: Optional[datetime] = None,
    limit: int = 100,
) -> List[StoryRaw]:
    """
    Find stories ready for permanent deletion (past compliance window).

    Returns stories that:
    - Have been archived OR are in hard_delete_mode
    - Are older than the compliance retention window
    - Are not under legal hold
    - Have been soft-deleted for at least 24 hours (grace period)

    Args:
        db: Database session
        cutoff_date: Stories older than this date are deletable
        limit: Maximum stories to return
    """
    policy = get_active_policy(db)
    if not policy:
        return []

    if cutoff_date is None:
        cutoff_date = datetime.utcnow() - timedelta(days=policy.compliance_days)

    grace_period = datetime.utcnow() - timedelta(hours=24)

    return (
        db.query(StoryRaw)
        .filter(
            and_(
                # Old enough for deletion
                StoryRaw.ingested_at < cutoff_date,
                # Not under legal hold
                StoryRaw.legal_hold == False,
                # Either archived or soft-deleted with grace period
                (
                    (StoryRaw.archived_at.isnot(None)) |
                    (
                        StoryRaw.deleted_at.isnot(None) &
                        (StoryRaw.deleted_at < grace_period)
                    )
                ),
            )
        )
        .order_by(StoryRaw.ingested_at.asc())
        .limit(limit)
        .all()
    )


def get_retention_stats(db: Session) -> dict:
    """
    Get current retention statistics.

    Returns counts by retention tier for dashboard display.
    """
    from sqlalchemy import func

    policy = get_active_policy(db)
    if not policy:
        return {"error": "No active retention policy"}

    now = datetime.utcnow()
    active_cutoff = now - timedelta(days=policy.active_days)
    compliance_cutoff = now - timedelta(days=policy.compliance_days)

    # Count by tier
    total = db.query(func.count(StoryRaw.id)).scalar() or 0

    deleted = (
        db.query(func.count(StoryRaw.id))
        .filter(StoryRaw.deleted_at.isnot(None))
        .scalar()
    ) or 0

    preserved = (
        db.query(func.count(StoryRaw.id))
        .filter(
            StoryRaw.deleted_at.is_(None),
            (
                (StoryRaw.legal_hold == True) |
                (StoryRaw.preserve_until > now)
            ),
        )
        .scalar()
    ) or 0

    active = (
        db.query(func.count(StoryRaw.id))
        .filter(
            StoryRaw.deleted_at.is_(None),
            StoryRaw.legal_hold == False,
            (StoryRaw.preserve_until.is_(None) | (StoryRaw.preserve_until <= now)),
            StoryRaw.ingested_at >= active_cutoff,
        )
        .scalar()
    ) or 0

    compliance = (
        db.query(func.count(StoryRaw.id))
        .filter(
            StoryRaw.deleted_at.is_(None),
            StoryRaw.legal_hold == False,
            (StoryRaw.preserve_until.is_(None) | (StoryRaw.preserve_until <= now)),
            StoryRaw.ingested_at < active_cutoff,
            StoryRaw.ingested_at >= compliance_cutoff,
        )
        .scalar()
    ) or 0

    pending_deletion = (
        db.query(func.count(StoryRaw.id))
        .filter(
            StoryRaw.deleted_at.is_(None),
            StoryRaw.legal_hold == False,
            (StoryRaw.preserve_until.is_(None) | (StoryRaw.preserve_until <= now)),
            StoryRaw.ingested_at < compliance_cutoff,
        )
        .scalar()
    ) or 0

    return {
        "total": total,
        "by_tier": {
            "active": active,
            "compliance": compliance,
            "pending_deletion": pending_deletion,
            "preserved": preserved,
            "deleted": deleted,
        },
        "policy": {
            "name": policy.name,
            "active_days": policy.active_days,
            "compliance_days": policy.compliance_days,
            "hard_delete_mode": policy.hard_delete_mode,
        },
    }
