# app/services/brief_assembly.py
"""
Daily brief assembly service.

Deterministic rules:
1. Fixed category order: World, U.S., Local, Business, Technology, Science, Health, Environment, Sports, Culture
2. Within each category: order by published_at DESC
3. Tie-breaker: source priority (AP > Reuters > others), then story ID (deterministic)
4. Only include stories from last 24 hours (configurable)
5. Only include non-duplicate, neutralized, classified stories
6. Empty state if no qualifying stories

No personalization, trending, or popularity signals.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy.orm import Session

from app import models
from app.models import (
    FEED_CATEGORY_ORDER,
    FeedCategory,
    PipelineStage,
    PipelineStatus,
)


class StoryRow(NamedTuple):
    """A neutralized story with its raw source data, used throughout brief assembly."""

    neutralized: models.StoryNeutralized
    raw: models.StoryRaw
    source: models.Source


logger = logging.getLogger(__name__)

# Source priority for tie-breaking (lower = higher priority)
SOURCE_PRIORITY = {
    "ap": 1,
    "ap-news": 1,
    "reuters": 2,
    "bbc": 3,
    "npr": 4,
}

DEFAULT_PRIORITY = 99


class BriefAssemblyService:
    """Service for assembling deterministic daily briefs."""

    def _log_pipeline(
        self,
        db: Session,
        stage: PipelineStage,
        status: PipelineStatus,
        brief_id: uuid.UUID | None = None,
        started_at: datetime | None = None,
        error_message: str | None = None,
        metadata: dict | None = None,
    ) -> models.PipelineLog:
        """Create a pipeline log entry."""
        now = datetime.utcnow()
        duration_ms = None
        if started_at:
            duration_ms = int((now - started_at).total_seconds() * 1000)

        log = models.PipelineLog(
            id=uuid.uuid4(),
            stage=stage.value,
            status=status.value,
            brief_id=brief_id,
            started_at=started_at or now,
            finished_at=now,
            duration_ms=duration_ms,
            error_message=error_message,
            metadata=metadata,
        )
        db.add(log)
        return log

    def _get_source_priority(self, source_slug: str) -> int:
        """Get priority for a source (lower = higher priority)."""
        return SOURCE_PRIORITY.get(source_slug.lower(), DEFAULT_PRIORITY)

    def _sort_stories(
        self,
        stories: list[StoryRow],
    ) -> list[StoryRow]:
        """
        Sort stories deterministically.

        Order:
        1. published_at DESC (most recent first)
        2. source priority ASC (AP before Reuters)
        3. story ID ASC (deterministic tie-breaker)
        """
        return sorted(
            stories,
            key=lambda x: (
                -x[1].published_at.timestamp(),  # published_at DESC
                self._get_source_priority(x[2].slug),  # source priority ASC
                str(x[1].id),  # story ID ASC (deterministic)
            ),
        )

    def get_qualifying_stories(
        self,
        db: Session,
        cutoff_time: datetime,
    ) -> dict[FeedCategory, list[StoryRow]]:
        """
        Get all qualifying stories grouped by feed category.

        Qualifying means:
        - Not a duplicate
        - Has current neutralization (status=success)
        - Passed quality control gate (qc_status=passed)
        - Published after cutoff
        - Has been classified (feed_category is not null)
        """
        # Query for neutralized, non-duplicate stories
        results = (
            db.query(models.StoryNeutralized, models.StoryRaw, models.Source)
            .join(models.StoryRaw, models.StoryNeutralized.story_raw_id == models.StoryRaw.id)
            .join(models.Source, models.StoryRaw.source_id == models.Source.id)
            .filter(
                models.StoryNeutralized.is_current == True,
                models.StoryNeutralized.neutralization_status == "success",
                models.StoryNeutralized.qc_status == "passed",
                models.StoryRaw.is_duplicate == False,
                models.StoryRaw.published_at >= cutoff_time,
            )
            .all()
        )

        # Group by feed_category
        by_category: dict[FeedCategory, list[StoryRow]] = {cat: [] for cat in FeedCategory}

        for neutralized, story_raw, source in results:
            cat_value = story_raw.feed_category
            if cat_value is None:
                # Skip unclassified articles — they'll appear after next classify run
                continue

            try:
                category = FeedCategory(cat_value)
                by_category[category].append(StoryRow(neutralized, story_raw, source))
            except ValueError:
                continue

        # Sort each category
        for cat in by_category:
            by_category[cat] = self._sort_stories(by_category[cat])

        return by_category

    def assemble_brief(
        self,
        db: Session,
        cutoff_hours: int = 24,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Assemble the daily brief.

        Args:
            cutoff_hours: Hours to look back for stories
            force: Reassemble even if current brief exists

        Returns:
            Dict with brief info and stats
        """
        started_at = datetime.utcnow()
        brief_date = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_time = datetime.utcnow() - timedelta(hours=cutoff_hours)

        result = {
            "status": "completed",
            "started_at": started_at,
            "finished_at": None,
            "duration_ms": 0,
            "brief_id": None,
            "brief_date": brief_date,
            "cutoff_time": cutoff_time,
            "total_stories": 0,
            "is_empty": False,
            "empty_reason": None,
            "sections": [],
            "error": None,
        }

        try:
            # Check for existing current brief
            existing = (
                db.query(models.DailyBrief)
                .filter(
                    models.DailyBrief.is_current == True,
                )
                .order_by(models.DailyBrief.assembled_at.desc())
                .first()
            )

            if existing and not force:
                # Check if it's recent enough (within last hour)
                if (datetime.utcnow() - existing.assembled_at).total_seconds() < 3600:
                    result["status"] = "skipped"
                    result["brief_id"] = str(existing.id)
                    result["total_stories"] = existing.total_stories
                    result["is_empty"] = existing.is_empty
                    result["empty_reason"] = existing.empty_reason
                    result["finished_at"] = datetime.utcnow()
                    result["duration_ms"] = int((result["finished_at"] - started_at).total_seconds() * 1000)
                    return result

            # Get qualifying stories
            stories_by_section = self.get_qualifying_stories(db, cutoff_time)

            total_stories = sum(len(stories) for stories in stories_by_section.values())

            # Mark old briefs as not current
            if existing:
                existing.is_current = False

            # Determine version
            version = 1
            if existing:
                version = existing.version + 1

            # Check for empty state
            is_empty = total_stories == 0
            empty_reason = None
            if is_empty:
                empty_reason = "Insufficient qualifying stories in the last 24 hours."

            # Create brief
            brief = models.DailyBrief(
                id=uuid.uuid4(),
                brief_date=brief_date,
                version=version,
                total_stories=total_stories,
                cutoff_time=cutoff_time,
                is_current=True,
                is_empty=is_empty,
                empty_reason=empty_reason,
                assembled_at=datetime.utcnow(),
            )
            db.add(brief)
            db.flush()

            # Create brief items
            for category in FeedCategory:
                cat_stories = stories_by_section.get(category, [])
                cat_order = FEED_CATEGORY_ORDER[category]

                result["sections"].append(
                    {
                        "section": category.value,
                        "story_count": len(cat_stories),
                    }
                )

                for position, (neutralized, story_raw, source) in enumerate(cat_stories):
                    item = models.DailyBriefItem(
                        id=uuid.uuid4(),
                        brief_id=brief.id,
                        story_neutralized_id=neutralized.id,
                        section=category.value,
                        section_order=cat_order,
                        position=position,
                        feed_title=neutralized.feed_title,
                        feed_summary=neutralized.feed_summary,
                        source_name=source.name,
                        original_url=story_raw.original_url,
                        published_at=story_raw.published_at,
                        has_manipulative_content=neutralized.has_manipulative_content,
                    )
                    db.add(item)

            # Calculate duration
            finished_at = datetime.utcnow()
            duration_ms = int((finished_at - started_at).total_seconds() * 1000)
            brief.assembly_duration_ms = duration_ms

            db.commit()

            # Log success
            self._log_pipeline(
                db,
                stage=PipelineStage.BRIEF_ASSEMBLE,
                status=PipelineStatus.COMPLETED,
                brief_id=brief.id,
                started_at=started_at,
                metadata={
                    "total_stories": total_stories,
                    "is_empty": is_empty,
                    "version": version,
                },
            )

            result["brief_id"] = str(brief.id)
            result["total_stories"] = total_stories
            result["is_empty"] = is_empty
            result["empty_reason"] = empty_reason
            result["finished_at"] = finished_at
            result["duration_ms"] = duration_ms

            if is_empty:
                result["status"] = "empty"

        except Exception as e:
            logger.error(f"Brief assembly failed: {e}")
            result["status"] = "failed"
            result["error"] = str(e)

            self._log_pipeline(
                db,
                stage=PipelineStage.BRIEF_ASSEMBLE,
                status=PipelineStatus.FAILED,
                started_at=started_at,
                error_message=str(e),
            )

        return result

    def get_current_brief(
        self,
        db: Session,
    ) -> models.DailyBrief | None:
        """Get the current daily brief."""
        return (
            db.query(models.DailyBrief)
            .filter(models.DailyBrief.is_current == True)
            .order_by(models.DailyBrief.assembled_at.desc())
            .first()
        )
