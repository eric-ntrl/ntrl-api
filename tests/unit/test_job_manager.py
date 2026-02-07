"""
Unit tests for PipelineJobManager.

Tests job lifecycle: creation, status tracking, cancellation, and cleanup.
"""

import uuid
from unittest.mock import MagicMock

import pytest

from app.models import PipelineJobStatus


class TestPipelineJobManager:
    """Tests for PipelineJobManager class."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock()
        db.query = MagicMock()
        return db

    @pytest.fixture
    def sample_config(self):
        """Sample pipeline configuration."""
        return {
            "max_items_per_source": 25,
            "classify_limit": 200,
            "neutralize_limit": 25,
            "max_workers": 5,
            "cutoff_hours": 24,
            "enable_evaluation": False,
            "enable_auto_optimize": False,
        }

    @pytest.fixture
    def mock_orchestrator_factory(self):
        """Mock orchestrator factory that returns a mock orchestrator."""

        async def execute():
            return {
                "status": "completed",
                "summary_id": str(uuid.uuid4()),
                "stage_progress": {"ingest": {"total": 10}},
                "errors": [],
            }

        orchestrator = MagicMock()
        orchestrator.execute = execute

        def factory(*args, **kwargs):
            return orchestrator

        return factory

    def test_get_job_status_valid_id(self, mock_db):
        """Test getting job status with valid UUID."""
        from app.services.pipeline_job_manager import PipelineJobManager

        job_id = str(uuid.uuid4())
        mock_job = MagicMock()
        mock_job.id = uuid.UUID(job_id)
        mock_job.status = PipelineJobStatus.RUNNING.value

        mock_db.query.return_value.filter.return_value.first.return_value = mock_job

        result = PipelineJobManager.get_job_status(mock_db, job_id)

        assert result == mock_job
        mock_db.query.assert_called_once()

    def test_get_job_status_invalid_id(self, mock_db):
        """Test getting job status with invalid UUID returns None."""
        from app.services.pipeline_job_manager import PipelineJobManager

        result = PipelineJobManager.get_job_status(mock_db, "not-a-uuid")

        assert result is None

    def test_get_job_status_not_found(self, mock_db):
        """Test getting job status when job doesn't exist."""
        from app.services.pipeline_job_manager import PipelineJobManager

        job_id = str(uuid.uuid4())
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = PipelineJobManager.get_job_status(mock_db, job_id)

        assert result is None

    def test_is_job_cancelled_true(self, mock_db):
        """Test checking if job is cancelled when it is."""
        from app.services.pipeline_job_manager import PipelineJobManager

        job_id = str(uuid.uuid4())
        mock_job = MagicMock()
        mock_job.cancel_requested = True

        mock_db.query.return_value.filter.return_value.first.return_value = mock_job

        result = PipelineJobManager.is_job_cancelled(mock_db, job_id)

        assert result is True

    def test_is_job_cancelled_false(self, mock_db):
        """Test checking if job is cancelled when it isn't."""
        from app.services.pipeline_job_manager import PipelineJobManager

        job_id = str(uuid.uuid4())
        mock_job = MagicMock()
        mock_job.cancel_requested = False

        mock_db.query.return_value.filter.return_value.first.return_value = mock_job

        result = PipelineJobManager.is_job_cancelled(mock_db, job_id)

        assert result is False

    def test_update_job_stage(self, mock_db):
        """Test updating job stage and progress."""
        from app.services.pipeline_job_manager import PipelineJobManager

        job_id = str(uuid.uuid4())
        mock_job = MagicMock()
        mock_job.current_stage = None
        mock_job.stage_progress = {}

        mock_db.query.return_value.filter.return_value.first.return_value = mock_job

        PipelineJobManager.update_job_stage(mock_db, job_id, "ingest", {"total": 10, "success": 8})

        assert mock_job.current_stage == "ingest"
        assert "ingest" in mock_job.stage_progress
        assert mock_job.stage_progress["ingest"]["total"] == 10
        mock_db.commit.assert_called_once()

    def test_list_recent_jobs(self, mock_db):
        """Test listing recent jobs."""
        from app.services.pipeline_job_manager import PipelineJobManager

        mock_jobs = [MagicMock(), MagicMock()]
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = mock_jobs

        result = PipelineJobManager.list_recent_jobs(mock_db, limit=10)

        assert result == mock_jobs

    def test_list_recent_jobs_with_status_filter(self, mock_db):
        """Test listing recent jobs with status filter."""
        from app.services.pipeline_job_manager import PipelineJobManager

        mock_jobs = [MagicMock()]
        mock_db.query.return_value.order_by.return_value.filter.return_value.limit.return_value.all.return_value = (
            mock_jobs
        )

        result = PipelineJobManager.list_recent_jobs(mock_db, limit=10, status="running")

        assert result == mock_jobs

    def test_get_running_job_count(self):
        """Test getting count of running jobs."""
        from app.services.pipeline_job_manager import PipelineJobManager

        # Clear any existing jobs
        PipelineJobManager._running_jobs.clear()

        # Add some mock tasks
        done_task = MagicMock()
        done_task.done.return_value = True

        running_task = MagicMock()
        running_task.done.return_value = False

        PipelineJobManager._running_jobs = {
            "job1": done_task,
            "job2": running_task,
            "job3": running_task,
        }

        result = PipelineJobManager.get_running_job_count()

        assert result == 2

        # Clean up
        PipelineJobManager._running_jobs.clear()


