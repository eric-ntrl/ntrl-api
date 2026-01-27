# app/main.py
"""
NTRL Phase-1 POC - Neutral News Backend API

A calm, deterministic news feed that removes manipulative language.

No engagement mechanics (likes, saves, shares).
No personalization, trending, or recommendations.
No urgency language or "breaking" alerts.
"""

import logging
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.routers import brief_router, stories_router, admin_router, sources_router, pipeline_router

logger = logging.getLogger(__name__)

# Rate limiter — in-memory store (upgrade to Redis for multi-instance)
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# Create app
app = FastAPI(
    title="NTRL API",
    description="Neutral News Backend - Phase 1 POC",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Attach rate limiter to app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def custom_openapi():
    """Custom OpenAPI schema with API key security."""
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    # Add API key security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "Admin API key for pipeline operations",
        }
    }
    # Apply security to all admin endpoints
    for path in openapi_schema["paths"]:
        if any(x in path for x in ["/ingest/", "/neutralize/", "/brief/", "/pipeline/", "/prompts"]):
            for method in openapi_schema["paths"][path]:
                if method != "parameters":
                    openapi_schema["paths"][path][method]["security"] = [{"ApiKeyAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# CORS middleware — restrict origins in production
_cors_origins_env = os.getenv("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()] if _cors_origins_env else [
    "http://localhost:8081",
    "http://localhost:19006",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key"],
)

# Global exception handler — never leak internal details to clients
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = str(uuid.uuid4())[:8]
    logger.error(f"Unhandled exception [request_id={request_id}]: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
    )


# Include routers
app.include_router(brief_router)
app.include_router(stories_router)
app.include_router(admin_router)
app.include_router(sources_router)
app.include_router(pipeline_router)  # NTRL Filter v2 pipeline


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"])
def health() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "ntrl-api",
        "version": "1.0.0",
    }


@app.get("/", tags=["health"])
def root() -> dict:
    """Root endpoint with API info."""
    return {
        "service": "NTRL API",
        "version": "2.0.0",
        "description": "Neutral News Backend",
        "docs": "/docs",
        "endpoints": {
            # V1 endpoints (legacy)
            "brief": "GET /v1/brief",
            "story": "GET /v1/stories/{id}",
            "transparency": "GET /v1/stories/{id}/transparency",
            "sources": "GET /v1/sources",
            "add_source": "POST /v1/sources",
            "ingest": "POST /v1/ingest/run",
            "neutralize": "POST /v1/neutralize/run",
            "brief_run": "POST /v1/brief/run",
            # V2 endpoints (NTRL Filter v2)
            "v2_scan": "POST /v2/scan",
            "v2_process": "POST /v2/process",
            "v2_batch": "POST /v2/batch",
            "v2_transparency": "POST /v2/transparency",
        },
    }
