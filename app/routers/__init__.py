# app/routers/__init__.py
"""
API routers for v1 and v2 endpoints.
"""

from app.routers.brief import router as brief_router
from app.routers.stories import router as stories_router
from app.routers.admin import router as admin_router
from app.routers.sources import router as sources_router
from app.routers.pipeline import router as pipeline_router
from app.routers.admin_retention import router as admin_retention_router
from app.routers.search import router as search_router
from app.routers.topics import router as topics_router

__all__ = [
    "brief_router",
    "stories_router",
    "admin_router",
    "sources_router",
    "pipeline_router",
    "admin_retention_router",
    "search_router",
    "topics_router",
]
