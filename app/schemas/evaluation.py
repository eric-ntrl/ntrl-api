# app/schemas/evaluation.py
"""
Schemas for evaluation and prompt optimization endpoints.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# -----------------------------------------------------------------------------
# Score Comparison and Summary Schemas
# -----------------------------------------------------------------------------


class ScoreComparison(BaseModel):
    """Comparison with previous evaluation run."""

    previous_run_id: str | None = None
    classification_accuracy_prev: float | None = None
    classification_accuracy_delta: float | None = None
    classification_improved: bool | None = None
    neutralization_score_prev: float | None = None
    neutralization_score_delta: float | None = None
    neutralization_improved: bool | None = None
    span_precision_prev: float | None = None
    span_precision_delta: float | None = None
    span_recall_prev: float | None = None
    span_recall_delta: float | None = None
    overall_score_prev: float | None = None
    overall_score_delta: float | None = None
    overall_improved: bool | None = None


class MissedItemsSummary(BaseModel):
    """Aggregated missed manipulations and false positives."""

    total_missed_count: int = 0
    missed_by_category: dict[str, int] = Field(default_factory=dict)
    top_missed_phrases: list[dict[str, str]] = Field(default_factory=list)
    total_false_positives: int = 0
    top_false_positives: list[dict[str, str]] = Field(default_factory=list)


class PromptChangeDetail(BaseModel):
    """Detailed prompt change information."""

    prompt_name: str
    old_version: int
    new_version: int
    change_reason: str
    changes_made: list[str] = Field(default_factory=list)
    content_diff_summary: str | None = None


# -----------------------------------------------------------------------------
# Evaluation Run
# -----------------------------------------------------------------------------


class EvaluationRunRequest(BaseModel):
    """Request to trigger an evaluation run."""

    pipeline_run_id: str | None = Field(None, description="Pipeline run to evaluate (default: most recent)")
    teacher_model: str | None = Field(
        None, description="Teacher model for evaluation (default: uses EVAL_MODEL config)"
    )
    sample_size: int = Field(10, ge=1, le=50, description="Number of articles to sample for evaluation")
    enable_auto_optimize: bool = Field(False, description="Automatically apply prompt improvements if issues found")


class ArticleEvaluationResult(BaseModel):
    """Per-article evaluation result."""

    model_config = ConfigDict(from_attributes=True)

    story_raw_id: str
    original_title: str | None = None

    # Classification
    classification_correct: bool | None = None
    expected_domain: str | None = None
    expected_feed_category: str | None = None
    classification_feedback: str | None = None

    # Neutralization
    neutralization_score: float | None = None
    meaning_preservation_score: float | None = None
    neutrality_score: float | None = None
    grammar_score: float | None = None
    rule_violations: list[dict[str, Any]] | None = None
    neutralization_feedback: str | None = None

    # Spans
    span_precision: float | None = None
    span_recall: float | None = None
    missed_manipulations: list[dict[str, Any]] | None = None
    false_positives: list[dict[str, Any]] | None = None
    span_feedback: str | None = None


class EvaluationRecommendation(BaseModel):
    """A single recommendation from the teacher model."""

    prompt_name: str
    issue_category: str  # classification, neutralization, span_detection
    issue_description: str
    suggested_change: str
    priority: str  # high, medium, low
    affected_articles: list[str] = Field(default_factory=list)


class PromptUpdate(BaseModel):
    """Record of a prompt update."""

    prompt_name: str
    old_version: int
    new_version: int
    change_reason: str


class EvaluationRunResponse(BaseModel):
    """Response from an evaluation run."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_run_id: str
    teacher_model: str
    sample_size: int
    status: str = Field(..., description="running|completed|failed")

    # Timing
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None

    # Aggregate scores
    classification_accuracy: float | None = None
    avg_neutralization_score: float | None = None
    avg_span_precision: float | None = None
    avg_span_recall: float | None = None
    overall_quality_score: float | None = None

    # Score comparison with previous run
    score_comparison: ScoreComparison | None = None

    # Aggregated missed items summary
    missed_items_summary: MissedItemsSummary | None = None

    # Recommendations and actions
    recommendations: list[EvaluationRecommendation] | None = None
    prompts_updated: list[PromptUpdate] | None = None
    prompt_changes_detail: list[PromptChangeDetail] | None = None
    rollback_triggered: bool = False
    rollback_details: dict[str, Any] | None = None

    # Cost
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    # Article evaluations (optional - for detailed view)
    article_evaluations: list[ArticleEvaluationResult] | None = None


