# app/services/prompt_optimizer.py
"""
Prompt optimization service for automated prompt improvements.

Uses teacher LLM feedback to generate improved prompts, then applies
them with full version history tracking.
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from sqlalchemy.orm import Session

from app import models
from app.models import ChangeSource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt improvement generation
# ---------------------------------------------------------------------------

PROMPT_IMPROVEMENT_SYSTEM = """You are an expert prompt engineer improving LLM prompts for a news neutralization pipeline.

Given:
1. The current prompt
2. Identified issues from teacher evaluation
3. Specific examples of failures

Generate an improved prompt that:
- Fixes the identified issues
- Preserves all working functionality
- Adds specific examples where helpful
- Keeps the prompt concise and focused

IMPORTANT:
- Make targeted changes, not wholesale rewrites
- Add explicit guidance for the failure cases
- Include concrete examples when patterns emerge
- Do NOT change unrelated parts of the prompt

Respond with JSON:
{
  "improved_prompt": "<the complete improved prompt text>",
  "changes_made": ["<list of specific changes>"],
  "rationale": "<why these changes should fix the issues>"
}"""


@dataclass
class PromptImprovement:
    """Result of a prompt improvement generation."""
    prompt_name: str
    original_content: str
    improved_content: str
    changes_made: List[str]
    rationale: str
    issues_addressed: List[str]


@dataclass
class OptimizationResult:
    """Result of an optimization run."""
    prompts_updated: List[Dict]
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float
    status: str = "completed"
    error: Optional[str] = None


class PromptOptimizer:
    """
    Generates and applies prompt improvements based on evaluation results.

    Uses a teacher LLM to analyze failure patterns and generate targeted
    prompt improvements. All changes are versioned for rollback.
    """

    def __init__(self, teacher_model: str = "gpt-4o"):
        """Initialize the optimizer."""
        self.teacher_model = teacher_model
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    def analyze_and_improve(
        self,
        db: Session,
        evaluation_run_id: str,
        auto_apply: bool = False,
    ) -> OptimizationResult:
        """
        Analyze evaluation results and generate prompt improvements.

        Args:
            db: Database session
            evaluation_run_id: ID of the EvaluationRun to analyze
            auto_apply: If True, automatically apply improvements

        Returns:
            OptimizationResult with list of improvements made
        """
        self._total_input_tokens = 0
        self._total_output_tokens = 0

        logger.info(f"[OPTIMIZE] Analyzing evaluation run {evaluation_run_id}")

        # Get evaluation run with recommendations
        eval_run = db.query(models.EvaluationRun).filter(
            models.EvaluationRun.id == uuid.UUID(evaluation_run_id)
        ).first()

        if not eval_run:
            return OptimizationResult(
                prompts_updated=[],
                total_input_tokens=0,
                total_output_tokens=0,
                estimated_cost_usd=0.0,
                status="failed",
                error=f"Evaluation run {evaluation_run_id} not found",
            )

        if not eval_run.recommendations:
            logger.info("[OPTIMIZE] No recommendations to process")
            return OptimizationResult(
                prompts_updated=[],
                total_input_tokens=0,
                total_output_tokens=0,
                estimated_cost_usd=0.0,
                status="completed",
            )

        prompts_updated = []

        # Group recommendations by prompt (key = (name, model))
        by_prompt: Dict[tuple, List[Dict]] = {}
        for rec in eval_run.recommendations:
            prompt_name = rec.get("prompt_name")
            prompt_model = rec.get("model")  # None for model-agnostic prompts
            if prompt_name:
                key = (prompt_name, prompt_model)
                by_prompt.setdefault(key, []).append(rec)

        # Process each prompt with issues
        for (prompt_name, prompt_model), issues in by_prompt.items():
            try:
                # Get current prompt from DB
                # Handle model-agnostic prompts (model=NULL) vs model-specific ones
                query = db.query(models.Prompt).filter(
                    models.Prompt.name == prompt_name,
                    models.Prompt.is_active == True,
                )
                if prompt_model is None:
                    # Model-agnostic prompt (model IS NULL)
                    query = query.filter(models.Prompt.model.is_(None))
                else:
                    # Model-specific prompt
                    query = query.filter(models.Prompt.model == prompt_model)

                prompt = query.first()

                if not prompt:
                    logger.warning(f"[OPTIMIZE] Prompt '{prompt_name}' not found, skipping")
                    continue

                # Check if auto-optimize is enabled for this prompt
                if not prompt.auto_optimize_enabled and auto_apply:
                    logger.info(f"[OPTIMIZE] Auto-optimize disabled for '{prompt_name}', skipping")
                    continue

                # Generate improvement
                improvement = self._generate_improvement(prompt, issues)

                if not improvement:
                    logger.warning(f"[OPTIMIZE] Failed to generate improvement for '{prompt_name}'")
                    continue

                # Apply if requested
                model_desc = f" (model={prompt_model})" if prompt_model else " (model-agnostic)"
                if auto_apply:
                    update_result = self._apply_improvement(db, prompt, improvement, eval_run)
                    if update_result:
                        prompts_updated.append(update_result)
                        logger.info(f"[OPTIMIZE] Applied improvement to '{prompt_name}'{model_desc}")
                else:
                    # Just log the proposed improvement
                    logger.info(
                        f"[OPTIMIZE] Generated improvement for '{prompt_name}'{model_desc}: "
                        f"{len(improvement.changes_made)} changes"
                    )
                    prompts_updated.append({
                        "prompt_name": prompt_name,
                        "model": prompt_model,
                        "old_version": prompt.version,
                        "new_version": None,  # Not applied
                        "change_reason": improvement.rationale,
                        "applied": False,
                    })

            except Exception as e:
                logger.error(f"[OPTIMIZE] Failed to process prompt '{prompt_name}': {e}")

        # Calculate cost
        estimated_cost = (
            self._total_input_tokens * 5.00 / 1_000_000 +
            self._total_output_tokens * 15.00 / 1_000_000
        )

        # Update evaluation run with prompts_updated
        if auto_apply and prompts_updated:
            eval_run.prompts_updated = prompts_updated

        db.commit()

        return OptimizationResult(
            prompts_updated=prompts_updated,
            total_input_tokens=self._total_input_tokens,
            total_output_tokens=self._total_output_tokens,
            estimated_cost_usd=estimated_cost,
            status="completed",
        )

    def _generate_improvement(
        self,
        prompt: models.Prompt,
        issues: List[Dict],
    ) -> Optional[PromptImprovement]:
        """Generate an improved prompt based on identified issues."""
        # Build issue summary
        issue_descriptions = []
        affected_articles = set()
        for issue in issues:
            desc = issue.get("issue_description", "")
            suggestion = issue.get("suggested_change", "")
            issue_descriptions.append(f"- {desc}")
            if suggestion:
                issue_descriptions.append(f"  Suggestion: {suggestion}")
            for article_id in issue.get("affected_articles", []):
                affected_articles.add(article_id)

        user_prompt = f"""CURRENT PROMPT (name: {prompt.name}):
