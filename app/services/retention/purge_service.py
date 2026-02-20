# app/services/retention/purge_service.py
"""
Purge service for cascade-safe permanent deletion.

Handles:
- Safe deletion order respecting FK constraints
- Soft delete with grace period
- Hard delete for development mode
- Protection of active brief articles
- Cache invalidation after deletion
"""

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models import (
    ArticleEvaluation,
    ContentLifecycleEvent,
    DailyBrief,
    DailyBriefItem,
    LifecycleEventType,
    ManipulationSpan,
    PipelineLog,
    StoryNeutralized,
    StoryRaw,
    TransparencySpan,
)
from app.services.retention.policy_service import get_active_policy

logger = logging.getLogger(__name__)

# Brief protection window (hours) - never delete articles that could be in current brief
BRIEF_PROTECTION_HOURS = int(os.getenv("BRIEF_CUTOFF_HOURS", "24"))


@dataclass
class PurgeResult:
    """Result of a purge operation."""

    success: bool
    dry_run: bool = False
    stories_soft_deleted: int = 0
    stories_hard_deleted: int = 0
    stories_skipped: int = 0
    related_records_deleted: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    protected_by_brief: int = 0
    protected_by_hold: int = 0


def _get_brief_protected_story_ids(db: Session) -> set[uuid.UUID]:
    """
    Get IDs of stories in the current brief (protected from deletion).

    Returns set of StoryRaw IDs that are in the current brief.
    """
    # Get current brief
    brief = db.query(DailyBrief).filter(DailyBrief.is_current == True).first()

    if not brief:
        return set()

    # Get story_raw_ids from brief items via neutralized
    items = db.query(DailyBriefItem).filter(DailyBriefItem.brief_id == brief.id).all()
    neutralized_ids = [item.story_neutralized_id for item in items]

    if not neutralized_ids:
        return set()

    # Get raw IDs from neutralized
    neutralized = db.query(StoryNeutralized.story_raw_id).filter(StoryNeutralized.id.in_(neutralized_ids)).all()

    return {n.story_raw_id for n in neutralized}


def _invalidate_caches():
    """Invalidate brief and story caches after deletion."""
    try:
        from app.routers.brief import invalidate_brief_cache

        invalidate_brief_cache()
        logger.debug("Brief cache invalidated")
    except Exception as e:
        logger.warning(f"Failed to invalidate brief cache: {e}")

    try:
        from app.routers.stories import _story_cache, _transparency_cache

        _story_cache.clear()
        _transparency_cache.clear()
        logger.debug("Story caches invalidated")
    except Exception as e:
        logger.warning(f"Failed to invalidate story caches: {e}")


def _log_lifecycle_event(
    db: Session,
    story_id: uuid.UUID,
    event_type: LifecycleEventType,
    initiated_by: str,
    idempotency_key: str | None = None,
    event_metadata: dict | None = None,
):
    """Log a lifecycle event for audit trail."""
    if idempotency_key:
        existing = (
            db.query(ContentLifecycleEvent).filter(ContentLifecycleEvent.idempotency_key == idempotency_key).first()
        )
        if existing:
            return existing

    event = ContentLifecycleEvent(
        story_raw_id=story_id,
        event_type=event_type.value,
        event_timestamp=datetime.now(UTC),
        initiated_by=initiated_by,
        idempotency_key=idempotency_key,
        event_metadata=event_metadata,
    )
    db.add(event)
    return event


def soft_delete_story(
    db: Session,
    story: StoryRaw,
    reason: str = "retention",
    initiated_by: str = "scheduler",
) -> bool:
    """
    Soft delete a story (tombstone pattern).

    Sets deleted_at and deletion_reason but doesn't remove records.
    Actual deletion happens after grace period.
    """
    if story.deleted_at:
        return True  # Already soft deleted

    if story.legal_hold:
        logger.warning(f"Cannot delete story {story.id} - under legal hold")
        return False

    now = datetime.now(UTC)
    if story.preserve_until and story.preserve_until > now:
        logger.warning(f"Cannot delete story {story.id} - preserved until {story.preserve_until}")
        return False

    story.deleted_at = now
    story.deletion_reason = reason
    db.add(story)

    _log_lifecycle_event(
        db,
        story.id,
        LifecycleEventType.SOFT_DELETED,
        initiated_by,
        idempotency_key=f"soft_delete:{story.id}:{now.strftime('%Y%m%d')}",
        event_metadata={"reason": reason},
    )

    logger.debug(f"Soft deleted story {story.id} (reason: {reason})")
    return True


