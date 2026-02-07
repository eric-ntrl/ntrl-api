# app/services/rollback_service.py
"""
Rollback service for automated quality degradation detection and prompt rollback.

Monitors evaluation metrics across runs and automatically rolls back prompts
when quality degrades beyond configured thresholds.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app import models
from app.models import ChangeSource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rollback triggers
# ---------------------------------------------------------------------------

ROLLBACK_TRIGGERS = {
    "overall_score_drop": 0.5,  # 0.5+ point drop triggers rollback
    "classification_accuracy_drop": 0.10,  # 10% accuracy drop
    "neutralization_score_drop": 0.75,  # 0.75+ point drop
    "span_precision_drop": 0.15,  # 15% precision drop
    "span_recall_drop": 0.15,  # 15% recall drop
}

# Map degradation triggers to the prompt most likely responsible
TRIGGER_TO_PROMPT = {
    "overall_score_drop": None,  # Roll back all changed prompts
    "classification_accuracy_drop": "classification_system_prompt",
    "neutralization_score_drop": "article_system_prompt",
    "span_precision_drop": "span_detection_prompt",
    "span_recall_drop": "span_detection_prompt",
}

# Number of recent evaluation runs to consider for best-known-good baseline
BASELINE_LOOKBACK_RUNS = 5


@dataclass
class DegradationCheck:
    """Result of checking for quality degradation."""

    degraded: bool
    trigger_name: str | None = None
    current_value: float | None = None
    previous_value: float | None = None
    threshold: float | None = None
    drop_amount: float | None = None
    all_triggers: list[str] | None = None  # All triggers that fired


@dataclass
class RollbackResult:
    """Result of a rollback operation."""

    success: bool
    prompt_name: str
    from_version: int
    to_version: int
    reason: str
    error: str | None = None


class RollbackService:
    """
    Monitors for quality degradation and automatically rolls back prompts.

    Compares current evaluation metrics to previous evaluations and triggers
    rollback when thresholds are exceeded.
    """

    def __init__(self, triggers: dict[str, float] | None = None):
        """Initialize with custom triggers or use defaults."""
        self.triggers = triggers or ROLLBACK_TRIGGERS

    def check_and_rollback(
        self,
        db: Session,
        current_eval_id: str,
        auto_rollback: bool = True,
    ) -> RollbackResult | None:
        """
        Check for degradation and optionally perform rollback.

        Rolls back ALL changed prompts when degradation is detected (not just one).
        Uses metric-to-prompt correlation to prioritize rollbacks, and compares
        against the best-known-good baseline (not just previous run).

        Args:
            db: Database session
            current_eval_id: ID of the current EvaluationRun
            auto_rollback: If True, automatically rollback on degradation

        Returns:
            RollbackResult for the first rollback if triggered, None otherwise
        """
        logger.info(f"[ROLLBACK] Checking evaluation {current_eval_id} for degradation")

        # Get current evaluation
        current_eval = (
            db.query(models.EvaluationRun).filter(models.EvaluationRun.id == uuid.UUID(current_eval_id)).first()
        )

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

        # Check for degradation vs previous run
        degradation = self._calculate_degradation(current_eval, previous_eval)

        # Also check against best-known-good baseline
        if not degradation.degraded:
            degradation = self._check_baseline_degradation(db, current_eval)

        if not degradation.degraded:
            logger.info("[ROLLBACK] No degradation detected")
            return None

        logger.warning(
            f"[ROLLBACK] Degradation detected: {degradation.trigger_name} "
            f"({degradation.previous_value:.2f} → {degradation.current_value:.2f}, "
            f"drop={degradation.drop_amount:.2f}, threshold={degradation.threshold:.2f})"
        )
        if degradation.all_triggers:
            logger.warning(f"[ROLLBACK] All triggered: {degradation.all_triggers}")

        # Find prompts updated since previous evaluation
        changed_prompts = self._find_changed_prompts(db, previous_eval, current_eval)

        if not changed_prompts:
            logger.warning("[ROLLBACK] Degradation detected but no prompts changed")
            return None

        # Determine which prompts to roll back using metric-to-prompt mapping
        prompts_to_rollback = self._select_prompts_to_rollback(changed_prompts, degradation)

        if not auto_rollback:
            prompt_names = [p.name for p in prompts_to_rollback]
            logger.info(f"[ROLLBACK] Would rollback {prompt_names} (auto_rollback=False)")
            first = prompts_to_rollback[0]
            return RollbackResult(
                success=False,
                prompt_name=first.name,
                from_version=first.version,
                to_version=first.version - 1,
                reason=f"Degradation: {degradation.trigger_name}",
                error="auto_rollback=False",
            )

        # Execute rollback for ALL targeted prompts
        results = []
        for prompt in prompts_to_rollback:
            result = self.execute_rollback(
                db,
                prompt_name=prompt.name,
                model=prompt.model,
                reason=f"Auto-rollback: {degradation.trigger_name} exceeded threshold",
            )
            results.append(result)
            if result.success:
                logger.info(f"[ROLLBACK] Rolled back '{prompt.name}' v{result.from_version} → v{result.to_version}")
            else:
                logger.error(f"[ROLLBACK] Failed to rollback '{prompt.name}': {result.error}")

        # Update evaluation run with rollback info
        successful_rollbacks = [r for r in results if r.success]
        if successful_rollbacks:
            current_eval.rollback_triggered = True
            current_eval.rollback_details = {
                "prompts_rolled_back": [
                    {
                        "prompt_name": r.prompt_name,
                        "from_version": r.from_version,
                        "to_version": r.to_version,
                    }
                    for r in successful_rollbacks
                ],
                "reason": successful_rollbacks[0].reason,
                "trigger": degradation.trigger_name,
                "all_triggers": degradation.all_triggers,
                "drop_amount": degradation.drop_amount,
                # Keep backwards-compatible fields
                "prompt_name": successful_rollbacks[0].prompt_name,
                "from_version": successful_rollbacks[0].from_version,
                "to_version": successful_rollbacks[0].to_version,
            }
            db.commit()

        # Return the first successful result (or last failed one)
        return successful_rollbacks[0] if successful_rollbacks else results[-1]

    def _calculate_degradation(
        self,
        current: models.EvaluationRun,
        previous: models.EvaluationRun,
    ) -> DegradationCheck:
        """Check all degradation triggers.

        Returns the worst trigger as the primary, but also collects all
        triggered metrics in `all_triggers` for comprehensive rollback.
        """
        triggered = []

        # Check each metric pair
        checks = [
            ("overall_score_drop", current.overall_quality_score, previous.overall_quality_score),
            ("classification_accuracy_drop", current.classification_accuracy, previous.classification_accuracy),
            ("neutralization_score_drop", current.avg_neutralization_score, previous.avg_neutralization_score),
            ("span_precision_drop", current.avg_span_precision, previous.avg_span_precision),
            ("span_recall_drop", current.avg_span_recall, previous.avg_span_recall),
        ]

        for trigger_name, current_val, previous_val in checks:
            if current_val is not None and previous_val is not None:
                drop = previous_val - current_val
                if drop >= self.triggers[trigger_name]:
                    triggered.append((trigger_name, current_val, previous_val, drop))

        if not triggered:
            return DegradationCheck(degraded=False)

        # Use the worst trigger (largest relative drop) as the primary
        worst = max(triggered, key=lambda t: t[3] / max(self.triggers[t[0]], 0.001))
        trigger_name, current_val, previous_val, drop = worst

        return DegradationCheck(
            degraded=True,
            trigger_name=trigger_name,
            current_value=current_val,
            previous_value=previous_val,
            threshold=self.triggers[trigger_name],
            drop_amount=drop,
            all_triggers=[t[0] for t in triggered],
        )

    def _find_changed_prompts(
        self,
        db: Session,
        previous_eval: models.EvaluationRun,
        current_eval: models.EvaluationRun,
    ) -> list[models.Prompt]:
        """Find prompts that were updated between evaluations.

        Returns prompts in deterministic order (most recently changed first).
        """
        # Find prompt versions created between the two evaluations
        changed_versions = (
            db.query(models.PromptVersion)
            .filter(models.PromptVersion.created_at > previous_eval.finished_at)
            .filter(models.PromptVersion.created_at <= current_eval.started_at)
            .filter(models.PromptVersion.change_source == ChangeSource.AUTO_OPTIMIZE.value)
            .order_by(models.PromptVersion.created_at.desc())
            .all()
        )

        # Get unique prompt IDs preserving order (most recently changed first)
        seen = set()
        prompt_ids = []
        for v in changed_versions:
            if v.prompt_id not in seen:
                seen.add(v.prompt_id)
                prompt_ids.append(v.prompt_id)

        if not prompt_ids:
            return []

        # Fetch prompts and preserve the ordering from prompt_ids
        prompts = db.query(models.Prompt).filter(models.Prompt.id.in_(prompt_ids)).all()

        # Re-order to match prompt_ids ordering
        prompt_by_id = {p.id: p for p in prompts}
        return [prompt_by_id[pid] for pid in prompt_ids if pid in prompt_by_id]

    def _select_prompts_to_rollback(
        self,
        changed_prompts: list[models.Prompt],
        degradation: DegradationCheck,
    ) -> list[models.Prompt]:
        """Select which prompts to roll back based on metric-to-prompt mapping.

        If a specific metric triggered (e.g., neutralization_score_drop),
        prioritize the corresponding prompt. If overall_score_drop triggered
        or multiple triggers fired, roll back ALL changed prompts.
        """
        triggers = degradation.all_triggers or [degradation.trigger_name]

        # If overall score dropped or multiple metrics triggered,
        # roll back everything
        if "overall_score_drop" in triggers or len(triggers) > 1:
            logger.info(f"[ROLLBACK] Rolling back ALL {len(changed_prompts)} changed prompts (triggers: {triggers})")
            return changed_prompts

        # Single specific metric trigger - find the corresponding prompt
        trigger = triggers[0]
        target_prompt_name = TRIGGER_TO_PROMPT.get(trigger)

        if target_prompt_name:
            # Try to find the specific prompt in the changed list
            target = [p for p in changed_prompts if p.name == target_prompt_name]
            if target:
                logger.info(f"[ROLLBACK] Targeting '{target_prompt_name}' for {trigger}")
                return target

        # Fallback: roll back all changed prompts
        logger.info(
            f"[ROLLBACK] Target prompt not in changed list, rolling back ALL {len(changed_prompts)} changed prompts"
        )
        return changed_prompts

    def _check_baseline_degradation(
        self,
        db: Session,
        current_eval: models.EvaluationRun,
    ) -> DegradationCheck:
        """Check current eval against the best-known-good score.

        Catches gradual decline that per-run comparison misses. If the current
        score is significantly below the best score from recent runs, trigger
        a rollback even though each individual step was small.
        """
        recent_evals = (
            db.query(models.EvaluationRun)
            .filter(models.EvaluationRun.id != current_eval.id)
            .filter(models.EvaluationRun.status == "completed")
            .filter(models.EvaluationRun.overall_quality_score.isnot(None))
            .order_by(models.EvaluationRun.finished_at.desc())
            .limit(BASELINE_LOOKBACK_RUNS)
            .all()
        )

        if not recent_evals:
            return DegradationCheck(degraded=False)

        # Find the best overall score in recent history
        best_eval = max(recent_evals, key=lambda e: e.overall_quality_score or 0)
        best_score = best_eval.overall_quality_score
        current_score = current_eval.overall_quality_score

        if best_score is None or current_score is None:
            return DegradationCheck(degraded=False)

        # Use a larger threshold for baseline comparison (1.0 point)
        # to avoid false positives from normal variance
        baseline_threshold = 1.0
        drop = best_score - current_score

        if drop >= baseline_threshold:
            logger.warning(
                f"[ROLLBACK] Baseline degradation: best={best_score:.2f} "
                f"current={current_score:.2f} drop={drop:.2f} "
                f"threshold={baseline_threshold}"
            )
            return DegradationCheck(
                degraded=True,
                trigger_name="baseline_overall_score_drop",
                current_value=current_score,
                previous_value=best_score,
                threshold=baseline_threshold,
                drop_amount=drop,
                all_triggers=["baseline_overall_score_drop"],
            )

        return DegradationCheck(degraded=False)

    def execute_rollback(
        self,
        db: Session,
        prompt_name: str,
        model: str | None = None,
        target_version: int | None = None,
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
            prompt.updated_at = datetime.now(UTC)

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
        model: str | None = None,
    ) -> list[dict[str, Any]]:
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
