"""
Unit tests for IngestionService.

Tests utility methods: paragraph deduplication, body upload to storage,
pipeline logging, and lazy storage initialization.
"""

import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.models import PipelineStage, PipelineStatus


class TestDeduplicateParagraphs:
    """Tests for _deduplicate_paragraphs method."""

    @pytest.fixture
    def service(self):
        """Create an IngestionService with mocked dependencies."""
        with (
            patch("app.services.ingestion.get_storage_provider"),
            patch("app.services.ingestion.Deduper"),
            patch("app.services.ingestion.SectionClassifier"),
            patch("app.services.ingestion.BodyExtractor"),
        ):
            from app.services.ingestion import IngestionService

            svc = IngestionService()
            return svc

    def test_deduplicate_paragraphs_basic(self, service):
        """Two identical paragraphs (>50 chars each) result in only one kept."""
        long_para = "This is a sufficiently long paragraph that exceeds the fifty character minimum threshold for deduplication."
        body = f"{long_para}\n\n{long_para}"

        result = service._deduplicate_paragraphs(body)

        assert result.count(long_para) == 1

    def test_deduplicate_paragraphs_short_kept(self, service):
        """Short paragraphs (<50 chars) are always kept even if duplicated."""
        short_para = "Photo: Reuters"
        body = f"{short_para}\n\n{short_para}"

        result = service._deduplicate_paragraphs(body)

        # Both instances kept because they are under 50 chars
        parts = result.split("\n\n")
        assert len(parts) == 2
        assert parts[0] == short_para
        assert parts[1] == short_para

    def test_deduplicate_paragraphs_empty(self, service):
        """Empty string input returns empty string."""
        result = service._deduplicate_paragraphs("")

        assert result == ""

    def test_deduplicate_paragraphs_none(self, service):
        """None input returns None."""
        result = service._deduplicate_paragraphs(None)

        assert result is None

    def test_deduplicate_paragraphs_case_insensitive(self, service):
        """Duplicate detection is case-insensitive for long paragraphs."""
        para_lower = "this is a sufficiently long paragraph that exceeds the fifty character minimum threshold for deduplication."
        para_upper = "THIS IS A SUFFICIENTLY LONG PARAGRAPH THAT EXCEEDS THE FIFTY CHARACTER MINIMUM THRESHOLD FOR DEDUPLICATION."
        body = f"{para_lower}\n\n{para_upper}"

        result = service._deduplicate_paragraphs(body)

        # Only first occurrence kept
        parts = result.split("\n\n")
        assert len(parts) == 1

    def test_deduplicate_paragraphs_whitespace_normalized(self, service):
        """Extra whitespace does not prevent deduplication."""
        para_normal = "This is a sufficiently long paragraph that exceeds the fifty character minimum threshold for deduplication."
        para_extra_spaces = "This  is  a  sufficiently  long  paragraph  that  exceeds  the  fifty  character  minimum  threshold  for  deduplication."
        body = f"{para_normal}\n\n{para_extra_spaces}"

        result = service._deduplicate_paragraphs(body)

        # Only first occurrence kept because normalized forms match
        parts = result.split("\n\n")
        assert len(parts) == 1