def _hard_delete_story_cascade(
    db: Session,
    story: StoryRaw,
    initiated_by: str = "scheduler",
) -> dict:
    """
    Hard delete a story and all related records.

    Follows cascade-safe deletion order (leaf-to-root):
    1. TransparencySpan, ManipulationSpan (pure leaf)
    2. ArticleEvaluation (references StoryRaw)
    3. DailyBriefItem (references StoryNeutralized)
    4. StoryNeutralized (references StoryRaw)
    5. PipelineLog (references StoryRaw)
    6. StoryRaw (root)

    Returns dict with counts of deleted records by table.
    """
    story_id = story.id
    counts = {}

    # Get all neutralized versions for this story
    neutralized_ids = [
        n.id for n in db.query(StoryNeutralized.id).filter(StoryNeutralized.story_raw_id == story_id).all()
    ]

    # Level 1: Pure leaf tables
    counts["transparency_spans"] = (
        (
            db.query(TransparencySpan)
            .filter(TransparencySpan.story_neutralized_id.in_(neutralized_ids))
            .delete(synchronize_session=False)
        )
        if neutralized_ids
        else 0
    )

    counts["manipulation_spans"] = (
        (
            db.query(ManipulationSpan)
            .filter(ManipulationSpan.story_neutralized_id.in_(neutralized_ids))
            .delete(synchronize_session=False)
        )
        if neutralized_ids
        else 0
    )

    counts["daily_brief_items"] = (
        (
            db.query(DailyBriefItem)
            .filter(DailyBriefItem.story_neutralized_id.in_(neutralized_ids))
            .delete(synchronize_session=False)
        )
        if neutralized_ids
        else 0
    )

    counts["article_evaluations"] = (
        db.query(ArticleEvaluation).filter(ArticleEvaluation.story_raw_id == story_id).delete(synchronize_session=False)
    )

    # Level 2: StoryNeutralized
    counts["stories_neutralized"] = (
        db.query(StoryNeutralized).filter(StoryNeutralized.story_raw_id == story_id).delete(synchronize_session=False)
    )

    # Level 3: PipelineLog (references StoryRaw)
    counts["pipeline_logs"] = (
        db.query(PipelineLog).filter(PipelineLog.story_raw_id == story_id).delete(synchronize_session=False)
    )

    # Log before deleting
    _log_lifecycle_event(
        db,
        story_id,
        LifecycleEventType.HARD_DELETED,
        initiated_by,
        idempotency_key=f"hard_delete:{story_id}:{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        event_metadata={"deleted_counts": counts},
    )

    # Level 4: StoryRaw (root)
    db.query(StoryRaw).filter(StoryRaw.id == story_id).delete(synchronize_session=False)
    counts["stories_raw"] = 1

    return counts


