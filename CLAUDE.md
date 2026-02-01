# NTRL API

Neutral news backend: removes manipulative language, creates calm news briefs.

## Quick Reference

| Resource | Location |
|----------|----------|
| Staging URL | `https://api-staging-7b4d.up.railway.app` |
| Admin Key | `staging-key-123` (header: `X-API-Key`) |
| Dev Server | `pipenv run uvicorn app.main:app --reload --port 8000` |
| Tests | `pipenv run pytest tests/` |
| Migrations | `pipenv run alembic upgrade head` |

## Pipeline Overview

```
INGEST → CLASSIFY → NEUTRALIZE → BRIEF ASSEMBLE
```

**Core principle**: Original article body is the single source of truth. All outputs derive from `original_body`.

## Slash Commands

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

## Key Gotchas

- **Spans**: Always reference `original_body`, not `detail_full`
- **Quotes**: Use Unicode escapes (`\u201c`) not literal curly quotes
- **Classification**: 20 domains → 10 feed_categories via `domain_mapper.py`
- **Limits**: Ingest 25, Classify 200, Neutralize 25 (development caps)
- **MockNeutralizerProvider**: Test-only, never production fallback

## Detailed Documentation

| Topic | Location |
|-------|----------|
| Architecture | `docs/claude/architecture.md` |
| Prompts & Spans | `docs/claude/prompts-and-spans.md` |
| Testing | `docs/claude/testing.md` |
| Operations | `docs/claude/operations.md` |
| Evaluation | `docs/claude/evaluation-system.md` |
| Fixes Log | `docs/claude/fixes-log.md` |
| Pipeline Details | `.claude/reference/pipeline-details.md` |

## Full Documentation

| Document | Description |
|----------|-------------|
| `docs/README.md` | Full documentation index (28 docs) |
| `docs/technical/api-reference.md` | All API endpoints |
| `docs/technical/architecture-overview.md` | System architecture |
| `docs/operations/monitoring-runbook.md` | Health monitoring |
