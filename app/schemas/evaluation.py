# app/schemas/evaluation.py
"""
Schemas for evaluation and prompt optimization endpoints.
"""

from datetime import datetime
from typing import List, Optional, Any, Dict
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


# -----------------------------------------------------------------------------
# Score Comparison and Summary Schemas
# -----------------------------------------------------------------------------

class ScoreComparison(BaseModel):
    """Comparison with previous evaluation run."""
    previous_run_id: Optional[str] = None
    classification_accuracy_prev: Optional[float] = None
    classification_accuracy_delta: Optional[float] = None
    classification_improved: Optional[bool] = None
    neutralization_score_prev: Optional[float] = None
    neutralization_score_delta: Optional[float] = None
    neutralization_improved: Optional[bool] = None
    span_precision_prev: Optional[float] = None
    span_precision_delta: Optional[float] = None
    span_recall_prev: Optional[float] = None
    span_recall_delta: Optional[float] = None
    overall_score_prev: Optional[float] = None
    overall_score_delta: Optional[float] = None
    overall_improved: Optional[bool] = None


class MissedItemsSummary(BaseModel):
    """Aggregated missed manipulations and false positives."""
    total_missed_count: int = 0
    missed_by_category: Dict[str, int] = Field(default_factory=dict)
    top_missed_phrases: List[Dict[str, str]] = Field(default_factory=list)
    total_false_positives: int = 0
    top_false_positives: List[Dict[str, str]] = Field(default_factory=list)


class PromptChangeDetail(BaseModel):
    """Detailed prompt change information."""
    prompt_name: str
    old_version: int
    new_version: int
    change_reason: str
    changes_made: List[str] = Field(default_factory=list)
    content_diff_summary: Optional[str] = None


# -----------------------------------------------------------------------------
# Evaluation Run
# -----------------------------------------------------------------------------

class EvaluationRunRequest(BaseModel):
    """Request to trigger an evaluation run."""
    pipeline_run_id: Optional[str] = Field(
        None,
        description="Pipeline run to evaluate (default: most recent)"
    )
    teacher_model: Optional[str] = Field(
        None,
        description="Teacher model for evaluation (default: uses EVAL_MODEL config)"
    )
    sample_size: int = Field(
        10,
        ge=1,
        le=50,
        description="Number of articles to sample for evaluation"
    )
    enable_auto_optimize: bool = Field(
        False,
        description="Automatically apply prompt improvements if issues found"
    )


class ArticleEvaluationResult(BaseModel):
    """Per-article evaluation result."""
    model_config = ConfigDict(from_attributes=True)

    story_raw_id: str
    original_title: Optional[str] = None

    # Classification
    classification_correct: Optional[bool] = None
    expected_domain: Optional[str] = None
    expected_feed_category: Optional[str] = None
    classification_feedback: Optional[str] = None

    # Neutralization
    neutralization_score: Optional[float] = None
    meaning_preservation_score: Optional[float] = None
    neutrality_score: Optional[float] = None
    grammar_score: Optional[float] = None
    rule_violations: Optional[List[Dict[str, Any]]] = None
    neutralization_feedback: Optional[str] = None

    # Spans
    span_precision: Optional[float] = None
    span_recall: Optional[float] = None
    missed_manipulations: Optional[List[Dict[str, Any]]] = None
    false_positives: Optional[List[Dict[str, Any]]] = None
    span_feedback: Optional[str] = None


class EvaluationRecommendation(BaseModel):
    """A single recommendation from the teacher model."""
    prompt_name: str
    issue_category: str  # classification, neutralization, span_detection
    issue_description: str
    suggested_change: str
    priority: str  # high, medium, low
    affected_articles: List[str] = Field(default_factory=list)


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
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    # Aggregate scores
    classification_accuracy: Optional[float] = None
    avg_neutralization_score: Optional[float] = None
    avg_span_precision: Optional[float] = None
    avg_span_recall: Optional[float] = None
    overall_quality_score: Optional[float] = None

    # Score comparison with previous run
    score_comparison: Optional[ScoreComparison] = None

    # Aggregated missed items summary
    missed_items_summary: Optional[MissedItemsSummary] = None

    # Recommendations and actions
    recommendations: Optional[List[EvaluationRecommendation]] = None
    prompts_updated: Optional[List[PromptUpdate]] = None
    prompt_changes_detail: Optional[List[PromptChangeDetail]] = None
    rollback_triggered: bool = False
    rollback_details: Optional[Dict[str, Any]] = None

    # Cost
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    # Article evaluations (optional - for detailed view)
    article_evaluations: Optional[List[ArticleEvaluationResult]] = None


class EvaluationRunSummary(BaseModel):
    """Summary of an evaluation run for list views."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    pipeline_run_id: str
    teacher_model: str
    sample_size: int
    status: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None

    # Key metrics
    classification_accuracy: Optional[float] = None
    avg_neutralization_score: Optional[float] = None
    overall_quality_score: Optional[float] = None

    # Actions
    prompts_updated_count: int = 0
    rollback_triggered: bool = False

    # Cost
    estimated_cost_usd: float = 0.0


class EvaluationRunListResponse(BaseModel):
    """Response for listing evaluation runs."""
    evaluations: List[EvaluationRunSummary] = Field(default_factory=list)
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
    change_reason: Optional[str] = None
    change_source: str  # manual, auto_optimize, rollback
    parent_version_id: Optional[str] = None
    avg_score_at_creation: Optional[float] = None
    created_at: datetime


class PromptVersionListResponse(BaseModel):
    """Response for listing prompt versions."""
    prompt_name: str
    prompt_id: str
    current_version: int
    versions: List[PromptVersionResponse] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Rollback
# -----------------------------------------------------------------------------

class RollbackRequest(BaseModel):
    """Request to rollback a prompt to a previous version."""
    target_version: Optional[int] = Field(
        None,
        description="Version to rollback to (default: previous version)"
    )
    reason: Optional[str] = Field(
        None,
        description="Reason for rollback"
    )


class RollbackResponse(BaseModel):
    """Response from a rollback operation."""
    status: str  # completed, failed
    prompt_name: str
    previous_version: int
    new_version: int
    rollback_reason: str
    created_at: datetime
    error: Optional[str] = None


# -----------------------------------------------------------------------------
# Auto-Optimize Configuration
# -----------------------------------------------------------------------------

class AutoOptimizeConfigRequest(BaseModel):
    """Request to configure auto-optimization for a prompt."""
    enabled: bool = Field(
        ...,
        description="Enable or disable auto-optimization"
    )
    min_score_threshold: Optional[float] = Field(
        None,
        ge=0.0,
        le=10.0,
        description="Minimum quality score threshold (default: 7.0)"
    )
    rollback_threshold: Optional[float] = Field(
        None,
        ge=0.0,
        le=5.0,
        description="Score drop threshold for rollback (default: 0.5)"
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
    enable_evaluation: bool = Field(
        False,
        description="Run teacher evaluation after pipeline"
    )
    teacher_model: Optional[str] = Field(
        None,
        description="Model to use for evaluation (default: uses EVAL_MODEL config)"
    )
    eval_sample_size: int = Field(
        10,
        ge=1,
        le=50,
        description="Number of articles to evaluate"
    )
    enable_auto_optimize: bool = Field(
        False,
        description="Auto-apply prompt improvements"
    )
