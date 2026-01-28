# NTRL Claude Code Development Guide

> Last updated: January 2026
> Purpose: Reference guide for AI-assisted development with Claude Code on the NTRL project.
> Audience: The developer (Eric) and any Claude Code session working on NTRL.

---

## 1. Project Context Files

NTRL maintains detailed context files that Claude Code reads automatically. Always ensure these are up to date.

| File | Location | Purpose | Size |
|------|----------|---------|------|
| **Backend CLAUDE.md** | `code/ntrl-api/CLAUDE.md` | Full backend reference — architecture, API routes, pipeline, database schema, testing, deployment | ~928 lines |
| **Frontend CLAUDE.md** | `code/ntrl-app/CLAUDE.md` | Full frontend reference — screens, components, navigation, theming, testing | ~373 lines |
| **AGENTS.md** | Repository root | Repository-level guidelines and conventions for AI agents | Varies |

**Best practice:** If a Claude Code session produces incorrect output, check whether the CLAUDE.md files need updating. Outdated context files are the most common source of incorrect AI-generated code.

---

## 2. Key Conventions

### Backend (ntrl-api)

| Convention | Detail |
|------------|--------|
| Language | Python 3.11+ |
| Framework | FastAPI |
| ORM | SQLAlchemy (async) |
| Package manager | pipenv |
| Naming | snake_case for everything (variables, functions, files, modules) |
| Database | PostgreSQL (Railway-managed) |
| Migrations | Alembic |
| Object storage | AWS S3 (article bodies) |
| LLM providers | OpenAI (primary, gpt-4o-mini), Google Gemini (fallback) |
| Deployment | Railway |
| Pipeline schedule | Cron: `0 */4 * * *` (every 4 hours) |

### Frontend (ntrl-app)

| Convention | Detail |
|------------|--------|
| Language | TypeScript |
| Framework | React Native |
| Build system | Expo |
| Package manager | npm |
| Formatting | Prettier |
| Linting | ESLint |
| Testing | Jest (unit), Playwright (E2E, UI capture) |
| Navigation | React Navigation |
| State management | React Query / context |

### CRITICAL Rules — Must Follow

These are the most common mistakes made in Claude Code sessions on NTRL. Violating these wastes significant time.

#### 1. Dark Mode Support — ALWAYS use useTheme() hook

**NEVER** use static/hardcoded colors in any component. NTRL supports dark mode, and every color must come from the theme.

```typescript
// WRONG - will break in dark mode
const styles = StyleSheet.create({
  container: { backgroundColor: '#FFFFFF' },
  text: { color: '#000000' },
});

// CORRECT - respects theme
const { colors } = useTheme();
const styles = StyleSheet.create({
  container: { backgroundColor: colors.background },
  text: { color: colors.text },
});
```

Every new component and every modified component must use `useTheme()`. No exceptions.

#### 2. Screen Names — Use the Correct Names

NTRL uses specific screen names. Using wrong names breaks navigation and confuses the codebase.

| Correct Name | WRONG Names (Do Not Use) |
|-------------|--------------------------|
| **TodayScreen** | FeedScreen, HomeScreen, MainScreen |
| **SectionsScreen** | CategoriesScreen, TopicsScreen, BrowseScreen |
| **ArticleDetailScreen** | ArticleScreen, StoryScreen, DetailScreen |
| **NtrlContent** | RedlineScreen, ComparisonScreen, DiffScreen |

#### 3. Pipeline is 4 Stages, Not 3

The NTRL pipeline has exactly **4 stages**:

```
INGEST → CLASSIFY → NEUTRALIZE → BRIEF ASSEMBLE
```

- **INGEST:** Fetch RSS feeds, scrape article bodies, store in S3
- **CLASSIFY:** Detect manipulation spans using gpt-4o-mini (14 categories)
- **NEUTRALIZE:** Rewrite manipulative sentences to be neutral
- **BRIEF ASSEMBLE:** Compile neutralized articles into per-category briefings

Do NOT describe this as a 3-stage pipeline. Do NOT omit BRIEF ASSEMBLE. Do NOT combine CLASSIFY and NEUTRALIZE into one stage.

#### 4. 10 Feed Categories, Not 5

NTRL has exactly **10 feed categories**:

1. Top Stories
2. U.S.
3. World
4. Business
5. Technology
6. Science
7. Health
8. Sports
9. Entertainment
10. Environment