```
{prompt.content}
```

IDENTIFIED ISSUES:
{chr(10).join(issue_descriptions)}

AFFECTED ARTICLES: {len(affected_articles)} articles

Generate an improved prompt that fixes these issues while preserving all working functionality."""

        try:
            result = self._call_teacher(PROMPT_IMPROVEMENT_SYSTEM, user_prompt)

            if not result or "improved_prompt" not in result:
                return None

            return PromptImprovement(
                prompt_name=prompt.name,
                original_content=prompt.content,
                improved_content=result["improved_prompt"],
                changes_made=result.get("changes_made", []),
                rationale=result.get("rationale", ""),
                issues_addressed=[i.get("issue_description", "") for i in issues],
            )

        except Exception as e:
            logger.error(f"[OPTIMIZE] Failed to generate improvement: {e}")
            return None

    def _apply_improvement(
        self,
        db: Session,
        prompt: models.Prompt,
        improvement: PromptImprovement,
        eval_run: models.EvaluationRun,
    ) -> Optional[Dict]:
        """Apply a prompt improvement with version tracking."""
        try:
            old_version = prompt.version
            new_version = old_version + 1

            # Create version history entry for old version (if not exists)
            existing_version = db.query(models.PromptVersion).filter(
                models.PromptVersion.prompt_id == prompt.id,
                models.PromptVersion.version == old_version,
            ).first()

            if not existing_version:
                # Create version entry for the current content before overwriting
                old_version_entry = models.PromptVersion(
                    id=uuid.uuid4(),
                    prompt_id=prompt.id,
                    version=old_version,
                    content=prompt.content,
                    change_reason="Historical version before auto-optimization",
                    change_source=ChangeSource.MANUAL.value,
                    avg_score_at_creation=eval_run.overall_quality_score,
                )
                db.add(old_version_entry)
                db.flush()
                parent_version_id = old_version_entry.id
            else:
                parent_version_id = existing_version.id

            # Create new version entry
            change_reason = f"Auto-optimize: {improvement.rationale[:200]}"
            new_version_entry = models.PromptVersion(
                id=uuid.uuid4(),
                prompt_id=prompt.id,
                version=new_version,
                content=improvement.improved_content,
                change_reason=change_reason,
                change_source=ChangeSource.AUTO_OPTIMIZE.value,
                parent_version_id=parent_version_id,
                avg_score_at_creation=eval_run.overall_quality_score,
            )
            db.add(new_version_entry)

            # Update the prompt
            prompt.content = improvement.improved_content
            prompt.version = new_version
            prompt.current_version_id = new_version_entry.id
            prompt.updated_at = datetime.now(timezone.utc)

            db.flush()

            return {
                "prompt_name": prompt.name,
                "model": prompt.model,  # None for model-agnostic prompts
                "old_version": old_version,
                "new_version": new_version,
                "change_reason": change_reason,
                "applied": True,
            }

        except Exception as e:
            logger.error(f"[OPTIMIZE] Failed to apply improvement: {e}")
            return None

    def _call_teacher(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        """Call the teacher LLM."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, timeout=60.0)

            response = client.chat.completions.create(
                model=self.teacher_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            if response.usage:
                self._total_input_tokens += response.usage.prompt_tokens
                self._total_output_tokens += response.usage.completion_tokens

            content = response.choices[0].message.content.strip()
            return json.loads(content)

        except Exception as e:
            logger.error(f"[OPTIMIZE] Teacher LLM call failed: {e}")
            raise


# ---------------------------------------------------------------------------
# Version management utilities
# ---------------------------------------------------------------------------

def get_prompt_versions(
    db: Session,
    prompt_name: str,
    model: Optional[str] = None,
) -> List[models.PromptVersion]:
    """Get version history for a prompt."""
    prompt = db.query(models.Prompt).filter(
        models.Prompt.name == prompt_name,
    )
    if model:
        prompt = prompt.filter(models.Prompt.model == model)
    else:
        prompt = prompt.filter(models.Prompt.model.is_(None))

    prompt = prompt.first()
    if not prompt:
        return []

    versions = (
        db.query(models.PromptVersion)
        .filter(models.PromptVersion.prompt_id == prompt.id)
        .order_by(models.PromptVersion.version.desc())
        .all()
    )

    return versions


def create_initial_version(
    db: Session,
    prompt: models.Prompt,
    change_reason: str = "Initial version",
) -> models.PromptVersion:
    """Create initial version entry for a prompt."""
    version_entry = models.PromptVersion(
        id=uuid.uuid4(),
        prompt_id=prompt.id,
        version=prompt.version,
        content=prompt.content,
        change_reason=change_reason,
        change_source=ChangeSource.MANUAL.value,
    )
    db.add(version_entry)
    prompt.current_version_id = version_entry.id
    db.flush()
    return version_entry
