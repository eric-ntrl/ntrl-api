# NTRL API

**Neutral News Backend - Phase 1 POC**

A calm, deterministic news feed that removes manipulative language and produces neutral summaries.

## Core Promise

- **Neutralization**: Remove manipulative language, produce neutral headlines and summaries
- **Transparency**: Show what was removed and why
- **Deterministic**: Same input = same output, no personalization or trending
- **Calm UX**: No urgency language, no "breaking", no engagement mechanics

## What It Does

1. **Ingest** articles from RSS feeds (NPR, Fox News, NY Post, etc.)
2. **Neutralize** content by removing:
   - Clickbait ("shocking", "you won't believe")
   - Urgency inflation ("breaking", "just in")
   - Emotional triggers ("slams", "destroys", "furious")
   - Agenda signaling ("finally", "controversial")
   - Rhetorical framing
3. **Classify** into sections (World, U.S., Local, Business, Technology)
4. **Assemble** deterministic daily briefs

## Tech Stack

- **Framework**: FastAPI (Python 3.11)
- **Database**: PostgreSQL + SQLAlchemy 2.x
- **Migrations**: Alembic
- **Storage**: S3 or local filesystem (for raw article bodies)
- **Neutralizer**: Pluggable (mock for testing, OpenAI for production)

## API Endpoints

### Sources

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/sources` | GET | List all news sources |
| `/v1/sources` | POST | Add a new source |
| `/v1/sources/{slug}` | DELETE | Remove a source |

### Stories

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/stories` | GET | List stories with before/after comparison |
| `/v1/stories/{id}` | GET | Get story detail (neutralized) |
| `/v1/stories/{id}/transparency` | GET | Get transparency view (what was removed) |

### Brief

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/brief` | GET | Get the current daily brief |

### Pipeline (Admin)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/ingest/run` | POST | Trigger RSS ingestion |
| `/v1/neutralize/run` | POST | Trigger neutralization pipeline |
| `/v1/brief/run` | POST | Trigger brief assembly |

### Health

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/` | GET | API info |

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL
- pipenv

### Installation

```bash
# Clone and install
git clone git@github.com:eric-ntrl/ntrl-api.git
cd ntrl-api
pipenv install

# Configure
cp .env.example .env
# Edit .env with your database credentials and OpenAI API key

# Create database and run migrations
createdb ntrl_dev
pipenv run alembic upgrade head

# Start server
pipenv run dev
```

### Add Sources and Run Pipeline

```bash
# 1. Add a news source
curl -X POST http://localhost:8000/v1/sources \
  -H "Content-Type: application/json" \
  -d '{
    "name": "NY Post",
    "slug": "nypost",
    "rss_url": "https://nypost.com/feed/",
    "default_section": "us"
  }'

# 2. Ingest articles from RSS feeds
curl -X POST http://localhost:8000/v1/ingest/run

# 3. Neutralize ingested articles
curl -X POST http://localhost:8000/v1/neutralize/run

# 4. Assemble daily brief
curl -X POST http://localhost:8000/v1/brief/run

# 5. View the brief
curl http://localhost:8000/v1/brief

