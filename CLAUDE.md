# NTRL API

Neutral news backend: removes manipulative language, creates calm news briefs.

## Quick Reference

| Resource | Location |
|----------|----------|
| Staging URL | `https://api-staging-7b4d.up.railway.app` |
| Admin Key | `$ADMIN_API_KEY` (header: `X-API-Key`) |
| Dev Server | `pipenv run uvicorn app.main:app --reload --port 8000` |
| Tests | `pipenv run pytest tests/unit/` (562 tests) |
| Migrations | `pipenv run alembic upgrade head` |

## Pipeline

```
INGEST → CLASSIFY → NEUTRALIZE → QC GATE → BRIEF ASSEMBLE → URL VALIDATE [→ EVALUATE → OPTIMIZE]
```

**Core principle**: Original article body is the single source of truth. All outputs derive from `original_body`.

Async pipeline: `POST /v1/pipeline/scheduled-run-async` (returns 202). Endpoints: `.claude/reference/async-architecture.md`

## QC Gate

21 checks between NEUTRALIZE and BRIEF ASSEMBLE. Articles must pass all to appear in the brief. Full check listing and source filtering details: `.claude/reference/qc-gate-details.md`

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

## Prompt Architecture (CRITICAL)

**The `prompts` database table is the source of truth**, not hardcoded constants.

- `get_prompt(name, model)` checks DB first (60s cache) → falls back to hardcoded
- `PUT /v1/prompts/{name}` updates DB, increments version, clears cache
- **Auto-optimized**: `high_recall_prompt`, `adversarial_prompt`, `span_detection_prompt`, `classification_system_prompt`
- **Manual only**: `synthesis_detail_full_prompt`, `compression_feed_outputs_prompt`
- **Trap**: Editing hardcoded prompts + tests pass (mock) ≠ production uses new prompt. Always sync via API.

## Key Gotchas

- **Spans**: Always reference `original_body`, not `detail_full`
- **Quotes**: Use Unicode escapes (`\u201c`) not literal curly quotes
- **Classification**: 20 domains → 10 feed_categories via `domain_mapper.py`. Perigon articles bypass LLM via `api_categories`.
- **Limits**: Ingest 25, Classify 200, Neutralize 25 (development caps)
- **gpt-5-mini temperature**: Does not support `temperature != 1` — omit entirely
- **`_neutralize_content()` vs `neutralize_story()`**: Both must check `detail_full_result.status`
- **Retention**: Never delete articles in current brief or under legal hold

## Git Workflow

Follow root `CLAUDE.md` conventions. CI (`ci.yml`): ruff + pytest (562 tests w/ Postgres). Uses `NEUTRALIZER_PROVIDER=mock` and `STORAGE_PROVIDER=local`.

## Documentation Index

| Topic | Location |
|-------|----------|
| QC Gate Details | `.claude/reference/qc-gate-details.md` |
| Deploy Guide | `.claude/reference/deploy-guide.md` |
| Async Architecture | `.claude/reference/async-architecture.md` |
| Data Retention | `.claude/reference/data-retention.md` |
| Pipeline Details | `.claude/reference/pipeline-details.md` |
| Full Docs Index | `docs/README.md` (28 docs) |