def purge_expired_content(
    db: Session,
    batch_size: int = 100,
    initiated_by: str = "scheduler",
    dry_run: bool = False,
) -> PurgeResult:
    """
    Purge content that has passed the compliance retention window.

    This is the main purge function for production use. It:
    1. Finds stories older than compliance_days
    2. Soft deletes them (if not already)
    3. Hard deletes stories that have been soft-deleted for 24+ hours

    Stories in the current brief are always protected.
    """
    result = PurgeResult(success=True, dry_run=dry_run)

    policy = get_active_policy(db)
    if not policy:
        result.success = False
        result.errors.append("No active retention policy found")
        return result

    # Get protected story IDs
    protected_ids = _get_brief_protected_story_ids(db)
    result.protected_by_brief = len(protected_ids)

    # Find stories past compliance window
    compliance_cutoff = datetime.now(UTC) - timedelta(days=policy.compliance_days)
    grace_period_cutoff = datetime.now(UTC) - timedelta(hours=24)

    # Step 1: Soft delete stories past compliance window (not already deleted)
    stories_to_soft_delete = (
        db.query(StoryRaw)
        .filter(
            and_(
                StoryRaw.ingested_at < compliance_cutoff,
                StoryRaw.deleted_at.is_(None),
                StoryRaw.legal_hold == False,
                ~StoryRaw.id.in_(protected_ids) if protected_ids else True,
            )
        )
        .limit(batch_size)
        .all()
    )

    for story in stories_to_soft_delete:
        if story.preserve_until and story.preserve_until > datetime.now(UTC):
            result.protected_by_hold += 1
            result.stories_skipped += 1
            continue

        if dry_run:
            result.stories_soft_deleted += 1
        else:
            if soft_delete_story(db, story, reason="retention", initiated_by=initiated_by):
                result.stories_soft_deleted += 1
            else:
                result.stories_skipped += 1

    # Step 2: Hard delete stories that were soft-deleted 24+ hours ago
    stories_to_hard_delete = (
        db.query(StoryRaw)
        .filter(
            and_(
                StoryRaw.deleted_at.isnot(None),
                StoryRaw.deleted_at < grace_period_cutoff,
                StoryRaw.legal_hold == False,
                ~StoryRaw.id.in_(protected_ids) if protected_ids else True,
            )
        )
        .limit(batch_size)
        .all()
    )

    for story in stories_to_hard_delete:
        if dry_run:
            result.stories_hard_deleted += 1
        else:
            try:
                counts = _hard_delete_story_cascade(db, story, initiated_by=initiated_by)
                result.stories_hard_deleted += 1

                # Aggregate counts
                for table, count in counts.items():
                    result.related_records_deleted[table] = result.related_records_deleted.get(table, 0) + count

            except Exception as e:
                logger.error(f"Failed to hard delete story {story.id}: {e}")
                result.errors.append(f"Story {story.id}: {str(e)}")
                result.success = False

    if not dry_run:
        db.commit()
        _invalidate_caches()

    logger.info(
        f"Purge complete: {result.stories_soft_deleted} soft deleted, "
        f"{result.stories_hard_deleted} hard deleted, "
        f"{result.stories_skipped} skipped (dry_run={dry_run})"
    )
    return result


def purge_development_mode(
    db: Session,
    days: int = 3,
    batch_size: int = 100,
    initiated_by: str = "admin",
    dry_run: bool = False,
) -> PurgeResult:
    """
    Development mode purge - hard delete all content older than N days.

    Bypasses soft delete grace period and archives. Use for clean iteration
    during development.

    WARNING: This permanently deletes data. Use with caution.
    """
    result = PurgeResult(success=True, dry_run=dry_run)

    # Get protected story IDs (still protect current brief)
    protected_ids = _get_brief_protected_story_ids(db)
    result.protected_by_brief = len(protected_ids)

    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Find all stories older than cutoff
    stories = (
        db.query(StoryRaw)
        .filter(
            and_(
                StoryRaw.ingested_at < cutoff,
                StoryRaw.legal_hold == False,
                ~StoryRaw.id.in_(protected_ids) if protected_ids else True,
            )
        )
        .limit(batch_size)
        .all()
    )

    logger.info(f"Development purge: found {len(stories)} stories older than {days} days")

    for story in stories:
        if story.preserve_until and story.preserve_until > datetime.now(UTC):
            result.protected_by_hold += 1
            result.stories_skipped += 1
            continue

        if dry_run:
            result.stories_hard_deleted += 1
        else:
            try:
                counts = _hard_delete_story_cascade(db, story, initiated_by=initiated_by)
                result.stories_hard_deleted += 1

                for table, count in counts.items():
                    result.related_records_deleted[table] = result.related_records_deleted.get(table, 0) + count

            except Exception as e:
                logger.error(f"Failed to delete story {story.id}: {e}")
                result.errors.append(f"Story {story.id}: {str(e)}")
                result.success = False

    if not dry_run:
        db.commit()
        _invalidate_caches()

    logger.info(
        f"Development purge complete: {result.stories_hard_deleted} deleted, "
        f"{result.stories_skipped} skipped (dry_run={dry_run})"
    )
    return result


