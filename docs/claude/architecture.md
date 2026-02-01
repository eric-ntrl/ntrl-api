# Architecture Quick Reference

> Quick reference for Claude Code. Full details in `../technical/architecture-overview.md`.

## Core Principle

**The original article body is the single source of truth.**

All user-facing outputs derive from `original_body`, not RSS metadata.

## 4-Stage Pipeline

```
INGEST → CLASSIFY → NEUTRALIZE → BRIEF ASSEMBLE
```

| Stage | Input | Output | Key Service |
|-------|-------|--------|-------------|
| INGEST | RSS feeds | StoryRaw + S3 body.txt | `ingestion.py` |
| CLASSIFY | body.txt (2000 chars) | domain, feed_category, tags | `llm_classifier.py` |
| NEUTRALIZE | body.txt (full) | 6 outputs + spans | `neutralizer/__init__.py` |
| BRIEF | Neutralized stories | DailyBrief | `brief_assembly.py` |

## Tech Stack

| Layer | Technology |
|-------|------------|
| Framework | FastAPI + Uvicorn |
| Language | Python 3.11 |
| ORM | SQLAlchemy |
| Database | PostgreSQL (Railway) |
| Object Storage | AWS S3 (`ntrl-raw-content`) |
| LLM Primary | gpt-4o-mini (OpenAI) |
| LLM Fallback | gemini-2.0-flash (Google) |

## Classification

- **20 domains** → mapped to **10 feed_categories** via `domain_mapper.py`
- Reliability chain: gpt-4o-mini → simplified prompt → gemini → keyword fallback
- Keyword fallback should be <1% of articles

## 10 Feed Categories (display order)

1. World, 2. U.S., 3. Local, 4. Business, 5. Technology
6. Science, 7. Health, 8. Environment, 9. Sports, 10. Culture

## 6 Neutralization Outputs

| Output | Purpose |
|--------|---------|
| `feed_title` | Short headline for cards |
| `feed_summary` | 1-2 sentence summary |
| `detail_title` | Full headline |
| `detail_brief` | 3-5 paragraph brief |
| `detail_full` | Full neutralized article |
| `spans` | Manipulative phrase annotations |

## Neutralization Status

| Status | Meaning |
|--------|---------|
| `success` | Displayed to users |
| `failed_llm` | LLM API failed |
| `failed_garbled` | Output unreadable |
| `failed_audit` | Failed quality check |
| `skipped` | Not processed |

## Key Files

```
app/
├── main.py                   # FastAPI entry point
├── services/
│   ├── ingestion.py          # RSS ingestion
│   ├── llm_classifier.py     # Article classification
│   ├── domain_mapper.py      # Domain → feed_category
│   ├── neutralizer/
│   │   ├── __init__.py       # Main neutralizer
│   │   ├── spans.py          # Span detection
│   │   └── providers/        # LLM providers
│   └── brief_assembly.py     # Brief generation
└── models.py                 # SQLAlchemy models
```

## See Also

- `../technical/architecture-overview.md` — Full system architecture
- `../technical/api-reference.md` — All API endpoints
- `../technical/data-model.md` — Database schema
