# NTRL Onboarding Guide

*Last updated: January 2026*

---

## Welcome to NTRL

NTRL is a news platform that strips manipulative language from journalism and delivers neutralized, fact-forward briefings to readers. Our pipeline ingests articles from RSS feeds, classifies them by topic, neutralizes bias and sensationalism using LLMs, and assembles a daily brief organized into 10 editorial sections.

This guide will walk you through your first three days: getting the project running locally, understanding the architecture, and writing your first code.

---

## Day 1: Environment Setup

### 1. Clone the Repository

```bash
git clone [repository-url]
cd NTRL
```

The project is organized as follows:

```
NTRL/
├── code/
│   ├── ntrl-api/     # FastAPI backend (Python 3.11)
│   └── ntrl-app/     # React Native/Expo app (TypeScript)
├── docs/             # Documentation (you are here)
├── brand/            # Brand PDFs (6 files)
├── AGENTS.md         # Repository guidelines
└── NTRL_Canonical_Documents_Master_v1.0/  # Historical PDFs
```

### 2. Set Up the Backend (`code/ntrl-api/`)

**Prerequisites:**
- Python 3.11+
- PostgreSQL (running locally)
- pipenv (`pip install pipenv`)

**Steps:**

```bash
cd code/ntrl-api

# Install dependencies
pipenv install

# Copy environment config
cp .env.example .env

# Create the development database
createdb ntrl_dev

# Run migrations
pipenv run alembic upgrade head

# Start the server
pipenv run dev
# (or explicitly: pipenv run uvicorn app.main:app --reload --port 8000)
```

The API will be available at http://localhost:8000. Open http://localhost:8000/docs for the interactive Swagger UI.

### 3. Set Up the Frontend (`code/ntrl-app/`)

**Prerequisites:**
- Node.js 18+
- npm
- Expo CLI
- iOS Simulator (macOS) or Android Emulator

**Steps:**

```bash
cd code/ntrl-app

# Install dependencies
npm install

# Start Expo dev server
npm start
```

From the Expo CLI menu:
- Press `i` to open the iOS simulator
- Press `a` to open Android emulator
- Press `w` to open in the web browser

You can also run platform-specific commands directly:

```bash
npm run ios       # Launch iOS simulator
npm run android   # Launch Android emulator
npm run web       # Open in browser
```

---

## Day 1: Key Documentation to Read

Before diving into code, read these documents in order:

| Priority | Document | Location | What You'll Learn |
|----------|----------|----------|-------------------|
| 1 | Repository Guidelines | `AGENTS.md` | Coding conventions, branch naming, commit rules |
| 2 | Brand Canon | `brand/NTRL_Brand_and_Product_Canon_v1.0.pdf` | What NTRL is, brand voice, product mission |
| 3 | Backend Reference | `code/ntrl-api/CLAUDE.md` | Full backend architecture, models, services |
| 4 | Frontend Reference | `code/ntrl-app/CLAUDE.md` | Full frontend architecture, components, navigation |
| 5 | Documentation Index | `docs/README.md` | Map of all project documentation |

Budget about 90 minutes to read through these. They are the single best way to get productive quickly.

---

## Day 2: Understanding the Architecture

### The 4-Stage Pipeline

NTRL processes news through four sequential stages. Each stage can be triggered independently via admin API endpoints.

```
INGEST --> CLASSIFY --> NEUTRALIZE --> BRIEF ASSEMBLE
```

#### Stage 1: INGEST (`app/services/ingestion.py`)

Pulls articles from configured RSS feeds, extracts the article body text, and stores:
- **Metadata** (title, source, URL, publish date) in PostgreSQL
- **Raw body text** (`body.txt`) in S3 (production) or local filesystem (development)

#### Stage 2: CLASSIFY (`app/services/llm_classifier.py`)

Reads `body.txt` for each ingested article and assigns:
- **Domain** (one of 20 fine-grained domains)
- **Feed category** (one of 10 editorial sections -- see below)
- **Tags** (freeform topic tags)

Classification uses a cascade strategy: `gpt-4o-mini` first, then `gemini-2.0-flash` as fallback, then keyword-based fallback if both LLMs fail.