def dry_run_purge(
    db: Session,
    days: int | None = None,
    development_mode: bool = False,
) -> dict:
    """
    Preview what would be purged without making changes.

    Returns detailed breakdown of what would be affected.
    """
    policy = get_active_policy(db)

    if development_mode:
        days = days or 3
        result = purge_development_mode(db, days=days, dry_run=True)
    else:
        result = purge_expired_content(db, dry_run=True)

    return {
        "dry_run": True,
        "mode": "development" if development_mode else "production",
        "policy": policy.name if policy else None,
        "would_soft_delete": result.stories_soft_deleted,
        "would_hard_delete": result.stories_hard_deleted,
        "would_skip": result.stories_skipped,
        "protected_by_brief": result.protected_by_brief,
        "protected_by_hold": result.protected_by_hold,
    }


def cleanup_orphaned_records(db: Session, dry_run: bool = False) -> dict:
    """
    Clean up orphaned records that reference deleted stories.

    This handles edge cases where a story was deleted but related
    records weren't properly cleaned up.
    """
    counts = {}

    # Find neutralized records with missing story_raw
    orphaned_neutralized = (
        db.query(StoryNeutralized)
        .outerjoin(StoryRaw, StoryNeutralized.story_raw_id == StoryRaw.id)
        .filter(StoryRaw.id.is_(None))
        .all()
    )

    counts["orphaned_neutralized"] = len(orphaned_neutralized)

    if not dry_run and orphaned_neutralized:
        neutralized_ids = [n.id for n in orphaned_neutralized]

        # Delete related spans
        db.query(TransparencySpan).filter(TransparencySpan.story_neutralized_id.in_(neutralized_ids)).delete(
            synchronize_session=False
        )

        db.query(ManipulationSpan).filter(ManipulationSpan.story_neutralized_id.in_(neutralized_ids)).delete(
            synchronize_session=False
        )

        db.query(DailyBriefItem).filter(DailyBriefItem.story_neutralized_id.in_(neutralized_ids)).delete(
            synchronize_session=False
        )

        # Delete orphaned neutralized
        db.query(StoryNeutralized).filter(StoryNeutralized.id.in_(neutralized_ids)).delete(synchronize_session=False)

        db.commit()

    logger.info(f"Orphan cleanup: {counts} (dry_run={dry_run})")
    return counts


def get_purge_preview(db: Session) -> dict:
    """
    Get a preview of current retention state and what would be purged.

    Useful for admin dashboard display.
    """
    policy = get_active_policy(db)
    if not policy:
        return {"error": "No active retention policy"}

    now = datetime.now(UTC)
    compliance_cutoff = now - timedelta(days=policy.compliance_days)
    grace_period_cutoff = now - timedelta(hours=24)

    protected_ids = _get_brief_protected_story_ids(db)

    # Count stories pending soft delete
    pending_soft_delete = (
        db.query(func.count(StoryRaw.id))
        .filter(
            and_(
                StoryRaw.ingested_at < compliance_cutoff,
                StoryRaw.deleted_at.is_(None),
                StoryRaw.legal_hold == False,
            )
        )
        .scalar()
    ) or 0

    # Count stories pending hard delete
    pending_hard_delete = (
        db.query(func.count(StoryRaw.id))
        .filter(
            and_(
                StoryRaw.deleted_at.isnot(None),
                StoryRaw.deleted_at < grace_period_cutoff,
                StoryRaw.legal_hold == False,
            )
        )
        .scalar()
    ) or 0

    return {
        "policy": policy.name,
        "compliance_days": policy.compliance_days,
        "protected_by_brief": len(protected_ids),
        "pending_soft_delete": pending_soft_delete,
        "pending_hard_delete": pending_hard_delete,
        "total_pending": pending_soft_delete + pending_hard_delete,
    }
