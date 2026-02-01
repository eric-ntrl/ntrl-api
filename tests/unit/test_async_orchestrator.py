"""
Unit tests for AsyncPipelineOrchestrator.

Tests stage execution, error handling, and cancellation.
"""

import asyncio
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from app.models import PipelineJobStatus


class TestAsyncPipelineOrchestrator:
    """Tests for AsyncPipelineOrchestrator class."""

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
    def orchestrator(self, mock_db, sample_config):
        """Create an orchestrator instance."""
        from app.services.async_pipeline_orchestrator import AsyncPipelineOrchestrator

        job_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())

        return AsyncPipelineOrchestrator(
            job_id=job_id,
            trace_id=trace_id,
            config=sample_config,
            db=mock_db,
        )

    def test_orchestrator_init(self, orchestrator, sample_config):
        """Test orchestrator initialization."""
        assert orchestrator.config == sample_config
        assert orchestrator.job_id is not None
        assert orchestrator.trace_id is not None
        assert orchestrator.stage_results == {}
        assert orchestrator.errors == []

    def test_determine_overall_status_all_completed(self, orchestrator):
        """Test status determination when all stages complete successfully."""
        from app.services.async_pipeline_orchestrator import StageResult

        orchestrator.stage_results = {
            "ingest": StageResult("ingest", "completed", 1000),
            "classify": StageResult("classify", "completed", 2000),
            "neutralize": StageResult("neutralize", "completed", 3000),
            "brief": StageResult("brief", "completed", 500),
        }

        result = orchestrator._determine_overall_status()
        assert result == PipelineJobStatus.COMPLETED.value

    def test_determine_overall_status_some_failed(self, orchestrator):
        """Test status determination when some stages fail."""
        from app.services.async_pipeline_orchestrator import StageResult

        orchestrator.stage_results = {
            "ingest": StageResult("ingest", "completed", 1000),
            "classify": StageResult("classify", "failed", 2000),
            "neutralize": StageResult("neutralize", "completed", 3000),
            "brief": StageResult("brief", "completed", 500),
        }

        result = orchestrator._determine_overall_status()
        assert result == PipelineJobStatus.PARTIAL.value

    def test_determine_overall_status_all_failed(self, orchestrator):
        """Test status determination when all stages fail."""
        from app.services.async_pipeline_orchestrator import StageResult

        orchestrator.stage_results = {
            "ingest": StageResult("ingest", "failed", 1000, errors=["Error 1"]),
            "classify": StageResult("classify", "failed", 0, errors=["Error 2"]),
        }

        result = orchestrator._determine_overall_status()
        assert result == PipelineJobStatus.FAILED.value

    def test_build_stage_progress(self, orchestrator):
        """Test building stage progress dict."""
        from app.services.async_pipeline_orchestrator import StageResult

        orchestrator.stage_results = {
            "ingest": StageResult("ingest", "completed", 1000, metrics={"total": 50}),
            "classify": StageResult("classify", "completed", 2000, metrics={"total": 48}),
        }

        progress = orchestrator._build_stage_progress()

        assert "ingest" in progress
        assert progress["ingest"]["status"] == "completed"
        assert progress["ingest"]["duration_ms"] == 1000
        assert progress["ingest"]["metrics"]["total"] == 50

        assert "classify" in progress
        assert progress["classify"]["status"] == "completed"
        assert progress["classify"]["metrics"]["total"] == 48

    def test_build_cancelled_result(self, orchestrator):
        """Test building cancelled result."""
        result = orchestrator._build_cancelled_result()

        assert result["status"] == PipelineJobStatus.CANCELLED.value
        assert result["summary_id"] is None
        assert len(result["errors"]) == 1
        assert result["errors"][0]["message"] == "Job was cancelled"


class TestStageResult:
    """Tests for StageResult dataclass."""

    def test_stage_result_defaults(self):
        """Test StageResult with default values."""
        from app.services.async_pipeline_orchestrator import StageResult

        result = StageResult(stage="test", status="completed", duration_ms=1000)

        assert result.stage == "test"
        assert result.status == "completed"
        assert result.duration_ms == 1000
        assert result.metrics == {}
        assert result.errors == []

    def test_stage_result_with_metrics(self):
        """Test StageResult with metrics."""
        from app.services.async_pipeline_orchestrator import StageResult

        result = StageResult(
            stage="ingest",
            status="completed",
            duration_ms=1500,
            metrics={"total": 100, "success": 95},
        )

        assert result.metrics["total"] == 100
        assert result.metrics["success"] == 95

    def test_stage_result_with_errors(self):
        """Test StageResult with errors."""
        from app.services.async_pipeline_orchestrator import StageResult

        result = StageResult(
            stage="classify",
            status="failed",
            duration_ms=500,
            errors=["LLM timeout", "Rate limit exceeded"],
        )

        assert len(result.errors) == 2
        assert "LLM timeout" in result.errors


class TestPipelineResult:
    """Tests for PipelineResult dataclass."""

    def test_pipeline_result_complete(self):
        """Test PipelineResult for successful run."""
        from app.services.async_pipeline_orchestrator import PipelineResult

        summary_id = str(uuid.uuid4())
        result = PipelineResult(
            status="completed",
            summary_id=summary_id,
            stage_progress={"ingest": {"status": "completed"}},
            errors=[],
            duration_ms=5000,
        )

        assert result.status == "completed"
        assert result.summary_id == summary_id
        assert result.duration_ms == 5000

    def test_pipeline_result_failed(self):
        """Test PipelineResult for failed run."""
        from app.services.async_pipeline_orchestrator import PipelineResult

        result = PipelineResult(
            status="failed",
            summary_id=None,
            stage_progress={"ingest": {"status": "failed"}},
            errors=[{"stage": "ingest", "message": "Connection failed"}],
            duration_ms=1000,
        )

        assert result.status == "failed"
        assert result.summary_id is None
        assert len(result.errors) == 1


class TestOrchestratorFactory:
    """Tests for create_orchestrator factory function."""

    def test_create_orchestrator(self):
        """Test creating an orchestrator via factory."""
        from app.services.async_pipeline_orchestrator import create_orchestrator

        mock_db = MagicMock()
        job_id = str(uuid.uuid4())
        trace_id = str(uuid.uuid4())
        config = {"max_items_per_source": 10}

        orchestrator = create_orchestrator(job_id, trace_id, config, mock_db)

        assert orchestrator.job_id == job_id
        assert orchestrator.trace_id == trace_id
        assert orchestrator.config == config
        assert orchestrator.db == mock_db
