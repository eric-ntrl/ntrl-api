"""
End-to-end tests for async pipeline endpoints.

Tests the full async pipeline flow from API request to job completion.
"""

import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi.testclient import TestClient

# Set test environment before importing app
os.environ.setdefault("TESTING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ADMIN_API_KEY", "test-api-key")


class TestAsyncPipelineEndpoints:
    """E2E tests for async pipeline endpoints."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        from app.main import app
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self):
        """Create auth headers for admin endpoints."""
        return {"X-API-Key": "test-api-key"}

    @pytest.fixture
    def mock_job(self):
        """Create a mock pipeline job."""
        from app.models import PipelineJob, PipelineJobStatus

        job = MagicMock(spec=PipelineJob)
        job.id = uuid.uuid4()
        job.trace_id = str(uuid.uuid4())
        job.status = PipelineJobStatus.PENDING.value
        job.current_stage = None
        job.created_at = datetime.utcnow()
        job.started_at = None
        job.finished_at = None
        job.stage_progress = {}
        job.errors = []
        job.pipeline_run_summary_id = None
        job.cancel_requested = False
        return job

    def test_start_async_pipeline_returns_202(self, client, auth_headers):
        """Test that starting an async pipeline returns 202 Accepted."""
        with patch("app.services.pipeline_job_manager.PipelineJobManager.start_job") as mock_start:
            # Create mock job
            mock_job = MagicMock()
            mock_job.id = uuid.uuid4()
            mock_job.trace_id = str(uuid.uuid4())

            # Make start_job return a coroutine
            async def async_start(*args, **kwargs):
                return mock_job
            mock_start.side_effect = async_start

            response = client.post(
                "/v1/pipeline/scheduled-run-async",
                headers=auth_headers,
                json={
                    "max_items_per_source": 10,
                    "enable_evaluation": False,
                },
            )

            assert response.status_code == 202
            data = response.json()
            assert "job_id" in data
            assert "trace_id" in data
            assert data["status"] == "pending"
            assert "status_url" in data
            assert "stream_url" in data

    def test_start_async_pipeline_requires_auth(self, client):
        """Test that starting pipeline requires authentication."""
        response = client.post(
            "/v1/pipeline/scheduled-run-async",
            json={},
        )
        assert response.status_code == 401

    def test_get_job_status_success(self, client, auth_headers, mock_job):
        """Test getting job status."""
        with patch("app.services.pipeline_job_manager.PipelineJobManager.get_job_status") as mock_get:
            mock_get.return_value = mock_job

            response = client.get(
                f"/v1/pipeline/jobs/{mock_job.id}",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["id"] == str(mock_job.id)
            assert data["status"] == mock_job.status

    def test_get_job_status_not_found(self, client, auth_headers):
        """Test getting status for non-existent job."""
        with patch("app.services.pipeline_job_manager.PipelineJobManager.get_job_status") as mock_get:
            mock_get.return_value = None

            response = client.get(
                f"/v1/pipeline/jobs/{uuid.uuid4()}",
                headers=auth_headers,
            )

            assert response.status_code == 404

    def test_cancel_job_success(self, client, auth_headers, mock_job):
        """Test cancelling a running job."""
        with patch("app.services.pipeline_job_manager.PipelineJobManager.cancel_job") as mock_cancel:
            async def async_cancel(*args, **kwargs):
                return True
            mock_cancel.side_effect = async_cancel

            response = client.post(
                f"/v1/pipeline/jobs/{mock_job.id}/cancel",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["cancelled"] is True

    def test_cancel_job_already_completed(self, client, auth_headers, mock_job):
        """Test cancelling an already completed job."""
        with patch("app.services.pipeline_job_manager.PipelineJobManager.cancel_job") as mock_cancel:
            async def async_cancel(*args, **kwargs):
                return False
            mock_cancel.side_effect = async_cancel

            with patch("app.services.pipeline_job_manager.PipelineJobManager.get_job_status") as mock_get:
                mock_job.status = "completed"
                mock_get.return_value = mock_job

                response = client.post(
                    f"/v1/pipeline/jobs/{mock_job.id}/cancel",
                    headers=auth_headers,
                )

                assert response.status_code == 200
                data = response.json()
                assert data["cancelled"] is False
                assert "completed" in data["reason"]

    def test_list_jobs(self, client, auth_headers, mock_job):
        """Test listing pipeline jobs."""
        with patch("app.services.pipeline_job_manager.PipelineJobManager.list_recent_jobs") as mock_list:
            mock_list.return_value = [mock_job]

            with patch("app.services.pipeline_job_manager.PipelineJobManager.get_running_job_count") as mock_count:
                mock_count.return_value = 1

                response = client.get(
                    "/v1/pipeline/jobs",
                    headers=auth_headers,
                )

                assert response.status_code == 200
                data = response.json()
                assert len(data["jobs"]) == 1
                assert data["total"] == 1
                assert data["running_count"] == 1

    def test_list_jobs_with_status_filter(self, client, auth_headers, mock_job):
        """Test listing jobs with status filter."""
        with patch("app.services.pipeline_job_manager.PipelineJobManager.list_recent_jobs") as mock_list:
            mock_list.return_value = [mock_job]

            with patch("app.services.pipeline_job_manager.PipelineJobManager.get_running_job_count") as mock_count:
                mock_count.return_value = 1

                response = client.get(
                    "/v1/pipeline/jobs?status=pending",
                    headers=auth_headers,
                )

                assert response.status_code == 200
                mock_list.assert_called_once()
                call_kwargs = mock_list.call_args[1]
                assert call_kwargs.get("status") == "pending"


class TestAsyncPipelineResponse:
    """Tests for async pipeline response structure."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        from app.main import app
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self):
        """Create auth headers for admin endpoints."""
        return {"X-API-Key": "test-api-key"}

    def test_response_contains_status_url(self, client, auth_headers):
        """Test that response contains correct status URL."""
        with patch("app.services.pipeline_job_manager.PipelineJobManager.start_job") as mock_start:
            mock_job = MagicMock()
            mock_job.id = uuid.uuid4()
            mock_job.trace_id = str(uuid.uuid4())

            async def async_start(*args, **kwargs):
                return mock_job
            mock_start.side_effect = async_start

            response = client.post(
                "/v1/pipeline/scheduled-run-async",
                headers=auth_headers,
                json={},
            )

            data = response.json()
            assert f"/v1/pipeline/jobs/{mock_job.id}" in data["status_url"]

    def test_response_contains_stream_url(self, client, auth_headers):
        """Test that response contains correct stream URL."""
        with patch("app.services.pipeline_job_manager.PipelineJobManager.start_job") as mock_start:
            mock_job = MagicMock()
            mock_job.id = uuid.uuid4()
            mock_job.trace_id = str(uuid.uuid4())

            async def async_start(*args, **kwargs):
                return mock_job
            mock_start.side_effect = async_start

            response = client.post(
                "/v1/pipeline/scheduled-run-async",
                headers=auth_headers,
                json={},
            )

            data = response.json()
            assert f"/v1/pipeline/jobs/{mock_job.id}/stream" in data["stream_url"]