# 6. View stories with before/after comparison
curl http://localhost:8000/v1/stories
```

### Interactive Docs

Open http://localhost:8000/docs for Swagger UI.

## Example Responses

### GET /v1/stories (Before/After Comparison)

```json
{
  "stories": [
    {
      "id": "story-uuid",
      "original_title": "SHOCKING: Senator SLAMS critics in FURIOUS response",
      "original_description": "You won't believe what happened next...",
      "neutral_headline": "Senator responds to policy criticism",
      "neutral_summary": "The senator addressed concerns raised by opponents regarding the proposed legislation.",
      "source_name": "NY Post",
      "source_slug": "nypost",
      "has_manipulative_content": true,
      "is_neutralized": true
    }
  ],
  "total": 50
}
```

### GET /v1/stories/{id}/transparency

```json
{
  "id": "story-uuid",
  "original_title": "SHOCKING: Senator SLAMS critics in furious response",
  "original_description": "You won't believe what happened...",
  "neutral_headline": "Senator responds to policy criticism",
  "neutral_summary": "The senator addressed concerns raised by opponents.",
  "spans": [
    {
      "start_char": 0,
      "end_char": 8,
      "original_text": "SHOCKING",
      "action": "removed",
      "reason": "clickbait",
      "replacement_text": null
    },
    {
      "start_char": 19,
      "end_char": 24,
      "original_text": "SLAMS",
      "action": "replaced",
      "reason": "emotional_trigger",
      "replacement_text": "criticizes"
    }
  ],
  "disclosure": "Manipulative language removed.",
  "has_manipulative_content": true
}
```

### GET /v1/brief

```json
{
  "id": "brief-uuid",
  "brief_date": "2024-01-06T00:00:00",
  "sections": [
    {
      "name": "world",
      "display_name": "World",
      "stories": [
        {
          "neutral_headline": "International leaders meet to discuss trade agreement",
          "neutral_summary": "Representatives from 12 countries convened to negotiate terms.",
          "source_name": "NPR News",
          "has_manipulative_content": false
        }
      ],
      "story_count": 5
    }
  ],
  "total_stories": 25
}
```

## Project Structure

```
ntrl-api/
├── app/
│   ├── main.py              # FastAPI application
│   ├── database.py          # Database configuration
│   ├── models.py            # SQLAlchemy models
│   ├── routers/             # API endpoints
│   │   ├── brief.py         # GET /v1/brief
│   │   ├── stories.py       # GET /v1/stories/*
│   │   ├── sources.py       # /v1/sources CRUD
│   │   └── admin.py         # POST /v1/*/run
│   ├── schemas/             # Pydantic schemas
│   ├── services/            # Business logic
│   │   ├── ingestion.py     # RSS ingestion
│   │   ├── neutralizer.py   # Neutralization pipeline
│   │   ├── brief_assembly.py
│   │   ├── classifier.py    # Section classification
│   │   ├── deduper.py       # Deduplication
│   │   └── lifecycle.py     # Content retention/cleanup
│   └── storage/             # Object storage abstraction
│       ├── base.py          # StorageProvider interface
│       ├── s3_provider.py   # AWS S3 implementation
│       ├── local_provider.py # Local filesystem
│       └── factory.py       # Provider factory
├── migrations/              # Alembic migrations
├── storage/                 # Local storage directory (gitignored)
├── tests/                   # Unit tests
├── Pipfile
├── .env.example
└── README.md
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
# Database
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/ntrl_dev

# Neutralizer (mock = deterministic testing, openai = production)
NEUTRALIZER_PROVIDER=openai
OPENAI_API_KEY=sk-your-api-key

# Storage (local = development, s3 = production)
STORAGE_PROVIDER=local
# S3_BUCKET=your-bucket-name
# AWS_ACCESS_KEY_ID=xxx
# AWS_SECRET_ACCESS_KEY=xxx

# Content retention (days)
RAW_CONTENT_RETENTION_DAYS=30
```

## Storage Architecture

Raw article bodies are stored in object storage (S3 or local), not PostgreSQL:

- **Postgres stores**: Metadata, titles, descriptions, neutralized content, transparency spans
- **S3/Local stores**: Full article bodies (gzip compressed)
- **Retention**: Raw bodies expire after 30 days; metadata persists indefinitely

## Testing

```bash
# Install dev dependencies
pipenv install --dev

# Run tests
pipenv run pytest

# Run with coverage
pipenv run pytest --cov=app
```

## Design Constraints

### What We Don't Do

- **No engagement**: No likes, saves, shares, reactions, streaks
- **No personalization**: No "for you" feeds
- **No trending**: No popularity signals, viral content
- **No urgency**: No "breaking" alerts, push notifications
- **No fact-checking**: We remove manipulative language, not claims

### Determinism

The same stories always produce the same daily brief:
- Fixed section order (World → U.S. → Local → Business → Technology)
- Time-based ordering within sections (newest first)
- Deterministic tie-breakers (source priority, then ID)

## Manipulative Language Categories

The neutralizer detects and flags:

1. **Clickbait**: "You won't believe...", "What happened next...", ALL CAPS
2. **Urgency Inflation**: "BREAKING", "JUST IN" (when not actually urgent)
3. **Emotional Triggers**: "slams", "destroys", "blasts", "furious"
4. **Agenda Signaling**: "Finally", "controversial", loaded adjectives
5. **Rhetorical Framing**: Leading questions, false equivalence
6. **Selling**: "Must-read", "Essential", superlatives

## License

Proprietary - All rights reserved.