class TestPipelineJobManagerAsync:
    """Async tests for PipelineJobManager."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock(side_effect=lambda x: None)
        db.query = MagicMock()
        return db

    @pytest.mark.asyncio
    async def test_cancel_job_running(self, mock_db):
        """Test cancelling a running job."""
        from app.services.pipeline_job_manager import PipelineJobManager

        job_id = str(uuid.uuid4())
        mock_job = MagicMock()
        mock_job.status = PipelineJobStatus.RUNNING.value
        mock_job.cancel_requested = False

        mock_db.query.return_value.filter.return_value.first.return_value = mock_job

        # Add a mock task
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel = MagicMock()
        PipelineJobManager._running_jobs[job_id] = mock_task

        result = await PipelineJobManager.cancel_job(mock_db, job_id)

        assert result is True
        assert mock_job.cancel_requested is True
        mock_task.cancel.assert_called_once()
        mock_db.commit.assert_called_once()

        # Clean up
        PipelineJobManager._running_jobs.pop(job_id, None)

    @pytest.mark.asyncio
    async def test_cancel_job_already_completed(self, mock_db):
        """Test cancelling an already completed job."""
        from app.services.pipeline_job_manager import PipelineJobManager

        job_id = str(uuid.uuid4())
        mock_job = MagicMock()
        mock_job.status = PipelineJobStatus.COMPLETED.value

        mock_db.query.return_value.filter.return_value.first.return_value = mock_job

        result = await PipelineJobManager.cancel_job(mock_db, job_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_job_not_found(self, mock_db):
        """Test cancelling a non-existent job."""
        from app.services.pipeline_job_manager import PipelineJobManager

        job_id = str(uuid.uuid4())
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = await PipelineJobManager.cancel_job(mock_db, job_id)

        assert result is False

    @pytest.mark.asyncio
    async def test_cleanup_stale_jobs(self, mock_db):
        """Test cleaning up stale jobs."""
        from app.services.pipeline_job_manager import PipelineJobManager

        # Create mock stale jobs
        stale_job1 = MagicMock()
        stale_job1.status = PipelineJobStatus.RUNNING.value
        stale_job1.current_stage = "ingest"

        stale_job2 = MagicMock()
        stale_job2.status = PipelineJobStatus.PENDING.value
        stale_job2.current_stage = None

        mock_db.query.return_value.filter.return_value.all.return_value = [stale_job1, stale_job2]

        result = await PipelineJobManager.cleanup_stale_jobs(mock_db, stale_hours=2)

        assert result == 2
        assert stale_job1.status == PipelineJobStatus.FAILED.value
        assert stale_job2.status == PipelineJobStatus.FAILED.value
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_stale_jobs_none_found(self, mock_db):
        """Test cleanup when no stale jobs exist."""
        from app.services.pipeline_job_manager import PipelineJobManager

        mock_db.query.return_value.filter.return_value.all.return_value = []

        result = await PipelineJobManager.cleanup_stale_jobs(mock_db, stale_hours=2)

        assert result == 0
        mock_db.commit.assert_not_called()