class TestJobStatusResponse:
    """Tests for job status response structure."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        from app.main import app
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self):
        """Create auth headers for admin endpoints."""
        return {"X-API-Key": "test-api-key"}

    def test_running_job_status(self, client, auth_headers):
        """Test status response for running job."""
        with patch("app.services.pipeline_job_manager.PipelineJobManager.get_job_status") as mock_get:
            mock_job = MagicMock()
            mock_job.id = uuid.uuid4()
            mock_job.trace_id = str(uuid.uuid4())
            mock_job.status = "running"
            mock_job.current_stage = "neutralize"
            mock_job.created_at = datetime.utcnow()
            mock_job.started_at = datetime.utcnow()
            mock_job.finished_at = None
            mock_job.stage_progress = {
                "ingest": {"status": "completed", "total": 50},
                "classify": {"status": "completed", "total": 48},
            }
            mock_job.errors = []
            mock_job.pipeline_run_summary_id = None

            mock_get.return_value = mock_job

            response = client.get(
                f"/v1/pipeline/jobs/{mock_job.id}",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "running"
            assert data["current_stage"] == "neutralize"
            assert "ingest" in data["stage_progress"]
            assert "classify" in data["stage_progress"]

    def test_completed_job_status(self, client, auth_headers):
        """Test status response for completed job."""
        with patch("app.services.pipeline_job_manager.PipelineJobManager.get_job_status") as mock_get:
            summary_id = uuid.uuid4()
            mock_job = MagicMock()
            mock_job.id = uuid.uuid4()
            mock_job.trace_id = str(uuid.uuid4())
            mock_job.status = "completed"
            mock_job.current_stage = None
            mock_job.created_at = datetime.utcnow()
            mock_job.started_at = datetime.utcnow()
            mock_job.finished_at = datetime.utcnow()
            mock_job.stage_progress = {
                "ingest": {"status": "completed"},
                "classify": {"status": "completed"},
                "neutralize": {"status": "completed"},
                "brief": {"status": "completed"},
            }
            mock_job.errors = []
            mock_job.pipeline_run_summary_id = summary_id

            mock_get.return_value = mock_job

            response = client.get(
                f"/v1/pipeline/jobs/{mock_job.id}",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"
            assert data["pipeline_run_summary_id"] == str(summary_id)
            assert data["finished_at"] is not None

    def test_failed_job_status(self, client, auth_headers):
        """Test status response for failed job."""
        with patch("app.services.pipeline_job_manager.PipelineJobManager.get_job_status") as mock_get:
            mock_job = MagicMock()
            mock_job.id = uuid.uuid4()
            mock_job.trace_id = str(uuid.uuid4())
            mock_job.status = "failed"
            mock_job.current_stage = "neutralize"
            mock_job.created_at = datetime.utcnow()
            mock_job.started_at = datetime.utcnow()
            mock_job.finished_at = datetime.utcnow()
            mock_job.stage_progress = {
                "ingest": {"status": "completed"},
                "classify": {"status": "completed"},
                "neutralize": {"status": "failed"},
            }
            mock_job.errors = [{"stage": "neutralize", "message": "LLM rate limit exceeded"}]
            mock_job.pipeline_run_summary_id = None

            mock_get.return_value = mock_job

            response = client.get(
                f"/v1/pipeline/jobs/{mock_job.id}",
                headers=auth_headers,
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "failed"
            assert len(data["errors"]) == 1
            assert "LLM rate limit" in data["errors"][0]["message"]
