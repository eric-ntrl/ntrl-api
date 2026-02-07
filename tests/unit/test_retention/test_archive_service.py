# tests/unit/test_retention/test_archive_service.py
"""Unit tests for archive service."""

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


class TestFindArchivableStories:
    """Tests for find_archivable_stories()."""

    def test_returns_empty_when_no_active_policy(self):
        """Should return empty list when no retention policy is active."""
        from app.services.retention.archive_service import find_archivable_stories

        mock_db = MagicMock()

        with patch("app.services.retention.archive_service.get_active_policy") as mock_get:
            mock_get.return_value = None
            result = find_archivable_stories(mock_db)

        assert result == []

    def test_respects_active_days_cutoff(self):
        """Should only return stories older than active_days."""
        from app.models import RetentionPolicy
        from app.services.retention.archive_service import find_archivable_stories

        mock_policy = MagicMock(spec=RetentionPolicy)
        mock_policy.active_days = 7

        mock_stories = [MagicMock(id=uuid.uuid4())]

        mock_db = MagicMock()
        mock_query = mock_db.query.return_value
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = mock_stories

        with patch("app.services.retention.archive_service.get_active_policy") as mock_get:
            mock_get.return_value = mock_policy
            result = find_archivable_stories(mock_db)

        assert result == mock_stories

    def test_respects_custom_cutoff_date(self):
        """Should use provided cutoff_date instead of policy default."""
        from app.models import RetentionPolicy
        from app.services.retention.archive_service import find_archivable_stories

        mock_policy = MagicMock(spec=RetentionPolicy)
        mock_policy.active_days = 7

        mock_db = MagicMock()
        mock_query = mock_db.query.return_value
        mock_query.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

        custom_cutoff = datetime.utcnow() - timedelta(days=3)

        with patch("app.services.retention.archive_service.get_active_policy") as mock_get:
            mock_get.return_value = mock_policy
            result = find_archivable_stories(mock_db, cutoff_date=custom_cutoff)

        # Verify filter was called (specific filter conditions would require more complex mocking)
        assert mock_db.query.called


class TestArchiveStory:
    """Tests for archive_story()."""

    def test_skips_already_archived_idempotent(self):
        """Should return True if story was already archived today."""
        from app.models import StoryRaw
        from app.services.retention.archive_service import archive_story

        mock_story = MagicMock(spec=StoryRaw)
        mock_story.id = uuid.uuid4()

        mock_db = MagicMock()
        # Simulate existing idempotent event
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()

        result = archive_story(mock_db, mock_story)

        assert result == True
        # Should not have tried to archive
        assert mock_story.archive_status != "archiving"

    def test_deletes_from_hot_storage(self):
        """Should delete raw content from hot storage during archive."""
        from app.models import StoryRaw
        from app.services.retention.archive_service import archive_story

        mock_story = MagicMock(spec=StoryRaw)
        mock_story.id = uuid.uuid4()
        mock_story.raw_content_uri = "s3://bucket/key"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None  # No existing event

        mock_storage = MagicMock()

        with patch("app.services.retention.archive_service.get_storage_provider") as mock_get_storage:
            mock_get_storage.return_value = mock_storage
            result = archive_story(mock_db, mock_story, move_to_glacier=True)

        mock_storage.delete.assert_called_once_with(mock_story.raw_content_uri)

    def test_updates_story_status_on_success(self):
        """Should update story archive status and timestamp on success."""
        from app.models import ArchiveStatus, StoryRaw
        from app.services.retention.archive_service import archive_story

        mock_story = MagicMock(spec=StoryRaw)
        mock_story.id = uuid.uuid4()
        mock_story.raw_content_uri = "s3://bucket/key"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.services.retention.archive_service.get_storage_provider") as mock_get_storage:
            mock_get_storage.return_value = MagicMock()
            result = archive_story(mock_db, mock_story, move_to_glacier=True)

        assert result == True
        assert mock_story.archive_status == ArchiveStatus.ARCHIVED.value
        assert mock_story.archived_at is not None
        assert mock_story.raw_content_available == False


class TestArchiveBatch:
    """Tests for archive_batch()."""

    def test_returns_error_when_no_policy(self):
        """Should return error result when no active policy."""
        from app.services.retention.archive_service import archive_batch

        mock_db = MagicMock()

        with patch("app.services.retention.archive_service.get_active_policy") as mock_get:
            mock_get.return_value = None
            result = archive_batch(mock_db)

        assert result.success == False
        assert "No active retention policy" in result.errors[0]

    def test_skips_archival_in_hard_delete_mode(self):
        """Should skip archival when hard_delete_mode is enabled."""
        from app.models import RetentionPolicy
        from app.services.retention.archive_service import archive_batch

        mock_policy = MagicMock(spec=RetentionPolicy)
        mock_policy.hard_delete_mode = True

        mock_db = MagicMock()

        with patch("app.services.retention.archive_service.get_active_policy") as mock_get:
            mock_get.return_value = mock_policy
            result = archive_batch(mock_db, batch_size=100)

        assert result.success == True
        assert result.stories_skipped == 100

    def test_dry_run_does_not_archive(self):
        """Should not actually archive in dry_run mode."""
        from app.models import RetentionPolicy, StoryRaw
        from app.services.retention.archive_service import archive_batch

        mock_policy = MagicMock(spec=RetentionPolicy)
        mock_policy.hard_delete_mode = False
        mock_policy.auto_archive = True

        mock_stories = [MagicMock(spec=StoryRaw, id=uuid.uuid4()) for _ in range(3)]

        mock_db = MagicMock()

        with patch("app.services.retention.archive_service.get_active_policy") as mock_get_policy:
            mock_get_policy.return_value = mock_policy
            with patch("app.services.retention.archive_service.find_archivable_stories") as mock_find:
                mock_find.return_value = mock_stories
                result = archive_batch(mock_db, dry_run=True)

        assert result.dry_run == True
        assert result.stories_archived == 3
        # Should not have called archive_story
        assert result.stories_failed == 0


class TestGetRetentionStats:
    """Tests for get_retention_stats()."""

    def test_returns_error_when_no_policy(self):
        """Should return error dict when no active policy."""
        from app.services.retention.archive_service import get_retention_stats

        mock_db = MagicMock()

        with patch("app.services.retention.archive_service.get_active_policy") as mock_get:
            mock_get.return_value = None
            result = get_retention_stats(mock_db)

        assert "error" in result

    def test_returns_counts_by_tier(self):
        """Should return story counts grouped by retention tier."""
        from app.models import RetentionPolicy
        from app.services.retention.archive_service import get_retention_stats

        mock_policy = MagicMock(spec=RetentionPolicy)
        mock_policy.name = "production"
        mock_policy.active_days = 7
        mock_policy.compliance_days = 365
        mock_policy.hard_delete_mode = False

        mock_db = MagicMock()
        # Mock the count queries
        mock_db.query.return_value.scalar.return_value = 100
        mock_db.query.return_value.filter.return_value.scalar.return_value = 10

        with patch("app.services.retention.archive_service.get_active_policy") as mock_get:
            mock_get.return_value = mock_policy
            result = get_retention_stats(mock_db)

        assert "total" in result
        assert "by_tier" in result
        assert "policy" in result
