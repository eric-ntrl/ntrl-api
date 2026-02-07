# app/services/lifecycle.py
"""
Lifecycle management service for raw content retention.

Handles:
- Marking expired content as unavailable in Postgres
- Deleting expired content from S3
- Updating story records with expiration timestamp
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app import models
from app.storage.factory import get_storage_provider

logger = logging.getLogger(__name__)


class LifecycleService:
    """
    Manages raw content lifecycle and retention.

    Raw article bodies expire after a configurable retention period.
    Metadata and neutralized summaries persist indefinitely.
    """

    DEFAULT_RETENTION_DAYS = int(os.getenv("RAW_CONTENT_RETENTION_DAYS", "30"))

    def __init__(self):
        self._storage = None

    @property
    def storage(self):
        """Lazy-load storage provider."""
        if self._storage is None:
            self._storage = get_storage_provider()
        return self._storage

    def find_expired_stories(
        self,
        db: Session,
        retention_days: int = None,
        limit: int = 1000,
    ) -> list[models.StoryRaw]:
        """
        Find stories with raw content older than retention period.

        Only returns stories that:
        - Have raw content available
        - Were ingested more than retention_days ago
        """
        days = retention_days or self.DEFAULT_RETENTION_DAYS
        cutoff = datetime.utcnow() - timedelta(days=days)

        return (
            db.query(models.StoryRaw)
            .filter(
                and_(
                    models.StoryRaw.raw_content_available == True,
                    models.StoryRaw.raw_content_uri.isnot(None),
                    models.StoryRaw.ingested_at < cutoff,
                )
            )
            .limit(limit)
            .all()
        )

    def expire_story_content(
        self,
        db: Session,
        story: models.StoryRaw,
        delete_from_storage: bool = True,
    ) -> bool:
        """
        Mark a story's raw content as expired.

        Args:
            db: Database session
            story: Story to expire
            delete_from_storage: Also delete from S3 (default True)

        Returns:
            True if successful
        """
        try:
            # Delete from storage if requested
            if delete_from_storage and story.raw_content_uri:
                try:
                    self.storage.delete(story.raw_content_uri)
                    logger.debug(f"Deleted from storage: {story.raw_content_uri}")
                except Exception as e:
                    logger.warning(f"Failed to delete {story.raw_content_uri}: {e}")

            # Update Postgres record
            story.raw_content_available = False
            story.raw_content_expired_at = datetime.utcnow()
            db.add(story)

            return True

        except Exception as e:
            logger.error(f"Failed to expire story {story.id}: {e}")
            return False

    def run_cleanup(
        self,
        db: Session,
        retention_days: int = None,
        batch_size: int = 100,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """
        Run cleanup job to expire old raw content.

        Args:
            db: Database session
            retention_days: Override default retention
            batch_size: Process this many stories at a time
            dry_run: If True, don't actually delete anything

        Returns:
            Dict with cleanup results
        """
        started_at = datetime.utcnow()
        result = {
            "status": "completed",
            "started_at": started_at,
            "finished_at": None,
            "retention_days": retention_days or self.DEFAULT_RETENTION_DAYS,
            "dry_run": dry_run,
            "stories_processed": 0,
            "stories_expired": 0,
            "storage_deleted": 0,
            "errors": [],
        }

        try:
            # Find expired stories
            expired_stories = self.find_expired_stories(
                db,
                retention_days=retention_days,
                limit=batch_size,
            )

            result["stories_processed"] = len(expired_stories)

            for story in expired_stories:
                try:
                    if dry_run:
                        result["stories_expired"] += 1
                        if story.raw_content_uri:
                            result["storage_deleted"] += 1
                    else:
                        if self.expire_story_content(db, story, delete_from_storage=True):
                            result["stories_expired"] += 1
                            if story.raw_content_uri:
                                result["storage_deleted"] += 1

                except Exception as e:
                    logger.error(f"Error expiring story {story.id}: {e}")
                    result["errors"].append(str(e))

            if not dry_run:
                db.commit()

        except Exception as e:
            logger.error(f"Cleanup job failed: {e}")
            result["status"] = "failed"
            result["errors"].append(str(e))

        result["finished_at"] = datetime.utcnow()
        return result
