# NTRL API

**Neutral News Backend - Phase 1 POC**

A calm, deterministic news feed that removes manipulative language and produces neutral summaries.

## Core Promise

- **Neutralization**: Remove manipulative language, produce neutral headlines and summaries
- **Transparency**: Show what was removed and why
- **Deterministic**: Same input = same output, no personalization or trending
- **Calm UX**: No urgency language, no "breaking", no engagement mechanics

## What It Does

1. **Ingest** articles from RSS feeds (AP, Reuters, BBC, NPR)
2. **Neutralize** content by removing:
   - Clickbait ("shocking", "you won't believe")
   - Urgency inflation ("breaking", "just in")
   - Emotional triggers ("slams", "destroys", "furious")
   - Rhetorical framing
3. **Classify** into sections (World, U.S., Local, Business, Technology)
4. **Assemble** deterministic daily briefs

## Tech Stack

- **Framework**: FastAPI (Python 3.11)
- **Database**: PostgreSQL + SQLAlchemy 2.x
- **Migrations**: Alembic
- **Neutralizer**: Pluggable (mock for testing, OpenAI for production)

## API Endpoints

### Public Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/brief` | GET | Get the current daily brief |
| `/v1/stories/{id}` | GET | Get story detail (neutralized content first) |
| `/v1/stories/{id}/transparency` | GET | Get transparency view (what was removed) |

### Admin Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/ingest/run` | POST | Trigger RSS ingestion |
| `/v1/neutralize/run` | POST | Trigger neutralization pipeline |
| `/v1/brief/run` | POST | Trigger brief assembly |

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL
- pipenv

### Installation

```bash
# Clone and install
git clone git@github.com:xbcinc/ntrl-api.git
cd ntrl-api
pipenv install

# Configure
cp .env.example .env
# Edit .env with your database credentials

# Create database and run migrations
createdb ntrl_dev
pipenv run migrate

# Seed sources
pipenv run python scripts/seed_sources.py

# Start server
pipenv run dev
```

### Running the Pipeline

```bash
# 1. Ingest articles from RSS feeds
curl -X POST http://localhost:8000/v1/ingest/run

# 2. Neutralize ingested articles
curl -X POST http://localhost:8000/v1/neutralize/run

# 3. Assemble daily brief
curl -X POST http://localhost:8000/v1/brief/run

# 4. View the brief
curl http://localhost:8000/v1/brief
```

## Example Responses

### GET /v1/brief

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "brief_date": "2024-01-06T00:00:00",
  "cutoff_time": "2024-01-05T00:00:00",
  "assembled_at": "2024-01-06T12:00:00",
  "sections": [
    {
      "name": "world",
      "display_name": "World",
      "order": 0,
      "stories": [
        {
          "id": "story-uuid",
          "neutral_headline": "International leaders meet to discuss trade agreement",
          "neutral_summary": "Representatives from 12 countries convened to negotiate terms of a new trade framework.",
          "source_name": "Associated Press",
          "source_url": "https://apnews.com/article/...",
          "published_at": "2024-01-06T10:00:00",
          "has_manipulative_content": true,
          "position": 0
        }
      ],
      "story_count": 5
    }
  ],
  "total_stories": 25,
  "is_empty": false,
  "empty_message": null
}
```

### GET /v1/stories/{id}

```json
{
  "id": "story-uuid",
  "neutral_headline": "Senator responds to policy criticism",
  "neutral_summary": "The senator addressed concerns raised by opponents regarding the proposed legislation.",
  "what_happened": "The senator addressed concerns raised by opponents.",
  "why_it_matters": null,
  "what_is_known": "The senator addressed concerns raised by opponents regarding the proposed legislation.",
  "what_is_uncertain": "Further details are pending confirmation.",
  "disclosure": "Manipulative language removed.",
  "has_manipulative_content": true,
  "source_name": "Associated Press",
  "source_url": "https://apnews.com/article/...",
  "published_at": "2024-01-06T10:00:00",
  "section": "us"
}
```

### GET /v1/stories/{id}/transparency

```json
{
  "id": "story-uuid",
  "original_title": "SHOCKING: Senator SLAMS critics in furious response",
  "original_description": "You won't believe what happened...",
  "original_body": null,
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
  "has_manipulative_content": true,
  "source_url": "https://apnews.com/article/...",
  "model_name": "mock-v1",
  "prompt_version": "v1",
  "processed_at": "2024-01-06T11:00:00"
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
│   │   └── admin.py         # POST /v1/*/run
│   ├── schemas/             # Pydantic schemas
│   │   ├── brief.py
│   │   ├── stories.py
│   │   └── admin.py
│   └── services/            # Business logic
│       ├── ingestion.py     # RSS ingestion
│       ├── neutralizer.py   # Neutralization pipeline
│       ├── brief_assembly.py # Brief assembly
│       ├── classifier.py    # Section classification
│       └── deduper.py       # Deduplication
├── migrations/              # Alembic migrations
├── scripts/
│   └── seed_sources.py      # Initialize RSS sources
├── tests/                   # Unit and contract tests
├── Pipfile
└── README.md
```

## Configuration

See `.env.example` for all configuration options.

Key settings:
- `DATABASE_URL`: PostgreSQL connection string
- `NEUTRALIZER_PROVIDER`: `mock` (deterministic) or `openai` (LLM-based)
- `ADMIN_API_KEY`: Optional API key for admin endpoints

## Testing

```bash
pipenv install --dev
pipenv run pytest
```

## Design Constraints

### What We Don't Do

- **No engagement**: No likes, saves, shares, reactions, streaks
- **No personalization**: No user accounts, preferences, "for you"
- **No trending**: No popularity signals, viral content
- **No urgency**: No "breaking" alerts, push notifications
- **No fact-checking**: We remove manipulative language, not claims

### Determinism

The same set of stories will always produce the same daily brief:
- Fixed section order (World → U.S. → Local → Business → Technology)
- Time-based ordering within sections (newest first)
- Deterministic tie-breakers (source priority, then ID)

## License

Proprietary
