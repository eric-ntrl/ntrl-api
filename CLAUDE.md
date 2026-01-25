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
- **NLP**: spaCy (en_core_web_sm) for structural detection
- **Dependencies**: Pipenv

## NTRL Filter v2 Architecture

The v2 architecture uses a two-phase approach for detecting and neutralizing manipulation:

```
Article Input
     │
     ▼
┌─────────────────────────────────────────────┐
│ Phase 1: ntrl-scan (Detection) ~400ms       │
│   ├── Lexical: regex patterns (~20ms)       │
│   ├── Structural: spaCy NLP (~80ms)         │
│   └── Semantic: LLM detection (~300ms)      │
│   → Outputs: DetectionInstance spans        │
├─────────────────────────────────────────────┤
│ Phase 2: ntrl-fix (Rewriting) ~800ms        │
│   ├── Detail Full: span-guided rewrite      │
│   ├── Detail Brief: synthesis               │
│   ├── Feed Outputs: title/summary           │
│   └── Red-Line Validator: 10 invariance     │
│   → Outputs: Neutralized content            │
└─────────────────────────────────────────────┘
     │
     ▼
Neutralized Content + Transparency Package
```

**Target latency**: 1-2 seconds per article

### V2 API Endpoints

```
POST /v2/scan         - Detection only (returns spans)
POST /v2/process      - Full pipeline (scan + fix)
POST /v2/batch        - Batch processing (up to 100 articles)
POST /v2/transparency - Full transparency package
```

### Manipulation Taxonomy

The taxonomy (`app/taxonomy.py`) defines 115 manipulation types across 6 categories:

| Category | Name | Examples |
|----------|------|----------|
| A | Attention & Engagement | Curiosity gaps, urgency markers, clickbait |
| B | Emotional & Affective | Rage verbs, fear appeals, tribal priming |
| C | Cognitive & Epistemic | False balance, motive certainty, anecdote-as-proof |
| D | Linguistic & Framing | Passive voice, vague attribution, loaded terms |
| E | Structural & Editorial | Buried lede, missing context |
| F | Incentive & Meta | Agenda masking, incentive opacity |

### Red-Line Validator

The validator (`ntrl_fix/validator.py`) enforces 10 invariance checks:

1. **Entity invariance** - Names, orgs, places preserved
2. **Number invariance** - All numbers preserved exactly
3. **Date invariance** - All dates preserved
4. **Attribution invariance** - Who said what preserved
5. **Modality invariance** - "alleged" never becomes "confirmed"
6. **Causality invariance** - Causal claims unchanged
7. **Risk invariance** - Warnings preserved
8. **Quote integrity** - Direct quotes verbatim
9. **Scope invariance** - Quantifiers unchanged
10. **Negation integrity** - "not" never accidentally removed

### Key V2 Classes

```python
# Detection
from app.services.ntrl_scan import NTRLScanner, ScannerConfig
scanner = NTRLScanner(config=ScannerConfig(enable_semantic=True))
result = await scanner.scan(text, ArticleSegment.BODY)

# Rewriting
from app.services.ntrl_fix import NTRLFixer, FixerConfig
fixer = NTRLFixer(config=FixerConfig())
result = await fixer.fix(body, title, body_scan, title_scan)

# Full Pipeline
from app.services.ntrl_pipeline import NTRLPipeline, PipelineConfig
pipeline = NTRLPipeline(config=PipelineConfig())
result = await pipeline.process(body, title)
```

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

## Staging Environment

- **API URL**: `https://api-staging-7b4d.up.railway.app`
- **Admin API Key**: `staging-key-123` (use in `X-API-Key` header)

### Common Operations

```bash
# Trigger RSS ingestion
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/ingest/run" \
  -H "X-API-Key: staging-key-123"

# Neutralize pending articles
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"limit": 50}'

# Rebuild the daily brief
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/brief/run" \
  -H "X-API-Key: staging-key-123"

# Check system status
curl "https://api-staging-7b4d.up.railway.app/v1/status"
```

## Project Structure

```
app/
├── main.py              # FastAPI entry point
├── database.py          # DB configuration
├── models.py            # SQLAlchemy ORM models
├── taxonomy.py          # 115 manipulation types (v2)
├── routers/
│   ├── admin.py         # V1 admin endpoints
│   ├── brief.py         # V1 brief endpoints
│   ├── stories.py       # V1 story endpoints
│   ├── sources.py       # V1 sources endpoints
│   └── pipeline.py      # V2 pipeline endpoints (/v2/scan, /v2/process, /v2/batch)
├── schemas/             # Pydantic request/response schemas
├── services/
│   ├── ingestion.py     # RSS ingestion
│   ├── neutralizer.py   # V1 neutralizer (legacy)
│   ├── brief_assembly.py
│   ├── ntrl_scan/       # V2 detection phase
│   │   ├── lexical_detector.py    # Regex patterns (~20ms)
│   │   ├── structural_detector.py # spaCy NLP (~80ms)
│   │   ├── semantic_detector.py   # LLM detection (~300ms)
│   │   └── scanner.py             # Parallel orchestrator
│   ├── ntrl_fix/        # V2 rewriting phase
│   │   ├── detail_full_gen.py     # Full article neutralization
│   │   ├── detail_brief_gen.py    # Brief synthesis
│   │   ├── feed_outputs_gen.py    # Title/summary generation
│   │   ├── validator.py           # 10 red-line invariance checks
│   │   └── fixer.py               # Parallel orchestrator
│   ├── ntrl_pipeline.py # V2 unified pipeline
│   └── ntrl_batcher.py  # V2 batch processing
├── storage/             # Object storage providers (S3, local)
└── jobs/                # Background jobs
migrations/              # Alembic migrations
tests/                   # Unit tests (156 tests for v2)
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

## UI Verification (CRITICAL)

**When making changes that affect the mobile app UI, Claude MUST verify the changes work before asking the user to test.**

Changes that require UI verification:
- Neutralization output (detail_full, detail_brief, feed_title, feed_summary)
- Transparency spans (ntrl-view highlights)
- Any API response format changes

### How to Verify

After deploying backend changes to staging:

1. **Re-neutralize articles** on staging:
   ```bash
   curl -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: staging-key-123" \
     -d '{"neutralize_limit": 10, "skip_ingest": true, "skip_brief": false}'
   ```

2. **Test the UI** using ntrl-app's testing tools (see `../ntrl-app/CLAUDE.md` for methods):
   - Playwright for web screenshots
   - Maestro for iOS simulator
   - Direct simulator screenshots via `xcrun simctl`

3. **Verify specific screens**:
   - Feed view: Are titles neutralized?
   - Article detail (full view): Is detail_full neutralized?
   - NTRL view: Are transparency spans highlighted?

4. **Only after visual verification**, report results to the user.

### Related Project
The mobile app is at `../ntrl-app/` - see its CLAUDE.md for UI testing commands.
