# NTRL API

Neutral news backend: removes manipulative language, creates calm news briefs.

## Quick Reference

| Resource | Location |
|----------|----------|
| Staging URL | `https://api-staging-7b4d.up.railway.app` |
| Admin Key | `staging-key-123` (header: `X-API-Key`) |
| Dev Server | `pipenv run uvicorn app.main:app --reload --port 8000` |
| Tests | `pipenv run pytest tests/` |
| Unit Tests | `pipenv run pytest tests/unit/` (435 tests) |
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
| QC Gate | <1s | 19 checks per article |
| Brief | ~125ms | Assembly |
| **Total** | **~8.5 min** | vs 9-14 min sequential |

## QC Gate

Runs between NEUTRALIZE and BRIEF ASSEMBLE. Articles must pass **all 19 checks** to appear in the brief. Failed articles are excluded with structured reason codes. Span detection uses **14 manipulation categories** and **8 SpanReason values** (including `selective_quoting` for cherry-picked/scare quotes).

**Implementation**: `app/services/quality_gate.py`

### Checks by Category

| Category | Checks | What They Catch |
|----------|--------|-----------------|
| **Required Fields** (7) | `required_feed_title`, `required_feed_summary`, `required_source`, `required_published_at`, `required_original_url`, `required_feed_category`, `source_name_not_generic` | Missing metadata, generic API source names |
| **Content Quality** (7) | `original_body_complete`, `original_body_sufficient`, `min_body_length`, `feed_title_bounds`, `feed_summary_bounds`, `no_garbled_output`, `no_llm_refusal` | Truncated bodies, paywall snippets, LLM refusals/apologies, placeholder text |
| **Pipeline Integrity** (3) | `neutralization_success`, `not_duplicate`, `url_reachable` | Failed neutralization, duplicate articles, dead URLs (404/410/403) |
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

Railway MCP integration available for deployment operations. See root `CLAUDE.md` for full tool reference.

## Async Pipeline Architecture

Key components: `PipelineJob`, `PipelineJobManager`, `AsyncPipelineOrchestrator`, `CircuitBreaker`. Details: `.claude/reference/async-architecture.md`

## Data Retention System

3-tier system: Active (0-7d), Compliance (7d-12mo), Deleted (>12mo). CLI, API endpoints, and safety features (brief protection, legal hold, dry run). Details: `.claude/reference/data-retention.md`

## Git Workflow

Follow the branch and commit conventions in the root `CLAUDE.md`. Key points for ntrl-api:

- **Branch prefixes**: `feature/`, `fix/`, `docs/`, `refactor/`, `chore/`
- **Conventional commits**: `type: description` format, enforced by `pre-commit` hooks
- **Pre-commit checks**: ruff lint/format, secret detection (`scripts/check-secrets.sh`), private key detection, merge conflict markers, trailing whitespace, YAML validation (excludes `.github/`)
- **CI** (`ci.yml`): ruff check + ruff format --check + pytest (255 unit tests w/ Postgres service container). Uses `NEUTRALIZER_PROVIDER=mock` and `STORAGE_PROVIDER=local` to avoid LLM/S3 costs.
- **Deploy verification** (`deploy-verify.yml`): After push to `main`, waits 120s for Railway, then hits `/health` and `/v1/brief`. Requires `STAGING_API_KEY` GitHub secret.

Install hooks after cloning:
```bash
pipenv install --dev
pipenv run pre-commit install --hook-type pre-commit --hook-type commit-msg
```

## Prompt Architecture

**The `prompts` database table is the source of truth for all LLM prompts, not the hardcoded constants in code.**

| Function | Behavior |
|----------|----------|
| `get_prompt(name, model)` | Checks DB first (60s cache) → falls back to hardcoded constant |
| `get_model_agnostic_prompt(name)` | Same DB-first lookup, ignores model column |
| `PUT /v1/prompts/{name}` | Updates DB prompt, increments version, clears cache |
| Auto-optimization | Writes improved prompts to DB, creates version history |

### Rules

1. **Always update DB prompts via API** after changing hardcoded constants — code changes alone are invisible to production
2. **Keep hardcoded constants in sync** as documentation and fallback, but they are NOT the active prompts
3. **Auto-optimized prompts** (span detection): `high_recall_prompt`, `adversarial_prompt`, `span_detection_prompt`
4. **Manually managed prompts**: `synthesis_detail_full_prompt`, `compression_feed_outputs_prompt`
5. **After prompt changes**: Sync to DB → run eval → verify scores

### Common Trap

Editing hardcoded prompts and seeing tests pass (mock provider) does NOT mean production uses the new prompt. The DB row takes precedence. Always `PUT /v1/prompts/{name}` after code changes.

## Source Health Monitoring

`GET /v1/admin/sources/health` — per-source-type ingestion quality metrics.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `hours` | 24 | Time window to analyze (1-168) |
| `source_type` | all | Filter: `rss`, `perigon`, or `newsdata` |

Returns truncation rates, body sizes, QC pass rates, and auto-generated alerts per source type. Example:
```bash
curl "https://api-staging-7b4d.up.railway.app/v1/admin/sources/health?hours=12&source_type=perigon" \
  -H "X-API-Key: staging-key-123"
```

Alerts trigger when: truncation >20%, QC pass rate <80%, avg body size <1KB, or URL reachability <90%.

## Key Gotchas

- **Spans**: Always reference `original_body`, not `detail_full`
- **Quotes**: Use Unicode escapes (`\u201c`) not literal curly quotes
- **Classification**: 20 domains → 10 feed_categories via `domain_mapper.py`
- **Limits**: Ingest 25, Classify 200, Neutralize 25 (development caps)
- **MockNeutralizerProvider**: Test-only, never production fallback
- **Retention**: Never delete articles in current brief or under legal hold
- **gpt-5-mini temperature**: Does not support `temperature != 1` — omit the parameter entirely
- **`_neutralize_content()` vs `neutralize_story()`**: Both paths must check `detail_full_result.status` for failures

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
