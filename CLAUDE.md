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

## Text/UI Length Constraints

When UI text appears too long or gets truncated with "...", the constraint is usually in the **backend LLM prompt**, not frontend CSS.

### Where to Look
- `app/services/neutralizer.py` - Contains all LLM prompts
- Search for `feed_summary`, `feed_title`, `detail_title`, `detail_brief`
- Look for character/word limits in prompt text (e.g., "≤100 characters")

### Key Lessons
1. **LLMs don't count accurately** - If you need max 115 chars, tell the LLM 100
2. **Examples > Instructions** - LLMs follow examples more than stated constraints
3. **After changes**: Must re-neutralize articles with `force: true` flag
4. **Frontend `numberOfLines`** only truncates display - doesn't control content length

### Workflow for Length Changes
1. Find constraint in `neutralizer.py` prompt
2. Reduce limit (add 15-20% buffer for LLM inaccuracy)
3. Update examples to match target length
4. Deploy to Railway
5. Re-neutralize: `POST /v1/neutralize/run` with `force: true`
6. Rebuild brief: `POST /v1/brief/run`
7. Verify in app

### Reference: Line Capacity
- Mobile displays ~38-42 chars per line
- 2 lines ≈ 65 chars | 3 lines ≈ 100 chars | 4 lines ≈ 135 chars
- Use `/ui-length` skill for guided workflow