class TestUploadBodyToStorage:
    """Tests for _upload_body_to_storage method."""

    @pytest.fixture
    def ingestion_service(self):
        """Create an IngestionService with mocked storage."""
        with (
            patch("app.services.ingestion.get_storage_provider") as mock_storage_factory,
            patch("app.services.ingestion.Deduper"),
            patch("app.services.ingestion.SectionClassifier"),
            patch("app.services.ingestion.BodyExtractor"),
        ):
            mock_storage = MagicMock()
            mock_storage_factory.return_value = mock_storage

            from app.services.ingestion import IngestionService

            svc = IngestionService()
            svc._storage = mock_storage
            yield svc, mock_storage

    def test_upload_body_empty(self, ingestion_service):
        """Empty body returns None without calling storage."""
        service, mock_storage = ingestion_service

        result = service._upload_body_to_storage(
            story_id="test-id",
            body="",
            published_at=datetime(2026, 2, 20, tzinfo=UTC),
        )

        assert result is None
        mock_storage.upload.assert_not_called()

    def test_upload_body_success(self, ingestion_service):
        """Successful upload returns dict with storage metadata."""
        service, mock_storage = ingestion_service

        mock_metadata = MagicMock()
        mock_metadata.uri = "s3://bucket/key"
        mock_metadata.content_hash = "abc123"
        mock_metadata.content_type.value = "text/plain"
        mock_metadata.content_encoding.value = "identity"
        mock_metadata.original_size_bytes = 1024

        mock_storage.generate_key.return_value = "stories/2026/02/test-id/body"
        mock_storage.upload.return_value = mock_metadata

        result = service._upload_body_to_storage(
            story_id="test-id",
            body="Article body content here.",
            published_at=datetime(2026, 2, 20, tzinfo=UTC),
        )

        assert result is not None
        assert result["uri"] == "s3://bucket/key"
        assert result["hash"] == "abc123"
        assert result["type"] == "text/plain"
        assert result["encoding"] == "identity"
        assert result["size"] == 1024
        mock_storage.upload.assert_called_once()

    def test_upload_body_failure(self, ingestion_service):
        """When storage.upload raises, returns None without propagating."""
        service, mock_storage = ingestion_service

        mock_storage.generate_key.return_value = "stories/2026/02/test-id/body"
        mock_storage.upload.side_effect = Exception("S3 connection refused")

        result = service._upload_body_to_storage(
            story_id="test-id",
            body="Article body content here.",
            published_at=datetime(2026, 2, 20, tzinfo=UTC),
        )

        assert result is None


class TestLogPipeline:
    """Tests for _log_pipeline method."""

    @pytest.fixture
    def service(self):
        """Create an IngestionService with mocked dependencies."""
        with (
            patch("app.services.ingestion.get_storage_provider"),
            patch("app.services.ingestion.Deduper"),
            patch("app.services.ingestion.SectionClassifier"),
            patch("app.services.ingestion.BodyExtractor"),
        ):
            from app.services.ingestion import IngestionService

            return IngestionService()

    def test_log_pipeline_creates_entry(self, service):
        """_log_pipeline creates a PipelineLog with correct fields and adds to session."""
        mock_db = MagicMock()
        story_raw_id = uuid.uuid4()
        started_at = datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC)
        test_url = "https://example.com/article"

        log = service._log_pipeline(
            db=mock_db,
            stage=PipelineStage.INGEST,
            status=PipelineStatus.COMPLETED,
            story_raw_id=story_raw_id,
            started_at=started_at,
            trace_id="trace-123",
            entry_url=test_url,
            metadata={"source": "reuters"},
        )

        # Verify the log was added to the session
        mock_db.add.assert_called_once_with(log)

        # Verify log fields
        assert log.stage == PipelineStage.INGEST.value
        assert log.status == PipelineStatus.COMPLETED.value
        assert log.story_raw_id == story_raw_id
        assert log.trace_id == "trace-123"
        assert log.entry_url == test_url
        assert log.entry_url_hash == hashlib.sha256(test_url.encode()).hexdigest()
        assert log.log_metadata == {"source": "reuters"}
        assert log.duration_ms is not None
        assert log.duration_ms >= 0


class TestStorageLazyInit:
    """Tests for lazy storage initialization."""

    def test_storage_lazy_init(self):
        """Storage property lazy-loads on first access via get_storage_provider."""
        with (
            patch("app.services.ingestion.get_storage_provider") as mock_factory,
            patch("app.services.ingestion.Deduper"),
            patch("app.services.ingestion.SectionClassifier"),
            patch("app.services.ingestion.BodyExtractor"),
        ):
            mock_storage = MagicMock()
            mock_factory.return_value = mock_storage

            from app.services.ingestion import IngestionService

            svc = IngestionService()

            # _storage is None before first access
            assert svc._storage is None

            # First access triggers lazy load
            storage = svc.storage

            assert storage is mock_storage
            mock_factory.assert_called_once()

            # Second access does not re-create
            storage2 = svc.storage
            assert storage2 is mock_storage
            mock_factory.assert_called_once()  # Still only one call
