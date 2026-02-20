"""
Pipeline Job Manager for async pipeline execution.

Manages the lifecycle of async pipeline jobs: creation, status tracking,
cancellation, and cleanup of stale jobs.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import PipelineJob, PipelineJobStatus

logger = logging.getLogger(__name__)


class PipelineJobManager:
    """
    Manages async pipeline job lifecycle.

    This is a singleton that tracks running jobs in memory and provides
    methods for creating, querying, and cancelling jobs.
    """

    # Class-level storage for running job tasks
    _running_jobs: dict[str, asyncio.Task] = {}

    @classmethod
    async def start_job(
        cls,
        db: Session,
        config: dict,
        orchestrator_factory,
    ) -> PipelineJob:
        """
        Start a new async pipeline job.

        Args:
            db: Database session
            config: ScheduledRunRequest config as dict
            orchestrator_factory: Factory function that creates the orchestrator

        Returns:
            PipelineJob: The created job record
        """
        # Concurrency guard: prevent overlapping pipeline runs
        running_count = cls.get_running_job_count()
        if running_count > 0:
            raise RuntimeError(
                f"Pipeline job already running ({running_count} active). Wait for it to complete or cancel it first."
            )

        trace_id = str(uuid.uuid4())
        job_id = uuid.uuid4()

        # Create job record
        job = PipelineJob(
            id=job_id,
            trace_id=trace_id,
            config=config,
            status=PipelineJobStatus.PENDING.value,
            created_at=datetime.now(UTC),
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        logger.info(
            f"Created pipeline job {job_id} with trace_id {trace_id}",
            extra={"event": "job_created", "job_id": str(job_id), "trace_id": trace_id},
        )

        # Create and start the background task
        # Note: We need to pass a new session to the background task
        # since SQLAlchemy sessions are not thread-safe
        async def run_job():
            await cls._execute_job(str(job_id), trace_id, config, orchestrator_factory)

        task = asyncio.create_task(run_job())
        cls._running_jobs[str(job_id)] = task

        # Clean up task reference when done
        task.add_done_callback(lambda t: cls._running_jobs.pop(str(job_id), None))

        return job

    @classmethod
    async def _execute_job(
        cls,
        job_id: str,
        trace_id: str,
        config: dict,
        orchestrator_factory,
    ) -> None:
        """
        Execute a pipeline job in the background.

        This runs in a separate task and updates the job record as it progresses.
        """
        from app.database import SessionLocal

        # Create a new session for the background task
        db = SessionLocal()

        try:
            # Mark job as running
            job = db.query(PipelineJob).filter(PipelineJob.id == job_id).first()
            if not job:
                logger.error(f"Job {job_id} not found when starting execution")
                return

            job.status = PipelineJobStatus.RUNNING.value
            job.started_at = datetime.now(UTC)
            db.commit()

            logger.info(
                f"Pipeline job {job_id} started", extra={"event": "job_started", "job_id": job_id, "trace_id": trace_id}
            )

            # Create and run the orchestrator
            orchestrator = orchestrator_factory(job_id, trace_id, config, db)
            result = await orchestrator.execute()

            # Update job with results
            job = db.query(PipelineJob).filter(PipelineJob.id == job_id).first()
            if job:
                job.status = result.get("status", PipelineJobStatus.COMPLETED.value)
                job.finished_at = datetime.now(UTC)
                job.stage_progress = result.get("stage_progress", {})
                job.pipeline_run_summary_id = result.get("summary_id")
                if result.get("errors"):
                    job.errors = result["errors"]
                db.commit()

            logger.info(
                f"Pipeline job {job_id} completed with status {job.status}",
                extra={
                    "event": "job_completed",
                    "job_id": job_id,
                    "trace_id": trace_id,
                    "status": job.status,
                },
            )

        except asyncio.CancelledError:
            # Job was cancelled
            job = db.query(PipelineJob).filter(PipelineJob.id == job_id).first()
            if job:
                job.status = PipelineJobStatus.CANCELLED.value
                job.finished_at = datetime.now(UTC)
                job.errors = [{"message": "Job was cancelled", "stage": job.current_stage}]
                db.commit()

            logger.warning(
                f"Pipeline job {job_id} was cancelled",
                extra={"event": "job_cancelled", "job_id": job_id, "trace_id": trace_id},
            )

        except Exception as e:
            # Job failed
            logger.exception(f"Pipeline job {job_id} failed: {e}")

            job = db.query(PipelineJob).filter(PipelineJob.id == job_id).first()
            if job:
                job.status = PipelineJobStatus.FAILED.value
                job.finished_at = datetime.now(UTC)
                job.errors = [{"message": str(e), "stage": job.current_stage}]
                db.commit()

        finally:
            db.close()

    @classmethod
    def get_job_status(cls, db: Session, job_id: str) -> PipelineJob | None:
        """
        Get job status by ID.

        Args:
            db: Database session
            job_id: Job UUID string

        Returns:
            PipelineJob or None if not found
        """
        try:
            job_uuid = uuid.UUID(job_id)
            return db.query(PipelineJob).filter(PipelineJob.id == job_uuid).first()
        except ValueError:
            return None

    @classmethod
    async def cancel_job(cls, db: Session, job_id: str) -> bool:
        """
        Request cancellation of a running job.

        Args:
            db: Database session
            job_id: Job UUID string

        Returns:
            True if cancellation was requested, False if job not found or not running
        """
        job = cls.get_job_status(db, job_id)
        if not job:
            return False

        if job.status not in [PipelineJobStatus.PENDING.value, PipelineJobStatus.RUNNING.value]:
            return False

        # Set cancel flag
        job.cancel_requested = True
        db.commit()

        # Cancel the task if it exists
        task = cls._running_jobs.get(job_id)
        if task and not task.done():
            task.cancel()

        logger.info(
            f"Cancellation requested for job {job_id}", extra={"event": "job_cancel_requested", "job_id": job_id}
        )

        return True

    @classmethod
    def list_recent_jobs(
        cls,
        db: Session,
        limit: int = 10,
        status: str | None = None,
    ) -> list[PipelineJob]:
        """
        List recent pipeline jobs.

        Args:
            db: Database session
            limit: Maximum number of jobs to return
            status: Optional status filter

        Returns:
            List of PipelineJob records
        """
        query = db.query(PipelineJob).order_by(PipelineJob.created_at.desc())

        if status:
            query = query.filter(PipelineJob.status == status)

        return query.limit(limit).all()

    @classmethod
    async def cleanup_stale_jobs(cls, db: Session, stale_hours: int = 2) -> int:
        """
        Clean up jobs that have been running or pending too long.

        This is called on startup and periodically to handle jobs that may have
        been orphaned due to a server restart.

        Args:
            db: Database session
            stale_hours: Hours after which a job is considered stale

        Returns:
            Number of jobs cleaned up
        """
        cutoff = datetime.now(UTC) - timedelta(hours=stale_hours)

        stale_jobs = (
            db.query(PipelineJob)
            .filter(
                PipelineJob.status.in_(
                    [
                        PipelineJobStatus.PENDING.value,
                        PipelineJobStatus.RUNNING.value,
                    ]
                ),
                PipelineJob.created_at < cutoff,
            )
            .all()
        )

        count = 0
        for job in stale_jobs:
            job.status = PipelineJobStatus.FAILED.value
            job.finished_at = datetime.now(UTC)
            job.errors = [{"message": "Job timed out or was orphaned", "stage": job.current_stage}]
            count += 1

        if count > 0:
            db.commit()
            logger.warning(
                f"Cleaned up {count} stale pipeline jobs", extra={"event": "stale_jobs_cleanup", "count": count}
            )

        return count

    @classmethod
    def is_job_cancelled(cls, db: Session, job_id: str) -> bool:
        """
        Check if a job has been requested to cancel.

        Used by the orchestrator to check if it should stop processing.

        Args:
            db: Database session
            job_id: Job UUID string

        Returns:
            True if cancellation was requested
        """
        job = cls.get_job_status(db, job_id)
        return job.cancel_requested if job else False

    @classmethod
    def update_job_stage(cls, db: Session, job_id: str, stage: str, progress: dict = None) -> None:
        """
        Update the current stage and progress of a job.

        Args:
            db: Database session
            job_id: Job UUID string
            stage: Current stage name
            progress: Optional stage progress details
        """
        job = cls.get_job_status(db, job_id)
        if job:
            job.current_stage = stage
            if progress:
                current_progress = job.stage_progress or {}
                current_progress[stage] = progress
                job.stage_progress = current_progress
            db.commit()

    @classmethod
    def get_running_job_count(cls) -> int:
        """Get the number of currently running jobs."""
        return len([t for t in cls._running_jobs.values() if not t.done()])


# Singleton instance for convenience
job_manager = PipelineJobManager()
