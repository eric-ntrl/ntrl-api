# NTRL API

Neutral news backend: removes manipulative language, creates calm news briefs.

## Quick Reference

| Resource | Location |
|----------|----------|
| Staging URL | `https://api-staging-7b4d.up.railway.app` |
| Admin Key | `staging-key-123` (header: `X-API-Key`) |
| Dev Server | `pipenv run uvicorn app.main:app --reload --port 8000` |
| Tests | `pipenv run pytest tests/` |
| Unit Tests | `pipenv run pytest tests/unit/` (255 tests) |
| E2E Tests | `pipenv run pytest tests/e2e/` (13 tests) |
| Migrations | `pipenv run alembic upgrade head` |

## Pipeline Overview

```
INGEST → CLASSIFY → NEUTRALIZE → QC GATE → BRIEF ASSEMBLE [→ EVALUATE → OPTIMIZE]
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
- **Resilience**: Circuit breaker, retry with backoff, rate limiting

### Performance (Verified)

| Stage | Duration | Notes |
|-------|----------|-------|
| Ingest | ~20s | Parallel RSS fetches |
| Classify | ~2.5 min | LLM classification |
| Neutralize | ~5.5 min | LLM neutralization |
| QC Gate | <1s | 18 checks per article |
| Brief | ~125ms | Assembly |
| **Total** | **~8.5 min** | vs 9-14 min sequential |

## QC Gate

Runs between NEUTRALIZE and BRIEF ASSEMBLE. Articles must pass **all 18 checks** to appear in the brief. Failed articles are excluded with structured reason codes.

**Implementation**: `app/services/quality_gate.py`

### Checks by Category

| Category | Checks | What They Catch |
|----------|--------|-----------------|
| **Required Fields** (7) | `required_feed_title`, `required_feed_summary`, `required_source`, `required_published_at`, `required_original_url`, `required_feed_category`, `source_name_not_generic` | Missing metadata, generic API source names |
| **Content Quality** (7) | `original_body_complete`, `original_body_sufficient`, `min_body_length`, `feed_title_bounds`, `feed_summary_bounds`, `no_garbled_output`, `no_llm_refusal` | Truncated bodies, paywall snippets, LLM refusals/apologies, placeholder text |
| **Pipeline Integrity** (2) | `neutralization_success`, `not_duplicate` | Failed neutralization, duplicate articles |
| **View Completeness** (2) | `views_renderable`, `brief_full_different` | Blank detail views, missing disclosure text, identical brief/full tabs |

### Key Design Decisions

- `min_body_length` uses **AND logic**: both `detail_brief` AND `detail_full` must meet minimums
- `no_llm_refusal` patterns are **anchored to start** of text to avoid false positives from articles quoting AI
- `original_body_sufficient` uses `raw_content_size` column as a proxy (no S3 download needed)
- `original_body_complete` checks the `body_is_truncated` flag set during ingestion

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

## Async Pipeline Architecture

Key components:

| Component | Location | Purpose |
|-----------|----------|---------|
| `PipelineJob` | `app/models.py` | Job state persistence |
| `PipelineJobManager` | `app/services/pipeline_job_manager.py` | Job lifecycle |
| `AsyncPipelineOrchestrator` | `app/services/async_pipeline_orchestrator.py` | Stage execution |
| `CircuitBreaker` | `app/services/resilience.py` | Failure protection |
| `PipelineLogger` | `app/logging_config.py` | Structured JSON logging |

### Alerts

| Alert Code | Threshold | Trigger |
|------------|-----------|---------|
| `llm_latency_high` | >5s avg | LLM calls slow |
| `pipeline_duration_high` | >10 min | Pipeline too slow |
| `token_usage_high` | >500k tokens | Cost concern |

## Data Retention System

3-tier retention system for compliance and clean development iteration:

| Tier | Window | Description |
|------|--------|-------------|
| **Active** | 0-7 days | Full access, all features work |
| **Compliance** | 7d-12mo | Metadata + neutralized content retained |
| **Deleted** | >12mo | Permanent removal |

### Retention CLI

```bash
# Check current status
pipenv run python -m app.cli.retention status

# Preview what would be purged
pipenv run python -m app.cli.retention purge --dry-run

# Development mode purge (hard delete)
pipenv run python -m app.cli.retention purge --dev --days 3 --confirm

# Switch retention policy
pipenv run python -m app.cli.retention set-policy production
```

### Retention API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/admin/retention/status` | GET | Current retention stats |
| `/v1/admin/retention/policy` | GET/PUT | View/update policy |
| `/v1/admin/retention/purge` | POST | Trigger purge (requires confirm) |
| `/v1/admin/retention/dry-run` | POST | Preview purge |

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `RetentionPolicy` | `app/models.py` | Configurable retention windows |
| `ContentLifecycleEvent` | `app/models.py` | Immutable audit trail |
| `policy_service` | `app/services/retention/` | Policy CRUD |
| `archive_service` | `app/services/retention/` | Tier transitions |
| `purge_service` | `app/services/retention/` | FK-safe deletion |

### Safety Features

- **Brief protection**: Never deletes articles in current brief
- **Legal hold**: Stories with `legal_hold=True` cannot be deleted
- **Soft delete grace**: 24-hour window before hard delete
- **Dry run**: Preview before executing any purge

## Git Workflow

Follow the branch and commit conventions in the root `CLAUDE.md`. Key points for ntrl-api:

- **Branch prefixes**: `feature/`, `fix/`, `docs/`, `refactor/`, `chore/`
- **Conventional commits**: `type: description` format, enforced by `pre-commit` hooks
- **Pre-commit checks**: `ruff` linting/formatting + secret detection, runs on every commit
- **CI**: GitHub Actions runs `ruff check` + `pytest` on every PR to `main`
- **Deploy verification**: After merge to `main`, `deploy-verify.yml` checks Railway health

Install hooks after cloning: `pipenv install --dev && pipenv run pre-commit install --hook-type pre-commit --hook-type commit-msg`

## Key Gotchas

- **Spans**: Always reference `original_body`, not `detail_full`
- **Quotes**: Use Unicode escapes (`\u201c`) not literal curly quotes
- **Classification**: 20 domains → 10 feed_categories via `domain_mapper.py`
- **Limits**: Ingest 25, Classify 200, Neutralize 25 (development caps)
- **MockNeutralizerProvider**: Test-only, never production fallback
- **Retention**: Never delete articles in current brief or under legal hold

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

## Architecture Diagrams

Visual documentation for complex flows:

| Diagram | Location | Description |
|---------|----------|-------------|
| Async Pipeline States | `docs/async-pipeline-states.md` | Job state machine, transitions, cancellation flow |
| NTRL Filter v2 Pipeline | `docs/ntrl-filter-v2-pipeline.md` | Detection + fix phases, parallel execution |
| Article Content Fields | `docs/article-content-fields.md` | Data flow from source to app tabs |

## Full Documentation

| Document | Description |
|----------|-------------|
| `docs/README.md` | Full documentation index (28 docs) |
| `docs/technical/api-reference.md` | All API endpoints |
| `docs/technical/architecture-overview.md` | System architecture |
| `docs/operations/monitoring-runbook.md` | Health monitoring |