#### Stage 3: NEUTRALIZE (`app/services/neutralizer/`)

Reads `body.txt` and generates **all** neutralized outputs in one pass:
- `feed_title` -- headline for the section feed
- `feed_summary` -- 1-2 sentence summary for the section feed
- `detail_title` -- headline for the article detail view
- `detail_brief` -- concise briefing (the "Brief" tab)
- `detail_full` -- full neutralized article (the "Full" tab)
- `spans` -- transparency annotations showing what was changed and why

Note: The neutralizer is a **module directory** (`app/services/neutralizer/`) with a `providers/` subdirectory for different LLM backends (OpenAI, mock, etc.).

#### Stage 4: BRIEF ASSEMBLE (`app/services/brief_assembly.py`)

Groups neutralized articles by their feed category (10 categories) and builds a `DailyBrief` object with sections in a fixed editorial order.

### The 10 Feed Categories

The brief is organized into these sections, always in this order:

1. World
2. U.S.
3. Local
4. Business
5. Technology
6. Science
7. Health
8. Environment
9. Sports
10. Culture

### Frontend Architecture -- Current Screens

The app is built with React Native and Expo. Here are the active screens:

| Screen | File | Purpose |
|--------|------|---------|
| Today | `src/screens/TodayScreen.tsx` | Session-filtered articles, main landing screen |
| Sections | `src/screens/SectionsScreen.tsx` | Browse all 10 category sections |
| Article Detail | `src/screens/ArticleDetailScreen.tsx` | Read an article with Brief / Full / Ntrl tabs |
| Profile | `src/screens/ProfileScreen.tsx` | User content preferences and saved topics |
| Settings | `src/screens/SettingsScreen.tsx` | Text size, appearance, and app preferences |
| Search | `src/screens/SearchScreen.tsx` | Search for articles |

There is also one important component that is **not** a screen:

| Component | File | Purpose |
|-----------|------|---------|
| NtrlContent | `src/components/NtrlContent.tsx` | Inline transparency view (rendered within ArticleDetailScreen, not a separate screen) |

**DEPRECATED -- do NOT reference these in new code or documentation:**
- `FeedScreen` (replaced by TodayScreen and SectionsScreen)
- `RedlineScreen` (replaced by NtrlContent inline component)
- `NtrlViewScreen` (dead code, never shipped)

### Key API Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/v1/brief` | GET | No | Get the daily brief |
| `/v1/stories/{id}` | GET | No | Get a single story's detail |
| `/v1/stories/{id}/transparency` | GET | No | Get transparency/span data |
| `/v1/stories/{id}/debug` | GET | No | Debug story content |
| `/v1/stories/{id}/debug/spans` | GET | No | Debug span detection |
| `/v1/sources` | GET | No | List all configured sources |
| `/v1/sources` | POST | No | Add a new RSS source |
| `/v1/ingest/run` | POST | Admin | Trigger RSS ingestion |
| `/v1/classify/run` | POST | Admin | Trigger classification |
| `/v1/neutralize/run` | POST | Admin | Trigger neutralization |
| `/v1/brief/run` | POST | Admin | Trigger brief assembly |
| `/v1/pipeline/run` | POST | Admin | Run the full 4-stage pipeline |
| `/v1/pipeline/scheduled-run` | POST | Admin | Scheduled pipeline run (Railway cron) |
| `/v1/status` | GET | Admin | System status and health |
| `/v1/prompts` | GET/PUT | Admin | View and update LLM prompts |

**Admin endpoints** require the `X-API-Key` header. See the Environment Variables section for the key values.

---

## Day 2: Try the Full Pipeline

With the backend running locally, walk through all four stages:

```bash
# Stage 1: Ingest articles from RSS feeds
curl -X POST "http://localhost:8000/v1/ingest/run" \
  -H "X-API-Key: staging-key-123"

# Stage 2: Classify the ingested articles
curl -X POST "http://localhost:8000/v1/classify/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"limit": 25}'

# Stage 3: Neutralize the classified articles
curl -X POST "http://localhost:8000/v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"limit": 25}'

# Stage 4: Assemble the daily brief
curl -X POST "http://localhost:8000/v1/brief/run" \
  -H "X-API-Key: staging-key-123"

# View the assembled brief
curl "http://localhost:8000/v1/brief" | python3 -m json.tool
```