Do NOT describe this as "5 categories" or list only a subset.

#### 5. 14 Manipulation Categories

The classification stage detects **14 categories** of manipulative language. Always reference this as "14 categories" — not "several," not "multiple," not a different number.

---

## 3. Common Tasks

### Prompt Changes (Neutralizer / Classifier)

This is the most frequent development task. When modifying prompts:

1. **Edit the prompt** — Modify the relevant prompt in the backend code.
2. **Deploy** — Push to Railway staging.
3. **Re-neutralize** — Trigger re-neutralization for test articles:
   ```
   POST /v1/neutralize/run
   Body: { "story_ids": [1, 2, 3, 4, 5], "force": true }
   ```
4. **Rebuild brief** — After neutralization completes:
   ```
   POST /v1/brief/run
   ```
5. **Review output** — Check neutralized articles and brief content for quality.

**Cost-saving tip:** Use `story_ids` to target 5-10 specific articles rather than re-neutralizing the entire corpus. Each full pipeline run processes hundreds of articles and incurs API costs.

### UI Changes

1. **Edit the component** — Modify the relevant `.tsx` file.
2. **Test locally** — `npx expo start` and test on simulator/device.
3. **Verify dark mode** — Test in both light and dark mode. Use `useTheme()` for all colors.
4. **Run Playwright** — Use Playwright capture scripts for visual regression testing.
5. **Run linter** — `npm run lint` to ensure code quality.

### Adding RSS Sources

Add a new source via the API:

```
POST /v1/sources
Body: {
  "name": "Source Name",
  "feed_url": "https://example.com/rss",
  "category": "technology",
  "active": true
}
```

After adding, monitor the next pipeline run to confirm the source is ingested correctly.

### Database Migrations

Alembic is used for database migrations. Follow this exact sequence:

```bash
# 1. Create migration
pipenv run alembic revision --autogenerate -m "description of change"

# 2. VERIFY single head (critical!)
pipenv run alembic heads
# Must show exactly ONE head. Multiple heads = crash on deploy.

# 3. Apply migration
pipenv run alembic upgrade head

# 4. Verify
pipenv run alembic current
```

**CRITICAL:** Alembic must maintain a single head at all times. Multiple heads cause a crash on Railway deployment. If multiple heads exist, they must be linearized before deploying. This was a known crash cause fixed in January 2026.

---

## 4. Testing Workflow

### Backend Testing

```bash
cd code/ntrl-api
pipenv run pytest
```

**Known:** There are 6 expected test failures related to MockNeutralizerProvider limitations. These are documented and acceptable — MockNeutralizerProvider achieves only ~5% precision (it is for testing pipeline flow, not output quality).

To run specific tests:
```bash
pipenv run pytest tests/test_neutralizer.py -v
pipenv run pytest tests/test_pipeline.py -k "test_classify" -v
```

### Frontend Testing

```bash
cd code/ntrl-app

# Unit tests
npm test

# E2E tests
npm run e2e

# Lint
npm run lint
```

### UI Visual Testing

**Playwright is recommended over Maestro** for UI capture and visual testing. Playwright capture scripts provide more reliable and reproducible results.

```bash
# Run Playwright capture
npx playwright test --project=mobile-capture
```

### Debug Endpoints

Use these endpoints to debug pipeline issues without running full pipeline:

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/stories/{id}/debug` | Full debug info for a specific article |
| `GET /v1/stories/{id}/debug/spans` | Span detection trace showing classification decisions |
| `GET /v1/status` | Pipeline status, last run times, alert flags |

---

## 5. Cost-Efficient Development

OpenAI API calls cost money. Be deliberate about when and how much you process.

### Use story_ids for Targeted Work

When testing prompt changes, never re-neutralize the entire database. Pick 5-10 representative articles:

```
POST /v1/neutralize/run
Body: { "story_ids": [42, 87, 123, 256, 301], "force": true }
```

Choose articles that represent:
- Different sources (AP wire vs. Daily Mail tabloid)
- Different manipulation levels (low, medium, high)
- Different lengths (short, medium, long)
- Different categories

### Test via Debug Endpoints First

Before triggering a full re-neutralization:
1. Use `GET /v1/stories/{id}/debug/spans` to see how the classifier handles an article.
2. Review the spans and categories detected.
3. Only re-neutralize if the classification looks correct and you want to see the full output.

### Avoid Unnecessary Full Pipeline Runs

A full pipeline run (POST /v1/pipeline/scheduled-run) processes all sources and all articles. This is appropriate for production cron but rarely needed during development. Use targeted endpoints instead.

---

## 6. Known Pitfalls

### MockNeutralizerProvider is Testing Only

The MockNeutralizerProvider exists for testing pipeline flow without making real API calls. It achieves approximately **5% precision** — its output is intentionally low-quality. Never evaluate neutralization quality using mock output. Always use the real OpenAI-backed provider for quality assessment.

### Unicode Escapes for Quote Characters

When working with prompts or text processing that involves quotation marks, use Unicode escape sequences rather than literal quote characters. Literal quotes can break JSON serialization and prompt formatting.

```python
# WRONG
prompt = 'Rewrite the sentence "example" to be neutral'

