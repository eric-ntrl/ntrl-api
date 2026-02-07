# app/schemas/__init__.py
"""
Pydantic schemas for API request/response validation.
"""

from app.schemas.admin import (
    BriefRunRequest,
    BriefRunResponse,
    IngestRunRequest,
    IngestRunResponse,
    NeutralizeRunRequest,
    NeutralizeRunResponse,
)
from app.schemas.brief import (
    BriefResponse,
    BriefSection,
    BriefStory,
)
from app.schemas.evaluation import (
    ArticleEvaluationResult,
    AutoOptimizeConfigRequest,
    AutoOptimizeConfigResponse,
    EvaluationRecommendation,
    EvaluationRunListResponse,
    EvaluationRunRequest,
    EvaluationRunResponse,
    EvaluationRunSummary,
    PromptUpdate,
    PromptVersionListResponse,
    PromptVersionResponse,
    RollbackRequest,
    RollbackResponse,
    ScheduledRunEvaluationConfig,
)
from app.schemas.search import (
    FacetCount,
    SearchFacets,
    SearchResponse,
    SearchResultItem,
    SearchSuggestion,
)
from app.schemas.stories import (
    StoryDetail,
    StoryTransparency,
    TransparencySpanResponse,
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
    # Search schemas
    "SearchResultItem",
    "FacetCount",
    "SearchFacets",
    "SearchSuggestion",
    "SearchResponse",
]
