# NTRL API

Neutral news backend: removes manipulative language, creates calm news briefs.

## Architecture Principle

**The original article body is the single source of truth.**

```
INGEST → CLASSIFY → NEUTRALIZE → BRIEF ASSEMBLE
```

- RSS title/description stored for audit, NOT used for neutralization
- Spans reference `original_body` positions (not `detail_full`)
- LLM synthesis preferred over in-place filtering (LLMs can't track char positions)

## Commands

```bash
pipenv run uvicorn app.main:app --reload --port 8000  # Dev server
pipenv run pytest tests/                               # Run tests
pipenv run alembic upgrade head                        # Migrations
```

## Claude Slash Commands

| Command | Purpose |
|---------|---------|
| `/status` | Check API health |
| `/evaluate` | Run teacher LLM evaluation |
| `/prompt` | View/update pipeline prompts |
| `/classify` | Run classification batch |
| `/neutralize` | Re-neutralize articles |
| `/brief` | Check brief sections |
| `/pipeline` | Run full pipeline |
| `/debug-spans` | Debug span detection |
| `/check-spans` | Check span reasons |

**After prompt changes**: `/classify force` → `/brief rebuild` → `/evaluate`

## Staging Environment

- **URL**: `https://api-staging-7b4d.up.railway.app`
- **Admin key**: `staging-key-123` (header: `X-API-Key`)
- Deploys from `main` on push (~2 min)

## Development Limits (IMPORTANT)

- Ingest: 25 articles max
- Classify: 200 articles max
- Neutralize: 25 articles max
- Articles hidden after 24 hours

## Key Gotchas

### Spans
- Spans ALWAYS reference `original_body`, not `detail_full`
- LLMs are bad at character counting — use synthesis mode
- Quote filtering uses Unicode escapes (`\u201c`) not literals

### Classification
- 20 domains → 10 feed_categories via `domain_mapper.py`
- gpt-4o-mini primary, gemini-2.0-flash fallback, keyword last resort
- Alert fires if keyword fallback >1%

### Prompts
- Stored in DB with version history
- Hot-reload on change (no deploy needed)
- Auto-optimize via `/evaluate auto-optimize`

### Neutralization Status
- `success`, `failed_llm`, `failed_garbled` tracked per article
- Only `success` articles appear in brief/stories
- MockNeutralizerProvider is test-only, never production fallback

### Text Limits
- Constraints are in backend prompts, not frontend CSS
- Ask LLM for 10-15% less than limit (they overcount)

## Detailed Reference

For detailed docs, see:
- @docs/README.md — Full documentation index
- @docs/technical/api-reference.md — All endpoints
- @docs/technical/architecture-overview.md — System architecture
- @.claude/reference/pipeline-details.md — Classification, neutralization, span detection details