If you are using the `mock` neutralizer provider (recommended for local development), the neutralized text will be placeholder content. Switch `NEUTRALIZER_PROVIDER` to `openai` and set your `OPENAI_API_KEY` to see real LLM-generated neutralizations.

You can also run all four stages at once:

```bash
curl -X POST "http://localhost:8000/v1/pipeline/run" \
  -H "X-API-Key: staging-key-123"
```

---

## Day 3: Coding Conventions & Workflow

### Python (Backend)

- Framework: FastAPI with SQLAlchemy ORM
- Style: `snake_case` for functions and variables, 4-space indentation
- Test files: `test_*.py` (pytest discovers them automatically)
- Imports: standard library first, then third-party, then local (`app.`)

### TypeScript (Frontend)

- Framework: React Native with Expo
- Style: Prettier and ESLint enforced (run `npm run lint` to check)
- TypeScript strict mode is enabled
- Test files: `*.test.ts` or `*.test.tsx`

### Git Workflow

- **Branch naming:** `feature/`, `fix/`, `refactor/`, `docs/` prefixes
  - Example: `feature/add-bookmark-screen`, `fix/brief-sort-order`
- **Merge strategy:** Squash merge into `main`
- **Commits:** Write clear, descriptive commit messages
- **Pre-push:** Run tests before pushing (`pipenv run pytest` and `npm test`)

---

## Environment Variables Reference

### Required for Local Development

These are the minimum variables to get the backend running locally. They should already be in `.env.example`.

| Variable | Value | Notes |
|----------|-------|-------|
| `DATABASE_URL` | `postgresql+psycopg2://postgres:postgres@localhost:5432/ntrl_dev` | Local PostgreSQL connection |
| `NEUTRALIZER_PROVIDER` | `mock` | Uses mock LLM responses (free, fast, no API key needed) |
| `STORAGE_PROVIDER` | `local` | Stores article bodies on local filesystem instead of S3 |

### Required for Staging / Production

| Variable | Value | Notes |
|----------|-------|-------|
| `DATABASE_URL` | Railway PostgreSQL URL | Provided by Railway |
| `NEUTRALIZER_PROVIDER` | `openai` | Real LLM-based neutralization |
| `OPENAI_API_KEY` | `sk-...` | OpenAI API key |
| `STORAGE_PROVIDER` | `s3` | AWS S3 for article body storage |
| `S3_BUCKET` | `ntrl-raw-content` | S3 bucket name |
| `AWS_ACCESS_KEY_ID` | `...` | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | `...` | AWS credentials |
| `ADMIN_API_KEY` | `...` | Key for admin endpoints |

---

## Staging Environment

| Detail | Value |
|--------|-------|
| API URL | `https://api-staging-7b4d.up.railway.app` |
| Admin API Key | `staging-key-123` (use in `X-API-Key` header) |
| Deployment | Auto-deploys from `main` branch on push via Railway |

Example: hitting the staging brief endpoint:

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/brief" | python3 -m json.tool
```

Example: triggering a pipeline run on staging:

```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/run" \
  -H "X-API-Key: staging-key-123"
```

---

## Testing

### Backend Tests

```bash
cd code/ntrl-api

# Run the full test suite
pipenv run pytest

# Run with coverage report
pipenv run pytest --cov=app

# Run a specific test file
pipenv run pytest tests/test_neutralizer.py

# Run a specific test by name
pipenv run pytest -k "test_brief_assembly"
```

The backend uses `mock` provider settings by default in tests, so no API keys are needed.

### Frontend Tests

```bash
cd code/ntrl-app

# Run unit tests
npm test

# Run linter
npm run lint
```

### UI Testing with Playwright

End-to-end tests use Playwright to exercise the app in a browser environment.

```bash
cd code/ntrl-app