class EvaluationRunSummary(BaseModel):
    """Summary of an evaluation run for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_run_id: str
    teacher_model: str
    sample_size: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None

    # Key metrics
    classification_accuracy: float | None = None
    avg_neutralization_score: float | None = None
    overall_quality_score: float | None = None

    # Actions
    prompts_updated_count: int = 0
    rollback_triggered: bool = False

    # Cost
    estimated_cost_usd: float = 0.0


class EvaluationRunListResponse(BaseModel):
    """Response for listing evaluation runs."""

    evaluations: list[EvaluationRunSummary] = Field(default_factory=list)
    total: int = 0


# -----------------------------------------------------------------------------
# Prompt Version History
# -----------------------------------------------------------------------------


class PromptVersionResponse(BaseModel):
    """A single prompt version."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int
    content: str
    change_reason: str | None = None
    change_source: str  # manual, auto_optimize, rollback
    parent_version_id: str | None = None
    avg_score_at_creation: float | None = None
    created_at: datetime


class PromptVersionListResponse(BaseModel):
    """Response for listing prompt versions."""

    prompt_name: str
    prompt_id: str
    current_version: int
    versions: list[PromptVersionResponse] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Rollback
# -----------------------------------------------------------------------------


class RollbackRequest(BaseModel):
    """Request to rollback a prompt to a previous version."""

    target_version: int | None = Field(None, description="Version to rollback to (default: previous version)")
    reason: str | None = Field(None, description="Reason for rollback")


class RollbackResponse(BaseModel):
    """Response from a rollback operation."""

    status: str  # completed, failed
    prompt_name: str
    previous_version: int
    new_version: int
    rollback_reason: str
    created_at: datetime
    error: str | None = None


# -----------------------------------------------------------------------------
# Auto-Optimize Configuration
# -----------------------------------------------------------------------------


class AutoOptimizeConfigRequest(BaseModel):
    """Request to configure auto-optimization for a prompt."""

    enabled: bool = Field(..., description="Enable or disable auto-optimization")
    min_score_threshold: float | None = Field(
        None, ge=0.0, le=10.0, description="Minimum quality score threshold (default: 7.0)"
    )
    rollback_threshold: float | None = Field(
        None, ge=0.0, le=5.0, description="Score drop threshold for rollback (default: 0.5)"
    )


class AutoOptimizeConfigResponse(BaseModel):
    """Response showing current auto-optimize configuration."""

    prompt_name: str
    prompt_id: str
    auto_optimize_enabled: bool
    min_score_threshold: float
    rollback_threshold: float
    current_version: int
    updated_at: datetime


# -----------------------------------------------------------------------------
# Scheduled Run Extension
# -----------------------------------------------------------------------------


class ScheduledRunEvaluationConfig(BaseModel):
    """Evaluation configuration for scheduled pipeline runs."""

    enable_evaluation: bool = Field(False, description="Run teacher evaluation after pipeline")
    teacher_model: str | None = Field(None, description="Model to use for evaluation (default: uses EVAL_MODEL config)")
    eval_sample_size: int = Field(10, ge=1, le=50, description="Number of articles to evaluate")
    enable_auto_optimize: bool = Field(False, description="Auto-apply prompt improvements")
