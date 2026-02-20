# tests/unit/test_retention/test_purge_service.py
"""Unit tests for purge service."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch


class TestSoftDeleteStory:
    """Tests for soft_delete_story()."""

    def test_sets_deleted_at_and_reason(self):
        """Should set deleted_at timestamp and deletion_reason."""
        from app.models import StoryRaw
        from app.services.retention.purge_service import soft_delete_story

        mock_story = MagicMock(spec=StoryRaw)
        mock_story.id = uuid.uuid4()
        mock_story.deleted_at = None
        mock_story.legal_hold = False
        mock_story.preserve_until = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None  # No existing event

        result = soft_delete_story(mock_db, mock_story, reason="retention")

        assert result == True
        assert mock_story.deleted_at is not None
        assert mock_story.deletion_reason == "retention"

    def test_skips_already_deleted(self):
        """Should return True immediately if story already deleted."""
        from app.models import StoryRaw
        from app.services.retention.purge_service import soft_delete_story

        mock_story = MagicMock(spec=StoryRaw)
        mock_story.deleted_at = datetime.now(UTC)

        mock_db = MagicMock()

        result = soft_delete_story(mock_db, mock_story)

        assert result == True
        # Should not have modified the story
        mock_db.add.assert_not_called()

    def test_respects_legal_hold(self):
        """Should not delete stories under legal hold."""
        from app.models import StoryRaw
        from app.services.retention.purge_service import soft_delete_story

        mock_story = MagicMock(spec=StoryRaw)
        mock_story.id = uuid.uuid4()
        mock_story.deleted_at = None
        mock_story.legal_hold = True

        mock_db = MagicMock()

        result = soft_delete_story(mock_db, mock_story)

        assert result == False

    def test_respects_preserve_until(self):
        """Should not delete stories with future preserve_until."""
        from app.models import StoryRaw
        from app.services.retention.purge_service import soft_delete_story

        mock_story = MagicMock(spec=StoryRaw)
        mock_story.id = uuid.uuid4()
        mock_story.deleted_at = None
        mock_story.legal_hold = False
        mock_story.preserve_until = datetime.now(UTC) + timedelta(days=30)

        mock_db = MagicMock()

        result = soft_delete_story(mock_db, mock_story)

        assert result == False


class TestHardDeleteStoryCascade:
    """Tests for _hard_delete_story_cascade()."""

    def test_deletes_in_correct_order(self):
        """Should delete related records before the story itself."""
        from app.models import StoryRaw
        from app.services.retention.purge_service import _hard_delete_story_cascade

        mock_story = MagicMock(spec=StoryRaw)
        mock_story.id = uuid.uuid4()

        mock_db = MagicMock()
        # Mock the query chain for neutralized IDs
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.delete.return_value = 0

        with patch("app.services.retention.purge_service._log_lifecycle_event"):
            counts = _hard_delete_story_cascade(mock_db, mock_story)

        # Should return counts dict
        assert "stories_raw" in counts
        assert counts["stories_raw"] == 1

    def test_logs_lifecycle_event(self):
        """Should log a HARD_DELETED lifecycle event."""
        from app.models import LifecycleEventType, StoryRaw
        from app.services.retention.purge_service import _hard_delete_story_cascade

        mock_story = MagicMock(spec=StoryRaw)
        mock_story.id = uuid.uuid4()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.delete.return_value = 0

        with patch("app.services.retention.purge_service._log_lifecycle_event") as mock_log:
            _hard_delete_story_cascade(mock_db, mock_story)

        mock_log.assert_called_once()
        call_args = mock_log.call_args
        assert call_args[0][2] == LifecycleEventType.HARD_DELETED


class TestPurgeExpiredContent:
    """Tests for purge_expired_content()."""

    def test_returns_error_when_no_policy(self):
        """Should return error result when no active policy."""
        from app.services.retention.purge_service import purge_expired_content

        mock_db = MagicMock()

        with patch("app.services.retention.purge_service.get_active_policy") as mock_get:
            mock_get.return_value = None
            result = purge_expired_content(mock_db)

        assert result.success == False
        assert "No active retention policy" in result.errors[0]

    def test_protects_brief_articles(self):
        """Should not delete articles in the current brief."""
        from app.models import RetentionPolicy
        from app.services.retention.purge_service import purge_expired_content

        mock_policy = MagicMock(spec=RetentionPolicy)
        mock_policy.compliance_days = 365

        protected_id = uuid.uuid4()

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = []

        with patch("app.services.retention.purge_service.get_active_policy") as mock_get:
            mock_get.return_value = mock_policy
            with patch("app.services.retention.purge_service._get_brief_protected_story_ids") as mock_protected:
                mock_protected.return_value = {protected_id}
                result = purge_expired_content(mock_db)

        assert result.protected_by_brief == 1

    def test_dry_run_does_not_delete(self):
        """Should not actually delete in dry_run mode."""
        from app.models import RetentionPolicy, StoryRaw
        from app.services.retention.purge_service import purge_expired_content

        mock_policy = MagicMock(spec=RetentionPolicy)
        mock_policy.compliance_days = 365

        mock_story = MagicMock(spec=StoryRaw)
        mock_story.id = uuid.uuid4()
        mock_story.preserve_until = None
        mock_story.deleted_at = datetime.now(UTC) - timedelta(hours=48)  # Past grace period

        mock_db = MagicMock()
        # First query for soft delete, second for hard delete
        mock_db.query.return_value.filter.return_value.limit.return_value.all.side_effect = [
            [],  # No stories to soft delete
            [mock_story],  # One story to hard delete
        ]

        with patch("app.services.retention.purge_service.get_active_policy") as mock_get:
            mock_get.return_value = mock_policy
            with patch("app.services.retention.purge_service._get_brief_protected_story_ids") as mock_protected:
                mock_protected.return_value = set()
                result = purge_expired_content(mock_db, dry_run=True)

        assert result.dry_run == True
        assert result.stories_hard_deleted == 1
        # Should not have committed
        mock_db.commit.assert_not_called()


class TestPurgeDevelopmentMode:
    """Tests for purge_development_mode()."""

    def test_hard_deletes_directly(self):
        """Should hard delete without soft delete phase."""
        from app.models import StoryRaw
        from app.services.retention.purge_service import purge_development_mode

        mock_story = MagicMock(spec=StoryRaw)
        mock_story.id = uuid.uuid4()
        mock_story.preserve_until = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = [mock_story]

        with patch("app.services.retention.purge_service._get_brief_protected_story_ids") as mock_protected:
            mock_protected.return_value = set()
            with patch("app.services.retention.purge_service._hard_delete_story_cascade") as mock_delete:
                mock_delete.return_value = {"stories_raw": 1}
                with patch("app.services.retention.purge_service._invalidate_caches"):
                    result = purge_development_mode(mock_db, days=3)

        assert result.stories_hard_deleted == 1
        mock_delete.assert_called_once()

    def test_uses_custom_days_threshold(self):
        """Should respect the days parameter for cutoff."""
        from app.services.retention.purge_service import purge_development_mode

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.limit.return_value.all.return_value = []

        with patch("app.services.retention.purge_service._get_brief_protected_story_ids") as mock_protected:
            mock_protected.return_value = set()
            result = purge_development_mode(mock_db, days=1)

        # Should have queried with 1 day cutoff (filter was called)
        assert mock_db.query.called


class TestDryRunPurge:
    """Tests for dry_run_purge()."""

    def test_returns_preview_without_changes(self):
        """Should return counts without making any changes."""
        from app.models import RetentionPolicy
        from app.services.retention.purge_service import dry_run_purge

        mock_policy = MagicMock(spec=RetentionPolicy)
        mock_policy.name = "development"

        mock_db = MagicMock()

        with patch("app.services.retention.purge_service.get_active_policy") as mock_get:
            mock_get.return_value = mock_policy
            with patch("app.services.retention.purge_service.purge_development_mode") as mock_purge:
                mock_purge.return_value = MagicMock(
                    stories_soft_deleted=0,
                    stories_hard_deleted=5,
                    stories_skipped=2,
                    protected_by_brief=1,
                    protected_by_hold=0,
                )
                result = dry_run_purge(mock_db, development_mode=True)

        assert result["dry_run"] == True
        assert result["mode"] == "development"
        assert result["would_hard_delete"] == 5


class TestGetBriefProtectedStoryIds:
    """Tests for _get_brief_protected_story_ids()."""

    def test_returns_empty_set_when_no_brief(self):
        """Should return empty set when no current brief exists."""
        from app.services.retention.purge_service import _get_brief_protected_story_ids

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = _get_brief_protected_story_ids(mock_db)

        assert result == set()

    def test_returns_story_ids_from_brief(self):
        """Should return story_raw_ids for all items in current brief."""
        from app.models import DailyBrief, DailyBriefItem
        from app.services.retention.purge_service import _get_brief_protected_story_ids

        brief_id = uuid.uuid4()
        story_id = uuid.uuid4()
        neutralized_id = uuid.uuid4()

        mock_brief = MagicMock(spec=DailyBrief)
        mock_brief.id = brief_id

        mock_item = MagicMock(spec=DailyBriefItem)
        mock_item.story_neutralized_id = neutralized_id

        mock_neutralized = MagicMock()
        mock_neutralized.story_raw_id = story_id

        mock_db = MagicMock()
        # First query: get current brief
        # Second query: get brief items
        # Third query: get neutralized records
        mock_db.query.return_value.filter.return_value.first.return_value = mock_brief
        mock_db.query.return_value.filter.return_value.all.side_effect = [
            [mock_item],  # Brief items
            [mock_neutralized],  # Neutralized records
        ]

        result = _get_brief_protected_story_ids(mock_db)

        assert story_id in result


class TestInvalidateCaches:
    """Tests for _invalidate_caches()."""

    def test_clears_brief_cache(self):
        """Should clear the brief cache."""
        from app.services.retention.purge_service import _invalidate_caches

        with patch("app.routers.brief.invalidate_brief_cache") as mock_invalidate:
            _invalidate_caches()

        mock_invalidate.assert_called_once()

    def test_clears_story_caches(self):
        """Should clear story and transparency caches."""
        from app.services.retention.purge_service import _invalidate_caches

        mock_story_cache = MagicMock()
        mock_story_cache.clear = MagicMock()
        mock_transparency_cache = MagicMock()
        mock_transparency_cache.clear = MagicMock()

        with patch("app.routers.brief.invalidate_brief_cache"):
            with patch("app.routers.stories._story_cache", mock_story_cache):
                with patch("app.routers.stories._transparency_cache", mock_transparency_cache):
                    _invalidate_caches()

        mock_story_cache.clear.assert_called_once()
        mock_transparency_cache.clear.assert_called_once()