# Run end-to-end tests
npm run e2e
```

Make sure the backend is running before starting E2E tests, as they hit real API endpoints.

---

## Key Contacts

| Role | Name | Contact |
|------|------|---------|
| Founder | Eric Brown | [contact info] |

---

## First Tasks for New Engineers

Once your environment is running, work through these tasks to build familiarity with the codebase:

### Starter Task 1: Run the Tests
```bash
cd code/ntrl-api && pipenv run pytest
cd code/ntrl-app && npm test
```
Verify everything passes. If anything fails, debug it -- that is a useful exercise in itself.

### Starter Task 2: Trace a Story End-to-End
1. Trigger ingestion (`POST /v1/ingest/run`)
2. Pick a story ID from the database or API response
3. Classify it (`POST /v1/classify/run`)
4. Neutralize it (`POST /v1/neutralize/run`)
5. Assemble the brief (`POST /v1/brief/run`)
6. View the story at `GET /v1/stories/{id}` and its transparency data at `GET /v1/stories/{id}/transparency`
7. Open the app and find the same story in TodayScreen or SectionsScreen

### Starter Task 3: Read the Neutralizer Code
Open `app/services/neutralizer/` and trace how a raw article body becomes neutralized output. Pay attention to:
- How providers are selected (`NEUTRALIZER_PROVIDER` env var)
- What the `mock` provider returns vs. the `openai` provider
- How spans (transparency annotations) are generated

### Starter Task 4: Explore the Frontend Screens
Open the app in a simulator and navigate through:
1. **TodayScreen** -- the main landing page with session-filtered articles
2. **SectionsScreen** -- browse by category
3. **ArticleDetailScreen** -- tap an article, switch between Brief / Full / Ntrl tabs
4. Notice how **NtrlContent** renders inline transparency data (it is a component, not a separate screen)

### Starter Task 5: Add a New RSS Source
```bash
curl -X POST "http://localhost:8000/v1/sources" \
  -H "Content-Type: application/json" \
  -d '{"name": "AP News", "slug": "ap-news", "rss_url": "https://rsshub.app/apnews/topics/apf-topnews"}'
```
Then run the full pipeline and verify the new source's articles appear in the brief.

---

## FAQ / Troubleshooting

**Q: `createdb ntrl_dev` fails with "connection refused"**
A: Make sure PostgreSQL is running locally. On macOS with Homebrew: `brew services start postgresql@16`.

**Q: `pipenv install` is very slow or hangs**
A: Try `pipenv install --skip-lock` for a faster (though less reproducible) install. You can run `pipenv lock` separately later.

**Q: The app shows no articles after starting**
A: You need to run the pipeline first. Articles do not appear until all four stages (ingest, classify, neutralize, brief assemble) have completed. Use the curl commands in the "Try the Full Pipeline" section above.

**Q: `npm start` fails with port already in use**
A: Kill the process on port 8081 (`lsof -ti:8081 | xargs kill`) or use `npx expo start --port 8082`.

**Q: Tests fail because of missing environment variables**
A: Copy `.env.example` to `.env` in `code/ntrl-api/`. The test suite uses mock providers by default and should not need API keys.

**Q: What happened to FeedScreen / RedlineScreen?**
A: These screens are deprecated and no longer in use. FeedScreen was replaced by TodayScreen and SectionsScreen. RedlineScreen was replaced by the NtrlContent inline component within ArticleDetailScreen. Do not reference them in new code.

**Q: How do I see real (non-mock) neutralized content locally?**
A: Set `NEUTRALIZER_PROVIDER=openai` and `OPENAI_API_KEY=sk-...` in your `.env` file, then restart the server and re-run the neutralize stage.

**Q: How do I access admin endpoints?**
A: Include the `X-API-Key` header in your request. For local development, use the value from your `.env` file. For staging, use `staging-key-123`.

---

## Additional Resources

- `docs/README.md` -- Full documentation index
- `code/ntrl-api/CLAUDE.md` -- Comprehensive backend reference
- `code/ntrl-app/CLAUDE.md` -- Comprehensive frontend reference
- `AGENTS.md` -- Repository-wide guidelines and conventions
- `brand/NTRL_Brand_and_Product_Canon_v1.0.pdf` -- Brand identity and product mission
