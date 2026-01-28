# app/services/rollback_service.py
"""
Rollback service for automated quality degradation detection and prompt rollback.

Monitors evaluation metrics across runs and automatically rolls back prompts
when quality degrades beyond configured thresholds.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from sqlalchemy.orm import Session

from app import models
from app.models import ChangeSource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rollback triggers
# ---------------------------------------------------------------------------

ROLLBACK_TRIGGERS = {
    "overall_score_drop": 0.5,            # 0.5+ point drop triggers rollback
    "classification_accuracy_drop": 0.10,  # 10% accuracy drop
    "neutralization_score_drop": 0.75,     # 0.75+ point drop
    "span_precision_drop": 0.15,           # 15% precision drop
    "span_recall_drop": 0.15,              # 15% recall drop
}


@dataclass
class DegradationCheck:
    """Result of checking for quality degradation."""
    degraded: bool
    trigger_name: Optional[str] = None
    current_value: Optional[float] = None
    previous_value: Optional[float] = None
    threshold: Optional[float] = None
    drop_amount: Optional[float] = None


@dataclass
class RollbackResult:
    """Result of a rollback operation."""
    success: bool
    prompt_name: str
    from_version: int
    to_version: int
    reason: str
    error: Optional[str] = None


class RollbackService:
    """
    Monitors for quality degradation and automatically rolls back prompts.

    Compares current evaluation metrics to previous evaluations and triggers
    rollback when thresholds are exceeded.
    """

    def __init__(self, triggers: Optional[Dict[str, float]] = None):
        """Initialize with custom triggers or use defaults."""
        self.triggers = triggers or ROLLBACK_TRIGGERS

    def check_and_rollback(
        self,
        db: Session,
        current_eval_id: str,
        auto_rollback: bool = True,
    ) -> Optional[RollbackResult]:
        """
        Check for degradation and optionally perform rollback.

        Args:
            db: Database session
            current_eval_id: ID of the current EvaluationRun
            auto_rollback: If True, automatically rollback on degradation

        Returns:
            RollbackResult if rollback was triggered, None otherwise
        """
        logger.info(f"[ROLLBACK] Checking evaluation {current_eval_id} for degradation")

        # Get current evaluation
        current_eval = db.query(models.EvaluationRun).filter(
            models.EvaluationRun.id == uuid.UUID(current_eval_id)
        ).first()

        if not current_eval:
            logger.warning(f"[ROLLBACK] Evaluation {current_eval_id} not found")
            return None

        # Get previous evaluation (for comparison)
        previous_eval = (
            db.query(models.EvaluationRun)
            .filter(models.EvaluationRun.id != uuid.UUID(current_eval_id))
            .filter(models.EvaluationRun.status == "completed")
            .order_by(models.EvaluationRun.finished_at.desc())
            .first()
        )

        if not previous_eval:
            logger.info("[ROLLBACK] No previous evaluation for comparison")
            return None

        # Check for degradation
        degradation = self._calculate_degradation(current_eval, previous_eval)

        if not degradation.degraded:
            logger.info("[ROLLBACK] No degradation detected")
            return None

        logger.warning(
            f"[ROLLBACK] Degradation detected: {degradation.trigger_name} "
            f"({degradation.previous_value:.2f} → {degradation.current_value:.2f}, "
            f"drop={degradation.drop_amount:.2f}, threshold={degradation.threshold:.2f})"
        )

        # Find prompts updated since previous evaluation
        changed_prompts = self._find_changed_prompts(db, previous_eval, current_eval)

        if not changed_prompts:
            logger.warning("[ROLLBACK] Degradation detected but no prompts changed")
            return None

        # Select the most recently changed prompt to rollback
        prompt_to_rollback = changed_prompts[0]  # Most recent first

        if not auto_rollback:
            logger.info(
                f"[ROLLBACK] Would rollback '{prompt_to_rollback.name}' "
                f"(auto_rollback=False)"
            )
            return RollbackResult(
                success=False,
                prompt_name=prompt_to_rollback.name,
                from_version=prompt_to_rollback.version,
                to_version=prompt_to_rollback.version - 1,
                reason=f"Degradation: {degradation.trigger_name}",
                error="auto_rollback=False",
            )

        # Execute rollback
        result = self.execute_rollback(
            db,
            prompt_name=prompt_to_rollback.name,
            model=prompt_to_rollback.model,
            reason=f"Auto-rollback: {degradation.trigger_name} exceeded threshold",
        )

        if result.success:
            # Update evaluation run with rollback info
            current_eval.rollback_triggered = True
            current_eval.rollback_details = {
                "prompt_name": result.prompt_name,
                "from_version": result.from_version,
                "to_version": result.to_version,
                "reason": result.reason,
                "trigger": degradation.trigger_name,
                "drop_amount": degradation.drop_amount,
            }
            db.commit()

        return result

    def _calculate_degradation(
        self,
        current: models.EvaluationRun,
        previous: models.EvaluationRun,
    ) -> DegradationCheck:
        """Check all degradation triggers."""
        # Overall quality score
        if current.overall_quality_score is not None and previous.overall_quality_score is not None:
            drop = previous.overall_quality_score - current.overall_quality_score
            if drop >= self.triggers["overall_score_drop"]:
                return DegradationCheck(
                    degraded=True,
                    trigger_name="overall_score_drop",
                    current_value=current.overall_quality_score,
                    previous_value=previous.overall_quality_score,
                    threshold=self.triggers["overall_score_drop"],
                    drop_amount=drop,
                )

        # Classification accuracy
        if current.classification_accuracy is not None and previous.classification_accuracy is not None:
            drop = previous.classification_accuracy - current.classification_accuracy
            if drop >= self.triggers["classification_accuracy_drop"]:
                return DegradationCheck(
                    degraded=True,
                    trigger_name="classification_accuracy_drop",
                    current_value=current.classification_accuracy,
                    previous_value=previous.classification_accuracy,
                    threshold=self.triggers["classification_accuracy_drop"],
                    drop_amount=drop,
                )

        # Neutralization score
        if current.avg_neutralization_score is not None and previous.avg_neutralization_score is not None:
            drop = previous.avg_neutralization_score - current.avg_neutralization_score
            if drop >= self.triggers["neutralization_score_drop"]:
                return DegradationCheck(
                    degraded=True,
                    trigger_name="neutralization_score_drop",
                    current_value=current.avg_neutralization_score,
                    previous_value=previous.avg_neutralization_score,
                    threshold=self.triggers["neutralization_score_drop"],
                    drop_amount=drop,
                )

        # Span precision
        if current.avg_span_precision is not None and previous.avg_span_precision is not None:
            drop = previous.avg_span_precision - current.avg_span_precision
            if drop >= self.triggers["span_precision_drop"]:
                return DegradationCheck(
                    degraded=True,
                    trigger_name="span_precision_drop",
                    current_value=current.avg_span_precision,
                    previous_value=previous.avg_span_precision,
                    threshold=self.triggers["span_precision_drop"],
                    drop_amount=drop,
                )

        # Span recall
        if current.avg_span_recall is not None and previous.avg_span_recall is not None:
            drop = previous.avg_span_recall - current.avg_span_recall
            if drop >= self.triggers["span_recall_drop"]:
                return DegradationCheck(
                    degraded=True,
                    trigger_name="span_recall_drop",
                    current_value=current.avg_span_recall,
                    previous_value=previous.avg_span_recall,
                    threshold=self.triggers["span_recall_drop"],
                    drop_amount=drop,
                )

        return DegradationCheck(degraded=False)

    def _find_changed_prompts(
        self,
        db: Session,
        previous_eval: models.EvaluationRun,
        current_eval: models.EvaluationRun,
    ) -> List[models.Prompt]:
        """Find prompts that were updated between evaluations."""
        # Find prompt versions created between the two evaluations
        changed_versions = (
            db.query(models.PromptVersion)
            .filter(models.PromptVersion.created_at > previous_eval.finished_at)
            .filter(models.PromptVersion.created_at <= current_eval.started_at)
            .filter(models.PromptVersion.change_source == ChangeSource.AUTO_OPTIMIZE.value)
            .order_by(models.PromptVersion.created_at.desc())
            .all()
        )

        # Get unique prompts
        prompt_ids = list(set(v.prompt_id for v in changed_versions))

        prompts = (
            db.query(models.Prompt)
            .filter(models.Prompt.id.in_(prompt_ids))
            .all()
        )

        return prompts

    def execute_rollback(
        self,
        db: Session,
        prompt_name: str,
        model: Optional[str] = None,
        target_version: Optional[int] = None,
        reason: str = "Manual rollback",
    ) -> RollbackResult:
        """
        Execute a rollback to a previous prompt version.

        Args:
            db: Database session
            prompt_name: Name of the prompt to rollback
            model: Model variant (None for generic)
            target_version: Version to rollback to (None = previous version)
            reason: Reason for rollback

        Returns:
            RollbackResult with success status
        """
        # Get current prompt
        query = db.query(models.Prompt).filter(models.Prompt.name == prompt_name)
        if model:
            query = query.filter(models.Prompt.model == model)
        else:
            query = query.filter(models.Prompt.model.is_(None))

        prompt = query.first()

        if not prompt:
            return RollbackResult(
                success=False,
                prompt_name=prompt_name,
                from_version=0,
                to_version=0,
                reason=reason,
                error=f"Prompt '{prompt_name}' not found",
            )

        current_version = prompt.version

        # Determine target version
        if target_version is None:
            target_version = current_version - 1

        if target_version < 1:
            return RollbackResult(
                success=False,
                prompt_name=prompt_name,
                from_version=current_version,
                to_version=target_version,
                reason=reason,
                error="Cannot rollback: no previous version",
            )

        # Get target version content
        target_version_entry = (
            db.query(models.PromptVersion)
            .filter(models.PromptVersion.prompt_id == prompt.id)
            .filter(models.PromptVersion.version == target_version)
            .first()
        )

        if not target_version_entry:
            return RollbackResult(
                success=False,
                prompt_name=prompt_name,
                from_version=current_version,
                to_version=target_version,
                reason=reason,
                error=f"Version {target_version} not found in history",
            )

        try:
            # Create new version entry for the rollback
            new_version = current_version + 1
            rollback_entry = models.PromptVersion(
                id=uuid.uuid4(),
                prompt_id=prompt.id,
                version=new_version,
                content=target_version_entry.content,
                change_reason=f"Rollback to v{target_version}: {reason}",
                change_source=ChangeSource.ROLLBACK.value,
                parent_version_id=prompt.current_version_id,
                avg_score_at_creation=None,  # Will be set after next evaluation
            )
            db.add(rollback_entry)

            # Update prompt to rolled back content
            prompt.content = target_version_entry.content
            prompt.version = new_version
            prompt.current_version_id = rollback_entry.id
            prompt.updated_at = datetime.now(timezone.utc)

            db.commit()

            logger.info(
                f"[ROLLBACK] Successfully rolled back '{prompt_name}' "
                f"from v{current_version} to v{target_version} content (new v{new_version})"
            )

            return RollbackResult(
                success=True,
                prompt_name=prompt_name,
                from_version=current_version,
                to_version=new_version,  # New version number with old content
                reason=reason,
            )

        except Exception as e:
            logger.error(f"[ROLLBACK] Failed to rollback '{prompt_name}': {e}")
            db.rollback()
            return RollbackResult(
                success=False,
                prompt_name=prompt_name,
                from_version=current_version,
                to_version=target_version,
                reason=reason,
                error=str(e),
            )

    def get_rollback_history(
        self,
        db: Session,
        prompt_name: str,
        model: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get rollback history for a prompt."""
        query = db.query(models.Prompt).filter(models.Prompt.name == prompt_name)
        if model:
            query = query.filter(models.Prompt.model == model)
        else:
            query = query.filter(models.Prompt.model.is_(None))

        prompt = query.first()
        if not prompt:
            return []

        rollbacks = (
            db.query(models.PromptVersion)
            .filter(models.PromptVersion.prompt_id == prompt.id)
            .filter(models.PromptVersion.change_source == ChangeSource.ROLLBACK.value)
            .order_by(models.PromptVersion.created_at.desc())
            .all()
        )

        return [
            {
                "version": r.version,
                "reason": r.change_reason,
                "created_at": r.created_at.isoformat(),
                "avg_score": r.avg_score_at_creation,
            }
            for r in rollbacks
        ]
