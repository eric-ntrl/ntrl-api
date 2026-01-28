# app/schemas/__init__.py
"""
Pydantic schemas for API request/response validation.
"""

from app.schemas.stories import (
    StoryDetail,
    StoryTransparency,
    TransparencySpanResponse,
)
from app.schemas.brief import (
    BriefResponse,
    BriefSection,
    BriefStory,
)
from app.schemas.admin import (
    IngestRunRequest,
    IngestRunResponse,
    NeutralizeRunRequest,
    NeutralizeRunResponse,
    BriefRunRequest,
    BriefRunResponse,
)
from app.schemas.evaluation import (
    EvaluationRunRequest,
    EvaluationRunResponse,
    EvaluationRunSummary,
    EvaluationRunListResponse,
    ArticleEvaluationResult,
    EvaluationRecommendation,
    PromptUpdate,
    PromptVersionResponse,
    PromptVersionListResponse,
    RollbackRequest,
    RollbackResponse,
    AutoOptimizeConfigRequest,
    AutoOptimizeConfigResponse,
    ScheduledRunEvaluationConfig,
)

__all__ = [
    "StoryDetail",
    "StoryTransparency",
    "TransparencySpanResponse",
    "BriefResponse",
    "BriefSection",
    "BriefStory",
    "IngestRunRequest",
    "IngestRunResponse",
    "NeutralizeRunRequest",
    "NeutralizeRunResponse",
    "BriefRunRequest",
    "BriefRunResponse",
    # Evaluation schemas
    "EvaluationRunRequest",
    "EvaluationRunResponse",
    "EvaluationRunSummary",
    "EvaluationRunListResponse",
    "ArticleEvaluationResult",
    "EvaluationRecommendation",
    "PromptUpdate",
    "PromptVersionResponse",
    "PromptVersionListResponse",
    "RollbackRequest",
    "RollbackResponse",
    "AutoOptimizeConfigRequest",
    "AutoOptimizeConfigResponse",
    "ScheduledRunEvaluationConfig",
]
