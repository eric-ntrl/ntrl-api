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
INGEST → CLASSIFY → NEUTRALIZE → BRIEF ASSEMBLE [→ EVALUATE → OPTIMIZE]
```

**Core principle**: Original article body is the single source of truth. All outputs derive from `original_body`.

## Async Pipeline (Recommended for Production)

The pipeline now supports async execution via background jobs to avoid HTTP timeouts:

| Endpoint | Purpose |
|----------|---------|
| `POST /v1/pipeline/scheduled-run-async` | Start async job (returns 202 immediately) |
| `GET /v1/pipeline/jobs/{id}` | Check job status and progress |
| `GET /v1/pipeline/jobs/{id}/stream` | SSE stream of job progress |
| `POST /v1/pipeline/jobs/{id}/cancel` | Cancel a running job |
| `GET /v1/pipeline/jobs` | List recent jobs |

### Running Async Pipeline

```bash
# Start job (returns immediately with job_id)
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run-async" \
  -H "X-API-Key: staging-key-123" \
  -H "Content-Type: application/json" \
  -d '{"enable_evaluation": true}'

# Poll status
curl "https://api-staging-7b4d.up.railway.app/v1/pipeline/jobs/{job_id}" \
  -H "X-API-Key: staging-key-123"
```

### Key Benefits

- **No timeouts**: Returns 202 immediately, processes in background
- **Progress tracking**: Real-time stage progress via polling or SSE
- **Cancellation**: Can cancel running jobs gracefully
- **Parallel execution**: Stages run with internal parallelism for speed

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

## Railway MCP Tools

Native Railway integration available via MCP:

| Tool | Purpose |
|------|---------|
| `railway_status` | Get service status and deploy state |
| `railway_logs` | Fetch logs (with optional filter) |
| `railway_deploys` | List recent deployments |
| `railway_deploy_wait` | Wait for deploy to complete |
| `railway_deploy_verify` | Wait + smoke test endpoints |
| `railway_env_get/set` | Manage environment variables |
| `railway_restart` | Restart the service |

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
