# app/main.py
"""
NTRL Phase-1 POC - Neutral News Backend API

A calm, deterministic news feed that removes manipulative language.

No engagement mechanics (likes, saves, shares).
No personalization, trending, or recommendations.
No urgency language or "breaking" alerts.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import brief_router, stories_router, admin_router

# Create app
app = FastAPI(
    title="NTRL API",
    description="Neutral News Backend - Phase 1 POC",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(brief_router)
app.include_router(stories_router)
app.include_router(admin_router)


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
        "version": "1.0.0",
        "description": "Neutral News Backend - Phase 1 POC",
        "docs": "/docs",
        "endpoints": {
            "brief": "GET /v1/brief",
            "story": "GET /v1/stories/{id}",
            "transparency": "GET /v1/stories/{id}/transparency",
            "ingest": "POST /v1/ingest/run",
            "neutralize": "POST /v1/neutralize/run",
            "brief_run": "POST /v1/brief/run",
        },
    }
