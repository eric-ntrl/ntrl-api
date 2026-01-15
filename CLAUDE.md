# CLAUDE.md - Project Context for Claude Code

## Project Overview

NTRL API is a neutral news backend service that removes manipulative language from news articles and creates calm, deterministic news briefs.

## Core Architecture Principle

**The original article body is the single source of truth.**

```
INGESTION:     RSS → Database (metadata) + S3 (body.txt)
NEUTRALIZATION: body.txt → ALL outputs (title, summary, brief, full, spans)
DISPLAY:        Neutralized content by default, originals only in "ntrl view"
```

- RSS title/description are stored for audit but NOT used for neutralization
- All user-facing content is derived from the scraped article body
- Transparency spans reference the original body for highlighting

See `docs/ARCHITECTURE.md` for full details.

## Tech Stack

- **Framework**: FastAPI (Python 3.11) with Uvicorn
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Migrations**: Alembic
- **Storage**: S3 or local filesystem for raw articles
- **AI**: Pluggable neutralizers (mock, OpenAI, Anthropic)
- **Dependencies**: Pipenv

## Key Commands

```bash
# Run the server
pipenv run uvicorn app.main:app --reload --port 8000

# Run tests
pipenv run python -m pytest tests/

# Database migrations
pipenv run alembic upgrade head
pipenv run alembic revision --autogenerate -m "description"

# Install dependencies
pipenv install
```

## Project Structure

```
app/
├── main.py              # FastAPI entry point
├── database.py          # DB configuration
├── models.py            # SQLAlchemy ORM models
├── routers/             # API endpoints (brief, stories, sources, admin)
├── schemas/             # Pydantic request/response schemas
├── services/            # Business logic (ingestion, neutralizer, brief_assembly)
├── storage/             # Object storage providers (S3, local)
└── jobs/                # Background jobs
migrations/              # Alembic migrations
tests/                   # Unit tests
```

## Development Workflow

This project uses a PRD-driven development approach with Claude Code skills:

1. **PRD** (`docs/prd/`) - Product requirements documents define features
2. **Stories** (`docs/stories/`) - Bite-sized implementation units with acceptance criteria
3. **Skills** - Claude Code commands for self-optimization:
   - `/prd` - Load and analyze a PRD
   - `/story` - Work on a specific story
   - `/validate` - Check acceptance criteria

## Code Style

- Use type hints for all function signatures
- Follow PEP 8 conventions
- Keep functions focused and small
- Write tests for new functionality