# CORRECT
prompt = 'Rewrite the sentence \u201cexample\u201d to be neutral'
```

### Alembic Must Maintain Single Head

If you see an error like `Multiple heads detected` during deployment:
1. Run `pipenv run alembic heads` to see all heads.
2. Create a merge migration: `pipenv run alembic merge heads -m "merge branches"`
3. Verify single head: `pipenv run alembic heads` should show exactly one.
4. Apply: `pipenv run alembic upgrade head`

This was a production crash cause in January 2026 and has been resolved, but vigilance is needed on every migration.

### 6 Expected Test Failures

When running the full test suite, 6 tests are expected to fail due to MockNeutralizerProvider limitations. These are:
- Tests that validate neutralization output quality (mock does not produce quality output)
- Tests are documented in the test files with comments explaining the expected failure

Do NOT spend time trying to fix these unless you are replacing MockNeutralizerProvider with a better test double.

### Long Article Limitation

Articles over ~8,000 characters may not be fully neutralized due to LLM context window constraints. Highlights may be missing from the tail end of long articles. Chunked processing is planned for Phase 2.

---

## 7. Development Environment Setup

### Backend

```bash
cd code/ntrl-api
pipenv install --dev
pipenv shell

# Environment variables needed (in .env):
# DATABASE_URL=postgresql://...
# OPENAI_API_KEY=sk-...
# GEMINI_API_KEY=...
# AWS_ACCESS_KEY_ID=...
# AWS_SECRET_ACCESS_KEY=...
# S3_BUCKET_NAME=...

# Run locally
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd code/ntrl-app
npm install

# Start Expo dev server
npx expo start

# iOS simulator
npx expo run:ios

# Android emulator
npx expo run:android
```

---

## 8. Deployment

### Backend (Railway)

- **Staging:** Automatic deploy on push to staging branch (or manual via Railway dashboard).
- **Production:** [TBD — not yet configured].
- **Rollback:** Use Railway dashboard to redeploy a previous build.
- **Logs:** Available in Railway dashboard, real-time streaming.
- **Cron:** Pipeline scheduled run configured as Railway cron job: `0 */4 * * *`.

### Frontend (Expo)

- **Development:** `npx expo start` for local dev server.
- **TestFlight/Play Store:** Build via Expo EAS: `eas build --platform ios` / `eas build --platform android`.
- **OTA Updates:** Expo supports over-the-air updates for JS bundle changes (no App Store review needed for minor fixes).

---

## 9. Quick Reference

| What | Command / Location |
|------|--------------------|
| Start backend | `cd code/ntrl-api && pipenv run uvicorn app.main:app --reload` |
| Start frontend | `cd code/ntrl-app && npx expo start` |
| Run backend tests | `cd code/ntrl-api && pipenv run pytest` |
| Run frontend tests | `cd code/ntrl-app && npm test` |
| Run E2E tests | `cd code/ntrl-app && npm run e2e` |
| Pipeline status | `GET /v1/status` |
| Debug article | `GET /v1/stories/{id}/debug` |
| Debug spans | `GET /v1/stories/{id}/debug/spans` |
| Trigger pipeline | `POST /v1/pipeline/scheduled-run` |
| Re-neutralize specific | `POST /v1/neutralize/run` with `story_ids` |
| Rebuild brief | `POST /v1/brief/run` |
| Add source | `POST /v1/sources` |
| Backend context | `code/ntrl-api/CLAUDE.md` |
| Frontend context | `code/ntrl-app/CLAUDE.md` |
| Agent guidelines | `AGENTS.md` |
