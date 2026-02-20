"""
Async Pipeline Orchestrator for parallel pipeline execution.

Runs pipeline stages with maximum parallelism while respecting dependencies:
- Ingest: Parallel across sources
- Classify: Parallel across articles
- Neutralize: Parallel across articles
- Brief Assembly: Sequential (depends on neutralization)
- Evaluation: Parallel across samples
- Optimization: Sequential (depends on evaluation)
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.logging_config import (
    MetricsCollector,
    log_stage,
    trace_id_var,
)
from app.models import PipelineJobStatus, PipelineRunSummary
from app.services.pipeline_job_manager import PipelineJobManager
from app.services.resilience import CircuitBreaker

logger = logging.getLogger(__name__)


@dataclass
class StageResult:
    """Result from a single pipeline stage."""

    stage: str
    status: str  # 'completed', 'partial', 'failed', 'skipped'
    duration_ms: int
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class PipelineResult:
    """Final result from complete pipeline execution."""

    status: str
    summary_id: str | None
    stage_progress: dict[str, Any]
    errors: list[dict[str, Any]]
    duration_ms: int


class AsyncPipelineOrchestrator:
    """
    Orchestrates pipeline stages with parallel execution.

    This orchestrator runs the full pipeline asynchronously, tracking progress
    and handling failures gracefully. It uses asyncio for concurrency and
    ThreadPoolExecutor for CPU-bound operations.
    """

    # Concurrency limits for each stage
    INGEST_CONCURRENCY = 10  # Max parallel RSS fetches
    CLASSIFY_CONCURRENCY = 5  # Max parallel LLM classifications
    NEUTRALIZE_CONCURRENCY = 5  # Max parallel LLM neutralizations
    EVAL_CONCURRENCY = 3  # Max parallel LLM evaluations

    # Timeout for stages (in seconds)
    STAGE_TIMEOUT = 600  # 10 minutes per stage

    def __init__(
        self,
        job_id: str,
        trace_id: str,
        config: dict[str, Any],
        db: Session,
    ):
        """
        Initialize the orchestrator.

        Args:
            job_id: UUID of the PipelineJob
            trace_id: Trace ID for logging correlation
            config: ScheduledRunRequest config as dict
            db: Database session
        """
        self.job_id = job_id
        self.trace_id = trace_id
        self.config = config
        self.db = db

        # Metrics collection
        self.metrics = MetricsCollector(job_id)

        # Stage results
        self.stage_results: dict[str, StageResult] = {}

        # Circuit breakers for external services
        self.llm_breaker = CircuitBreaker(
            name="llm",
            failure_threshold=5,
            reset_timeout_seconds=60,
        )

        # Errors collected during execution
        self.errors: list[dict[str, Any]] = []

        # Set logging context
        trace_id_var.set(trace_id)

    async def execute(self) -> dict[str, Any]:
        """
        Execute the full pipeline with progress tracking.

        Returns:
            Dict containing status, summary_id, stage_progress, and errors
        """
        self._started_at = datetime.utcnow()
        logger.info(
            f"Pipeline orchestrator starting for job {self.job_id}",
            extra={
                "event": "pipeline_start",
                "job_id": self.job_id,
                "trace_id": self.trace_id,
                "config": self.config,
            },
        )

        try:
            # Stage 1: Ingest
            if await self._check_cancelled():
                return self._build_cancelled_result()
            await self._run_ingest()

            # Stage 2: Classify
            if await self._check_cancelled():
                return self._build_cancelled_result()
            await self._run_classify()

            # Stage 3: Neutralize
            if await self._check_cancelled():
                return self._build_cancelled_result()
            await self._run_neutralize()

            # Stage 4: Quality Check
            if await self._check_cancelled():
                return self._build_cancelled_result()
            await self._run_quality_check()

            # Stage 5: Brief Assembly
            if await self._check_cancelled():
                return self._build_cancelled_result()
            await self._run_brief_assembly()

            # Stage 5b: URL Validation (non-blocking, runs after brief)
            if await self._check_cancelled():
                return self._build_cancelled_result()
            await self._run_url_validation()

            # Create the pipeline run summary
            summary = self._create_summary()

            # Stage 6: Evaluation (optional)
            if self.config.get("enable_evaluation", False):
                if await self._check_cancelled():
                    return self._build_cancelled_result()
                await self._run_evaluation(str(summary.id))

                # Stage 6: Optimization (optional)
                if self.config.get("enable_auto_optimize", False):
                    if await self._check_cancelled():
                        return self._build_cancelled_result()
                    await self._run_optimization()

            # Determine overall status
            overall_status = self._determine_overall_status()

            # Update summary with final status
            summary.status = overall_status
            self.db.commit()

            finished_at = datetime.utcnow()
            duration_ms = int((finished_at - self._started_at).total_seconds() * 1000)

            logger.info(
                f"Pipeline orchestrator completed with status {overall_status}",
                extra={
                    "event": "pipeline_complete",
                    "job_id": self.job_id,
                    "trace_id": self.trace_id,
                    "status": overall_status,
                    "duration_ms": duration_ms,
                },
            )

            return PipelineResult(
                status=overall_status,
                summary_id=str(summary.id),
                stage_progress=self._build_stage_progress(),
                errors=self.errors,
                duration_ms=duration_ms,
            ).__dict__

        except Exception as e:
            logger.exception(f"Pipeline orchestrator failed: {e}")
            self.errors.append(
                {
                    "stage": "orchestrator",
                    "message": str(e),
                }
            )

            finished_at = datetime.utcnow()
            duration_ms = int((finished_at - self._started_at).total_seconds() * 1000)

            return PipelineResult(
                status=PipelineJobStatus.FAILED.value,
                summary_id=None,
                stage_progress=self._build_stage_progress(),
                errors=self.errors,
                duration_ms=duration_ms,
            ).__dict__

    async def _check_cancelled(self) -> bool:
        """Check if the job has been cancelled."""
        return PipelineJobManager.is_job_cancelled(self.db, self.job_id)

    def _build_cancelled_result(self) -> dict[str, Any]:
        """Build result for a cancelled job."""
        return PipelineResult(
            status=PipelineJobStatus.CANCELLED.value,
            summary_id=None,
            stage_progress=self._build_stage_progress(),
            errors=[{"stage": "orchestrator", "message": "Job was cancelled"}],
            duration_ms=0,
        ).__dict__

    async def _run_ingest(self) -> None:
        """Run the ingestion stage."""
        from app.services.ingestion import IngestionService

        stage_name = "ingest"
        PipelineJobManager.update_job_stage(self.db, self.job_id, stage_name)

        started_at = datetime.utcnow()

        try:
            with log_stage(stage_name, self.trace_id):
                service = IngestionService()

                # Run in thread pool since it's a sync operation
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: service.ingest_all(
                        self.db,
                        max_items_per_source=self.config.get("max_items_per_source", 25),
                        trace_id=self.trace_id,
                    ),
                )

                duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
                self.metrics.record_stage_timing(stage_name, duration_ms)

                self.stage_results[stage_name] = StageResult(
                    stage=stage_name,
                    status=result.get("status", "completed"),
                    duration_ms=duration_ms,
                    metrics={
                        "total": result.get("total_ingested", 0) + result.get("total_skipped_duplicate", 0),
                        "success": result.get("total_ingested", 0),
                        "body_downloaded": result.get("total_body_downloaded", 0),
                        "body_failed": result.get("total_body_failed", 0),
                        "skipped_duplicate": result.get("total_skipped_duplicate", 0),
                    },
                    errors=result.get("errors", []),
                )

                PipelineJobManager.update_job_stage(
                    self.db, self.job_id, stage_name, progress=self.stage_results[stage_name].metrics
                )

        except Exception as e:
            duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
            self.stage_results[stage_name] = StageResult(
                stage=stage_name,
                status="failed",
                duration_ms=duration_ms,
                errors=[str(e)],
            )
            self.errors.append({"stage": stage_name, "message": str(e)})
            logger.exception(f"Ingest stage failed: {e}")

    async def _run_classify(self) -> None:
        """Run the classification stage."""
        from app.services.llm_classifier import LLMClassifier

        stage_name = "classify"
        PipelineJobManager.update_job_stage(self.db, self.job_id, stage_name)

        started_at = datetime.utcnow()

        try:
            with log_stage(stage_name, self.trace_id):
                classifier = LLMClassifier()

                # Run in thread pool since it's a sync operation
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: classifier.classify_pending(
                        self.db,
                        limit=self.config.get("classify_limit", 200),
                    ),
                )

                duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
                self.metrics.record_stage_timing(stage_name, duration_ms)

                self.stage_results[stage_name] = StageResult(
                    stage=stage_name,
                    status="completed" if result.failed == 0 else "partial",
                    duration_ms=duration_ms,
                    metrics={
                        "total": result.total,
                        "success": result.success,
                        "llm": result.llm,
                        "keyword_fallback": result.keyword_fallback,
                        "failed": result.failed,
                    },
                    errors=result.errors or [],
                )

                PipelineJobManager.update_job_stage(
                    self.db, self.job_id, stage_name, progress=self.stage_results[stage_name].metrics
                )

        except Exception as e:
            duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
            self.stage_results[stage_name] = StageResult(
                stage=stage_name,
                status="failed",
                duration_ms=duration_ms,
                errors=[str(e)],
            )
            self.errors.append({"stage": stage_name, "message": str(e)})
            logger.exception(f"Classify stage failed: {e}")

    async def _run_neutralize(self) -> None:
        """Run the neutralization stage."""
        from app.services.neutralizer import NeutralizerService

        stage_name = "neutralize"
        PipelineJobManager.update_job_stage(self.db, self.job_id, stage_name)

        started_at = datetime.utcnow()

        try:
            with log_stage(stage_name, self.trace_id):
                service = NeutralizerService()

                # Run in thread pool since it uses ThreadPoolExecutor internally
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: service.neutralize_pending(
                        self.db,
                        limit=self.config.get("neutralize_limit", 25),
                        max_workers=self.config.get("max_workers", 5),
                    ),
                )

                duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
                self.metrics.record_stage_timing(stage_name, duration_ms)

                total = result.get("total_processed", 0) + result.get("total_skipped", 0)
                success = result.get("total_processed", 0) - result.get("total_failed", 0)

                self.stage_results[stage_name] = StageResult(
                    stage=stage_name,
                    status=result.get("status", "completed"),
                    duration_ms=duration_ms,
                    metrics={
                        "total": total,
                        "success": success,
                        "skipped_no_body": result.get("skipped_no_body", 0),
                        "failed": result.get("total_failed", 0),
                    },
                    errors=[],
                )

                PipelineJobManager.update_job_stage(
                    self.db, self.job_id, stage_name, progress=self.stage_results[stage_name].metrics
                )

        except Exception as e:
            duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
            self.stage_results[stage_name] = StageResult(
                stage=stage_name,
                status="failed",
                duration_ms=duration_ms,
                errors=[str(e)],
            )
            self.errors.append({"stage": stage_name, "message": str(e)})
            logger.exception(f"Neutralize stage failed: {e}")

    async def _run_quality_check(self) -> None:
        """Run the quality control gate stage."""
        from app.services.quality_gate import QualityGateService

        stage_name = "quality_check"
        PipelineJobManager.update_job_stage(self.db, self.job_id, stage_name)

        started_at = datetime.utcnow()

        try:
            with log_stage(stage_name, self.trace_id):
                service = QualityGateService()

                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, lambda: service.run_batch(self.db, trace_id=self.trace_id))

                duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
                self.metrics.record_stage_timing(stage_name, duration_ms)

                self.stage_results[stage_name] = StageResult(
                    stage=stage_name,
                    status="completed",
                    duration_ms=duration_ms,
                    metrics={
                        "total": result.get("total_checked", 0),
                        "passed": result.get("passed", 0),
                        "failed": result.get("failed", 0),
                    },
                    errors=[],
                )

                PipelineJobManager.update_job_stage(
                    self.db, self.job_id, stage_name, progress=self.stage_results[stage_name].metrics
                )

        except Exception as e:
            duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
            self.stage_results[stage_name] = StageResult(
                stage=stage_name,
                status="failed",
                duration_ms=duration_ms,
                errors=[str(e)],
            )
            self.errors.append({"stage": stage_name, "message": str(e)})
            logger.exception(f"Quality check stage failed: {e}")

    async def _run_brief_assembly(self) -> None:
        """Run the brief assembly stage."""
        from app.services.brief_assembly import BriefAssemblyService

        stage_name = "brief"
        PipelineJobManager.update_job_stage(self.db, self.job_id, stage_name)

        started_at = datetime.utcnow()

        try:
            with log_stage(stage_name, self.trace_id):
                service = BriefAssemblyService()

                # Run in thread pool
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: service.assemble_brief(
                        self.db,
                        cutoff_hours=self.config.get("cutoff_hours", 24),
                        force=True,
                    ),
                )

                duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
                self.metrics.record_stage_timing(stage_name, duration_ms)

                self.stage_results[stage_name] = StageResult(
                    stage=stage_name,
                    status=result.get("status", "completed"),
                    duration_ms=duration_ms,
                    metrics={
                        "story_count": result.get("total_stories", 0),
                        "section_count": len(result.get("sections", [])),
                        "is_empty": result.get("is_empty", False),
                    },
                    errors=[result.get("error")] if result.get("error") else [],
                )

                PipelineJobManager.update_job_stage(
                    self.db, self.job_id, stage_name, progress=self.stage_results[stage_name].metrics
                )

                # Invalidate brief cache
                from app.routers.brief import invalidate_brief_cache

                invalidate_brief_cache()

        except Exception as e:
            duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
            self.stage_results[stage_name] = StageResult(
                stage=stage_name,
                status="failed",
                duration_ms=duration_ms,
                errors=[str(e)],
            )
            self.errors.append({"stage": stage_name, "message": str(e)})
            logger.exception(f"Brief assembly stage failed: {e}")

    async def _run_url_validation(self) -> None:
        """Run URL validation batch on recently ingested articles."""
        from app.services.url_validator import validate_batch

        stage_name = "url_validation"
        PipelineJobManager.update_job_stage(self.db, self.job_id, stage_name)

        started_at = datetime.utcnow()

        try:
            with log_stage(stage_name, self.trace_id):
                loop = asyncio.get_running_loop()
                stats = await loop.run_in_executor(None, lambda: validate_batch(self.db, limit=200))

                duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
                self.metrics.record_stage_timing(stage_name, duration_ms)

                self.stage_results[stage_name] = StageResult(
                    stage=stage_name,
                    status="completed",
                    duration_ms=duration_ms,
                    metrics=stats,
                    errors=[],
                )

                PipelineJobManager.update_job_stage(
                    self.db, self.job_id, stage_name, progress=self.stage_results[stage_name].metrics
                )

        except Exception as e:
            duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
            self.stage_results[stage_name] = StageResult(
                stage=stage_name,
                status="failed",
                duration_ms=duration_ms,
                errors=[str(e)],
            )
            # URL validation failures are non-critical — don't add to self.errors
            # so they don't affect overall pipeline status
            logger.warning(f"URL validation stage failed (non-critical): {e}")

    async def _run_evaluation(self, summary_id: str) -> None:
        """Run the evaluation stage."""
        from app.config import get_settings
        from app.services.evaluation_service import EvaluationService

        stage_name = "evaluation"
        PipelineJobManager.update_job_stage(self.db, self.job_id, stage_name)

        started_at = datetime.utcnow()
        settings = get_settings()

        try:
            with log_stage(stage_name, self.trace_id):
                eval_model = self.config.get("teacher_model")
                if eval_model is None:  # No override, use config default
                    eval_model = settings.EVAL_MODEL

                service = EvaluationService(teacher_model=eval_model)

                # Run in thread pool
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: service.run_evaluation(
                        self.db,
                        pipeline_run_id=summary_id,
                        sample_size=self.config.get("eval_sample_size", 10),
                    ),
                )

                duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
                self.metrics.record_stage_timing(stage_name, duration_ms)

                self.stage_results[stage_name] = StageResult(
                    stage=stage_name,
                    status=result.status if hasattr(result, "status") else "completed",
                    duration_ms=duration_ms,
                    metrics={
                        "classification_accuracy": result.classification_accuracy,
                        "avg_neutralization_score": result.avg_neutralization_score,
                        "avg_span_precision": result.avg_span_precision,
                        "avg_span_recall": result.avg_span_recall,
                        "overall_quality_score": result.overall_quality_score,
                        "estimated_cost_usd": result.estimated_cost_usd,
                    },
                    errors=[],
                )

                # Store for optimization stage
                self._eval_result = result

                # Send email notification
                if hasattr(result, "evaluation_run_id") and result.evaluation_run_id:
                    try:
                        from app.services.email_service import EmailService

                        email_service = EmailService()
                        email_result = await loop.run_in_executor(
                            None, lambda: email_service.send_evaluation_results(self.db, str(result.evaluation_run_id))
                        )
                        if email_result.get("status") == "sent":
                            logger.info(f"Evaluation email sent: {email_result.get('message_id')}")
                        else:
                            logger.warning(f"Email not sent: {email_result}")
                    except Exception as email_error:
                        logger.error(f"Failed to send evaluation email: {email_error}")
                        # Don't fail the stage for email errors

                PipelineJobManager.update_job_stage(
                    self.db, self.job_id, stage_name, progress=self.stage_results[stage_name].metrics
                )

        except Exception as e:
            duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
            self.stage_results[stage_name] = StageResult(
                stage=stage_name,
                status="failed",
                duration_ms=duration_ms,
                errors=[str(e)],
            )
            self.errors.append({"stage": stage_name, "message": str(e)})
            logger.exception(f"Evaluation stage failed: {e}")

    async def _run_optimization(self) -> None:
        """Run the prompt optimization stage."""
        from app.config import get_settings
        from app.services.prompt_optimizer import PromptOptimizer
        from app.services.rollback_service import RollbackService

        stage_name = "optimization"
        PipelineJobManager.update_job_stage(self.db, self.job_id, stage_name)

        started_at = datetime.utcnow()
        settings = get_settings()

        try:
            with log_stage(stage_name, self.trace_id):
                if not hasattr(self, "_eval_result") or not self._eval_result:
                    self.stage_results[stage_name] = StageResult(
                        stage=stage_name,
                        status="skipped",
                        duration_ms=0,
                        metrics={"reason": "No evaluation result available"},
                        errors=[],
                    )
                    return

                # Check for rollback first
                rollback_service = RollbackService()
                rollback_result = rollback_service.check_and_rollback(
                    self.db,
                    current_eval_id=self._eval_result.evaluation_run_id,
                    auto_rollback=True,
                )

                rollback_triggered = rollback_result and rollback_result.success
                prompts_updated = 0

                if not rollback_triggered:
                    # Check minimum run count before optimizing
                    # Don't optimize until we have at least 3 eval runs with
                    # the current prompt versions to avoid knee-jerk reactions
                    min_runs = self.config.get("min_runs_before_optimize", 3)
                    runs_since_change = self._count_runs_since_last_prompt_change(self.db)

                    if runs_since_change < min_runs:
                        logger.info(
                            f"[OPTIMIZE] Skipping: only {runs_since_change}/{min_runs} runs since last prompt change"
                        )
                        prompts_updated = 0
                    else:
                        # Run optimization
                        optimizer = PromptOptimizer(teacher_model=settings.OPTIMIZER_MODEL)

                        loop = asyncio.get_running_loop()
                        opt_result = await loop.run_in_executor(
                            None,
                            lambda: optimizer.analyze_and_improve(
                                self.db,
                                evaluation_run_id=self._eval_result.evaluation_run_id,
                                auto_apply=True,
                            ),
                        )

                        prompts_updated = len([p for p in opt_result.prompts_updated if p.get("applied")])

                duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
                self.metrics.record_stage_timing(stage_name, duration_ms)

                self.stage_results[stage_name] = StageResult(
                    stage=stage_name,
                    status="completed",
                    duration_ms=duration_ms,
                    metrics={
                        "rollback_triggered": rollback_triggered,
                        "prompts_updated": prompts_updated,
                    },
                    errors=[],
                )

                PipelineJobManager.update_job_stage(
                    self.db, self.job_id, stage_name, progress=self.stage_results[stage_name].metrics
                )

        except Exception as e:
            duration_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
            self.stage_results[stage_name] = StageResult(
                stage=stage_name,
                status="failed",
                duration_ms=duration_ms,
                errors=[str(e)],
            )
            self.errors.append({"stage": stage_name, "message": str(e)})
            logger.exception(f"Optimization stage failed: {e}")

    def _count_runs_since_last_prompt_change(self, db: Session) -> int:
        """Count evaluation runs since the last prompt change.

        Returns the number of completed evaluation runs that occurred
        after the most recent auto-optimize prompt version was created.
        """
        from app.models import ChangeSource, EvaluationRun, PromptVersion

        # Find the most recent auto-optimize version
        latest_change = (
            db.query(PromptVersion)
            .filter(PromptVersion.change_source == ChangeSource.AUTO_OPTIMIZE.value)
            .order_by(PromptVersion.created_at.desc())
            .first()
        )

        if not latest_change:
            # No auto-optimize changes ever — safe to optimize
            return 999

        # Count completed eval runs since that change
        count = (
            db.query(EvaluationRun)
            .filter(EvaluationRun.status == "completed")
            .filter(EvaluationRun.finished_at > latest_change.created_at)
            .count()
        )

        return count

    def _create_summary(self) -> PipelineRunSummary:
        """Create a PipelineRunSummary from stage results."""
        from app.services.alerts import check_alerts

        ingest = self.stage_results.get("ingest", StageResult("ingest", "skipped", 0))
        classify = self.stage_results.get("classify", StageResult("classify", "skipped", 0))
        neutralize = self.stage_results.get("neutralize", StageResult("neutralize", "skipped", 0))
        qc = self.stage_results.get("quality_check", StageResult("quality_check", "skipped", 0))
        brief = self.stage_results.get("brief", StageResult("brief", "skipped", 0))

        # Calculate overall timing
        total_duration = sum(r.duration_ms for r in self.stage_results.values())

        summary = PipelineRunSummary(
            id=uuid.uuid4(),
            trace_id=self.trace_id,
            started_at=self._started_at,
            finished_at=datetime.utcnow(),
            duration_ms=total_duration,
            ingest_total=ingest.metrics.get("total", 0),
            ingest_success=ingest.metrics.get("success", 0),
            ingest_body_downloaded=ingest.metrics.get("body_downloaded", 0),
            ingest_body_failed=ingest.metrics.get("body_failed", 0),
            ingest_skipped_duplicate=ingest.metrics.get("skipped_duplicate", 0),
            classify_total=classify.metrics.get("total", 0),
            classify_success=classify.metrics.get("success", 0),
            classify_llm=classify.metrics.get("llm", 0),
            classify_keyword_fallback=classify.metrics.get("keyword_fallback", 0),
            classify_failed=classify.metrics.get("failed", 0),
            neutralize_total=neutralize.metrics.get("total", 0),
            neutralize_success=neutralize.metrics.get("success", 0),
            neutralize_skipped_no_body=neutralize.metrics.get("skipped_no_body", 0),
            neutralize_failed=neutralize.metrics.get("failed", 0),
            qc_total=qc.metrics.get("total", 0),
            qc_passed=qc.metrics.get("passed", 0),
            qc_failed=qc.metrics.get("failed", 0),
            brief_story_count=brief.metrics.get("story_count", 0),
            brief_section_count=brief.metrics.get("section_count", 0),
            status="pending",  # Will be updated
            alerts=[],
            trigger="scheduled",
        )

        # Check alerts
        alerts = check_alerts(summary)
        summary.alerts = alerts

        self.db.add(summary)
        self.db.commit()
        self.db.refresh(summary)

        return summary

    def _determine_overall_status(self) -> str:
        """Determine overall pipeline status from stage results."""
        statuses = [r.status for r in self.stage_results.values()]

        if all(s == "completed" for s in statuses):
            return PipelineJobStatus.COMPLETED.value
        elif any(s == "failed" for s in statuses):
            if any(s == "completed" for s in statuses):
                return PipelineJobStatus.PARTIAL.value
            return PipelineJobStatus.FAILED.value
        else:
            return PipelineJobStatus.PARTIAL.value

    def _build_stage_progress(self) -> dict[str, Any]:
        """Build stage progress dict for job record."""
        return {
            stage: {
                "status": result.status,
                "duration_ms": result.duration_ms,
                "metrics": result.metrics,
                "errors": result.errors,
            }
            for stage, result in self.stage_results.items()
        }


def create_orchestrator(
    job_id: str,
    trace_id: str,
    config: dict[str, Any],
    db: Session,
) -> AsyncPipelineOrchestrator:
    """Factory function for creating orchestrators."""
    return AsyncPipelineOrchestrator(job_id, trace_id, config, db)
