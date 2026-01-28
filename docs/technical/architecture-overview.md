# NTRL System Architecture Overview

> **Version:** 1.0
> **Last Updated:** 2026-01-28
> **Status:** Living document

---

## Table of Contents

1. [System Overview & Design Philosophy](#1-system-overview--design-philosophy)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Project Structure](#4-project-structure)
5. [The 4-Stage Content Pipeline](#5-the-4-stage-content-pipeline)
6. [Database Architecture](#6-database-architecture)
7. [LLM Integration](#7-llm-integration)
8. [API Architecture](#8-api-architecture)
9. [Security Architecture](#9-security-architecture)
10. [Infrastructure & Deployment](#10-infrastructure--deployment)
11. [Data Flow](#11-data-flow)
12. [Frontend Architecture](#12-frontend-architecture)
13. [Monitoring & Observability](#13-monitoring--observability)

---

## 1. System Overview & Design Philosophy

NTRL is a neutral news platform that ingests articles from RSS feeds, classifies them by domain and category, neutralizes manipulative or biased language using LLMs, and presents the resulting content through a mobile application. The platform is split across two codebases:

| Codebase     | Role     | Stack                                    |
|------------- |--------- |----------------------------------------- |
| **ntrl-api** | Backend  | FastAPI, Python 3.11, PostgreSQL, S3     |
| **ntrl-app** | Frontend | React Native 0.81.5, Expo 54, TypeScript |

### Core Principle: Body-as-Source-of-Truth

Every user-facing output derives from the **original article body**, not from RSS metadata. The RSS title and description are stored for auditing purposes but are never used as inputs to classification or neutralization. This guarantees that the neutralization process operates on the most complete representation of the original journalism, not on truncated or editorially skewed summaries.

```
INGEST:          RSS --> Database (metadata) + S3 (body.txt)
CLASSIFY:        body.txt --> domain (20) + feed_category (10) + tags
NEUTRALIZE:      body.txt --> ALL outputs (title, summary, brief, full, spans)
BRIEF ASSEMBLE:  Group by feed_category (10 categories) --> DailyBrief
DISPLAY:         Neutralized content by default, originals only in "ntrl view"
```

This single-source design eliminates an entire class of consistency bugs where different outputs could drift from one another if they were derived from different source texts.

---

## 2. High-Level Architecture

```
+------------------+       +----------------------------+       +------------------+
|                  |       |        ntrl-api            |       |                  |
|   RSS Feeds      +------>+  (FastAPI / Python 3.11)   +<------+   ntrl-app       |
|   (External)     |       |                            |       |  (React Native   |
+------------------+       |  +----------------------+  |       |   / Expo 54)     |
                           |  | 4-Stage Pipeline     |  |       |                  |
                           |  |                      |  |       | +-------------+  |
                           |  | 1. INGEST            |  |       | | TodayScreen |  |
                           |  | 2. CLASSIFY          |  |       | +-------------+  |
                           |  | 3. NEUTRALIZE        |  |       | | Sections    |  |
                           |  | 4. BRIEF ASSEMBLE    |  |       | +-------------+  |
                           |  +----------------------+  |       | | ArticleView |  |
                           |                            |       | +-------------+  |
                           |  +--------+  +---------+   |       | | NtrlContent |  |
                           |  | LLMs   |  | spaCy   |   |       | +-------------+  |
                           |  +--------+  +---------+   |       +--------+---------+
                           +------+----------+----------+                |
                                  |          |                           |
                           +------v---+ +----v-------+          HTTPS / REST
                           |PostgreSQL | |  AWS S3    |          JSON responses
                           | (Railway) | | (raw body) |
                           +----------+ +------------+
```

### Request Flow

1. **Scheduled pipeline** (Railway cron, every 4 hours) triggers the 4-stage pipeline via admin endpoints.
2. **Ingestion** fetches RSS feeds, extracts article bodies, stores metadata in PostgreSQL and raw body text in S3.
3. **Classification** reads the body from S3 and uses LLM + fallback chain to assign domain, feed_category, and tags.
4. **Neutralization** reads the body from S3 and uses LLM to produce all user-facing text outputs.
5. **Brief assembly** groups neutralized stories by feed_category into a versioned DailyBrief.
6. **Mobile app** fetches the brief and individual stories via REST endpoints, rendering neutralized content by default.

---

## 3. Tech Stack

### Backend (ntrl-api)

| Layer              | Technology                                    | Notes                                          |
|------------------- |---------------------------------------------- |------------------------------------------------ |
| Framework          | FastAPI + Uvicorn                             | ASGI, async-capable                            |
| Language           | Python 3.11                                   |                                                |
| ORM                | SQLAlchemy                                    | Declarative models                             |
| Migrations         | Alembic                                       | Version-controlled schema changes              |
| Database           | PostgreSQL                                    | Railway-hosted, internal networking            |
| Object Storage     | AWS S3 (`ntrl-raw-content`)                   | Local filesystem fallback for development      |
| AI / LLM           | OpenAI (gpt-4o-mini), Gemini (2.0-flash), Anthropic | Pluggable provider architecture         |
| NLP                | spaCy (`en_core_web_sm`)                      | Lazy-loaded via `@lru_cache`                   |
| Config             | pydantic-settings                             | Validates all env vars at startup              |
| Rate Limiting      | slowapi                                       | Per-endpoint limits                            |
| Caching            | cachetools `TTLCache`                         | In-memory, per-endpoint TTLs                   |
| Dependency Mgmt    | Pipenv                                        | All versions pinned in `Pipfile.lock`          |

### Frontend (ntrl-app)

| Layer              | Technology                                    | Notes                                          |
|------------------- |---------------------------------------------- |------------------------------------------------ |
| Framework          | React Native 0.81.5                           |                                                |
| Platform SDK       | Expo 54                                       | Managed workflow with EAS Build                |
| Language           | TypeScript 5.9                                |                                                |
| Navigation         | React Navigation (Native Stack)               | Stack-based screen routing                     |
| Platforms          | iOS, Android                                  |                                                |
| Theme              | Dynamic light/dark mode                       | `useTheme()` hook                              |
| Unit Testing       | Jest + React Testing Library                  |                                                |
| E2E Testing        | Playwright                                    |                                                |

---

## 4. Project Structure

### Backend (`ntrl-api`)

```
app/
├── main.py                  # FastAPI entry point
│                            #   - CORS middleware (restricted origins)
│                            #   - Rate limiting middleware (slowapi)
│                            #   - Global exception handler (sanitized responses)
│                            #   - Router registration
│
├── config.py                # Pydantic-settings configuration
│                            #   - Validates all environment variables on startup
│                            #   - Fails fast on missing required config
│
├── constants.py             # Centralized magic constants
│                            #   - Thresholds, limits, fixed orderings
│
├── database.py              # SQLAlchemy engine + session factory
│
├── models.py                # SQLAlchemy ORM model definitions
│                            #   - Source, StoryRaw, StoryNeutralized,
│                            #     TransparencySpan, ManipulationSpan,
│                            #     DailyBrief, DailyBriefItem,
│                            #     PipelineLog, PipelineRunSummary, Prompt
│
├── taxonomy.py              # 115 manipulation types (v2 taxonomy)
│
├── routers/
│   ├── admin.py             # V1 admin endpoints
│   │                        #   POST /v1/admin/ingest
│   │                        #   POST /v1/admin/classify
│   │                        #   POST /v1/admin/neutralize
│   │                        #   POST /v1/admin/brief
│   │                        #   POST /v1/admin/pipeline
│   │
│   ├── brief.py             # V1 brief endpoints (TTL-cached, 15min)
│   │                        #   GET /v1/brief
│   │                        #   GET /v1/brief/latest
│   │
│   ├── stories.py           # V1 story endpoints (TTL-cached, 1hr)
│   │                        #   GET /v1/stories/{id}
│   │                        #   GET /v1/stories/{id}/transparency
│   │                        #   GET /v1/stories/{id}/debug (dev only)
│   │
│   ├── sources.py           # V1 sources endpoints
│   │                        #   GET /v1/sources
│   │
│   └── pipeline.py          # V2 pipeline endpoints
│
├── schemas/                 # Pydantic request/response schemas
│                            #   - Strict type validation
│                            #   - Serialization for API responses
│
├── services/
│   ├── ingestion.py                      # RSS ingestion service
│   │                                     #   - SSL-verified HTTP fetches
│   │                                     #   - Body extraction + S3 upload
│   │                                     #   - Deduplication logic
│   │
│   ├── llm_classifier.py                # LLM-based article classification
│   │                                     #   - Primary: gpt-4o-mini
│   │                                     #   - Fallback: gemini-2.0-flash
│   │
│   ├── domain_mapper.py                  # Domain + geography --> feed_category
│   │                                     #   - Maps 20 domains to 10 categories
│   │
│   ├── enhanced_keyword_classifier.py    # Keyword fallback classifier
│   │                                     #   - 20-domain keyword matching
│   │                                     #   - Last resort (<1% of articles)
│   │
│   ├── neutralizer/
│   │   ├── __init__.py                   # Main neutralizer orchestration
│   │   │                                 #   - Synthesis mode (primary)
│   │   │                                 #   - Synthesis fallback for garbled output
│   │   ├── providers/                    # LLM provider implementations
│   │   │   ├── openai_provider.py        #   - OpenAI (gpt-4o-mini)
│   │   │   ├── gemini_provider.py        #   - Google Gemini (2.0-flash)
│   │   │   └── anthropic_provider.py     #   - Anthropic Claude
│   │   └── spans.py                      # Span detection utilities
│   │                                     #   - Pattern matching on original body
│   │
│   ├── brief_assembly.py                # DailyBrief construction
│   │                                     #   - Groups by feed_category
│   │                                     #   - Fixed 10-category ordering
│   │
│   └── alerts.py                         # Pipeline alerting service
│
├── storage/
│   ├── s3.py                # AWS S3 storage provider
│   └── local.py             # Local filesystem fallback
│
└── jobs/                    # Background / scheduled jobs
```

### Frontend (`ntrl-app`)

```
src/
├── screens/
│   ├── TodayScreen.tsx              # Session-filtered article feed
│   │                                #   - Pulls from GET /v1/brief
│   │                                #   - Grouped by feed_category
│   │
│   ├── SectionsScreen.tsx           # All category sections browser
│   │
│   ├── ArticleDetailScreen.tsx      # Full article view
│   │                                #   - Three tabs: Brief / Full / Ntrl
│   │                                #   - Brief: neutralized summary
│   │                                #   - Full: neutralized full text
│   │                                #   - Ntrl: transparency view (highlights)
│   │
│   ├── ProfileScreen.tsx            # User content and topic preferences
│   ├── SettingsScreen.tsx           # App settings
│   └── SearchScreen.tsx             # Article search
│
├── components/
│   ├── NtrlContent.tsx              # Inline transparency view
│   │                                #   - Renders ManipulationSpans as highlights
│   │                                #   - Shows original vs. neutralized text
│   │
│   ├── ArticleBrief.tsx             # Brief article paragraph renderer
│   ├── SegmentedControl.tsx         # Tab switcher (Brief/Full/Ntrl)
│   └── ...                          # Shared UI components
│
├── api.ts                           # Centralized API client
│                                    #   - Base URL configuration
│                                    #   - Request/response typing
│
├── theme/                           # Design system
│                                    #   - Color tokens (light/dark)
│                                    #   - Typography scale
│                                    #   - Spacing system
│
└── storage/                         # Local storage utilities
                                     #   - AsyncStorage wrappers
                                     #   - Cached preferences
```

---

## 5. The 4-Stage Content Pipeline

The pipeline runs on a scheduled cron job every 4 hours and can also be triggered manually via the admin API. Each stage is independently invokable for debugging and re-processing.

### Stage 1: INGEST

**Purpose:** Fetch articles from configured RSS feeds, extract the full article body, and persist everything for downstream processing.

```
RSS Feed URLs (Source.rss_url where is_active=True)
        |
        v
  HTTP GET (SSL verified)
        |
        v
  Parse RSS XML --> extract entries
        |
        v
  For each entry:
    1. Check deduplication (URL-based)
    2. Fetch full article page
    3. Extract body text (HTML --> plain text)
    4. Upload body.txt to S3 (ntrl-raw-content bucket)
    5. Insert StoryRaw record in PostgreSQL
       - title, description from RSS (audit only)
       - url, published_at, source_id
       - s3_body_key (pointer to S3 object)
```

**Key design decisions:**
- SSL verification is always enabled for RSS fetches to prevent MITM attacks.
- Deduplication happens by URL to avoid re-ingesting the same article from multiple feeds.
- The RSS title and description are stored but never used as neutralization inputs.
- Body text is stored in S3 (not in the database) to keep PostgreSQL lean and enable independent scaling of storage.

### Stage 2: CLASSIFY

**Purpose:** Assign each article a domain (20 possible), feed_category (10 possible), and classification tags using the article body.

```
StoryRaw (unclassified)
        |
        v
  Read body.txt from S3 (first 2000 chars)
        |
        v
  LLM Classification (4-attempt reliability chain):
        |
        +--[1]--> gpt-4o-mini (full prompt)      --> success? --> done
        |
        +--[2]--> gpt-4o-mini (simplified prompt) --> success? --> done
        |
        +--[3]--> gemini-2.0-flash (full prompt)  --> success? --> done
        |
        +--[4]--> enhanced_keyword_classifier      --> always produces result
        |
        v
  domain_mapper: domain + geography --> feed_category
        |
        v
  Update StoryRaw:
    - domain (1 of 20)
    - feed_category (1 of 10)
    - classification_tags (list)
    - classification_confidence (float)
    - classification_model (which LLM succeeded)
    - classification_method (llm | keyword)
    - classified_at (timestamp)
```

**The 20 Domains:**
Domains represent fine-grained topic areas. The domain_mapper consolidates these (plus geography signals) into one of 10 feed categories for user-facing display.

**The 10 Feed Categories (fixed display order):**

| Order | Category     |
|------ |------------- |
| 1     | World        |
| 2     | U.S.         |
| 3     | Local        |
| 4     | Business     |
| 5     | Technology   |
| 6     | Science      |
| 7     | Health       |
| 8     | Environment  |
| 9     | Sports       |
| 10    | Culture      |

**Reliability chain rationale:** The 4-attempt chain ensures near-100% classification coverage. The keyword fallback classifier handles fewer than 1% of articles in production but guarantees that no article is left unclassified.

### Stage 3: NEUTRALIZE

**Purpose:** Generate all user-facing content from the original article body, detect and annotate manipulative language spans.

```
StoryRaw (classified, not yet neutralized)
        |
        v
  Read body.txt from S3 (full text)
        |
        v
  LLM Neutralization (Synthesis Mode):
    Input:  original body text
    Output: JSON with 6 fields:
      - feed_title        (short headline for feed cards)
      - feed_summary      (1-2 sentence summary for feed)
      - detail_title      (full headline for article view)
      - detail_brief      (3-5 paragraph briefing)
      - detail_full       (full neutralized article)
      - spans             (manipulative phrase annotations)
        |
        v
  Validation:
    - JSON parse succeeds?
    - All 6 fields present and non-empty?
    - If garbled: retry with synthesis fallback prompt
        |
        v
  Span Detection:
    - Pattern matching on original body
    - Maps to 115-type manipulation taxonomy
    - Records: start_char, end_char, original_text, action, reason, replacement_text
        |
        v
  Persist:
    - StoryNeutralized record (all 6 text fields)
    - TransparencySpan records (simple spans)
    - ManipulationSpan records (rich taxonomy spans)
    - neutralization_status:
        success | failed_llm | failed_garbled | failed_audit | skipped
```

**Neutralization status tracking** ensures observability into pipeline health. Each status maps to a specific failure mode:

| Status            | Meaning                                          |
|------------------ |------------------------------------------------- |
| `success`         | All outputs generated and validated               |
| `failed_llm`     | LLM provider returned an error                   |
| `failed_garbled`  | LLM output could not be parsed as valid JSON      |
| `failed_audit`    | Output failed quality checks                     |
| `skipped`         | Article excluded by policy (e.g., too short)      |

### Stage 4: BRIEF ASSEMBLE

**Purpose:** Group the day's successfully neutralized stories into a structured DailyBrief for consumption by the mobile app.

```
StoryNeutralized (status = success, today's date)
        |
        v
  Group by feed_category
        |
        v
  Order categories: World, U.S., Local, Business,
                     Technology, Science, Health,
                     Environment, Sports, Culture
        |
        v
  Create DailyBrief:
    - brief_date (today)
    - version (incremented per rebuild)
        |
        v
  Create DailyBriefItems:
    - story_neutralized_id (FK)
    - feed_category
    - position (ordering within category)
    - Denormalized fields for fast reads:
        feed_title, feed_summary, source_name
```

**Versioning:** Each time the brief is rebuilt for the same date, the version number increments. This allows the mobile app to detect updates and refresh content.

---

## 6. Database Architecture

### Entity-Relationship Overview

```
Source (1) ----< (N) StoryRaw (1) ----< (1) StoryNeutralized
                        |                        |
                        |                   (1) -+---< (N) TransparencySpan
                        |                        +---< (N) ManipulationSpan
                        |
                        +--- s3_body_key --> [S3: body.txt]

DailyBrief (1) ----< (N) DailyBriefItem >---- (1) StoryNeutralized

PipelineLog         (audit trail, no FK constraints)
PipelineRunSummary  (aggregated health metrics)
Prompt              (hot-reloadable LLM prompts)
```

### Model Details

#### Source
Represents an RSS feed that the system monitors for new articles.

| Column     | Type    | Description                        |
|----------- |-------- |----------------------------------- |
| id         | Integer | Primary key                        |
| name       | String  | Human-readable source name         |
| slug       | String  | URL-safe identifier (unique)       |
| rss_url    | String  | RSS feed URL                       |
| is_active  | Boolean | Whether to include in ingestion    |

#### StoryRaw
The raw ingested article. Metadata lives in PostgreSQL; the full body text lives in S3.

| Column                     | Type      | Description                                     |
|--------------------------- |---------- |------------------------------------------------ |
| id                         | Integer   | Primary key                                     |
| source_id                  | Integer   | FK to Source                                     |
| url                        | String    | Original article URL (unique, dedup key)         |
| title                      | String    | RSS title (audit only, not used for neutralization) |
| description                | Text      | RSS description (audit only)                     |
| published_at               | DateTime  | Publication timestamp                            |
| s3_body_key                | String    | S3 object key for body.txt                       |
| domain                     | String    | Classified domain (1 of 20)                      |
| feed_category              | String    | Mapped feed category (1 of 10)                   |
| classification_tags        | JSON      | Tag array from classifier                        |
| classification_confidence  | Float     | Classifier confidence score                      |
| classification_model       | String    | Which LLM/method produced the classification     |
| classification_method      | String    | `llm` or `keyword`                               |
| classified_at              | DateTime  | When classification completed                    |

#### StoryNeutralized
All user-facing content derived from neutralization of the original body.

| Column               | Type     | Description                                    |
|--------------------- |--------- |----------------------------------------------- |
| id                   | Integer  | Primary key                                    |
| story_raw_id         | Integer  | FK to StoryRaw (one-to-one)                    |
| feed_title           | String   | Short headline for feed cards                  |
| feed_summary         | Text     | 1-2 sentence summary for feed                 |
| detail_title         | String   | Full headline for article view                 |
| detail_brief         | Text     | 3-5 paragraph briefing                        |
| detail_full          | Text     | Full neutralized article                       |
| version              | Integer  | Incremented on re-neutralization               |
| neutralization_status| String   | success/failed_llm/failed_garbled/failed_audit/skipped |
| created_at           | DateTime | First neutralization timestamp                 |
| updated_at           | DateTime | Last re-neutralization timestamp               |

#### TransparencySpan
Simple manipulative phrase annotations linked to a neutralized story.

| Column           | Type    | Description                              |
|----------------- |-------- |----------------------------------------- |
| id               | Integer | Primary key                              |
| story_neutral_id | Integer | FK to StoryNeutralized                   |
| start_char       | Integer | Start character offset in original body  |
| end_char         | Integer | End character offset in original body    |
| original_text    | Text    | The manipulative phrase                  |
| action           | String  | What the neutralizer did (removed, replaced, softened) |
| reason           | Text    | Why this phrase was flagged              |
| replacement_text | Text    | What replaced it in the neutralized version |

#### ManipulationSpan
Rich taxonomy-based analysis spans with severity scoring.

| Column           | Type    | Description                              |
|----------------- |-------- |----------------------------------------- |
| id               | Integer | Primary key                              |
| story_neutral_id | Integer | FK to StoryNeutralized                   |
| start_char       | Integer | Start character offset                   |
| end_char         | Integer | End character offset                     |
| original_text    | Text    | The flagged phrase                       |
| manipulation_type| String  | One of 115 taxonomy types (v2)           |
| severity         | Float   | Severity score                           |
| detector         | String  | Which detector found this span           |

#### DailyBrief
A versioned daily brief containing curated stories across 10 categories.

| Column      | Type     | Description                       |
|------------ |--------- |---------------------------------- |
| id          | Integer  | Primary key                       |
| brief_date  | Date     | The date this brief covers        |
| version     | Integer  | Incremented on each rebuild       |
| created_at  | DateTime | Creation timestamp                |

#### DailyBriefItem
Individual story entries within a DailyBrief. Denormalized for fast API reads.

| Column                | Type    | Description                              |
|---------------------- |-------- |----------------------------------------- |
| id                    | Integer | Primary key                              |
| daily_brief_id        | Integer | FK to DailyBrief                         |
| story_neutralized_id  | Integer | FK to StoryNeutralized                   |
| feed_category         | String  | Category for grouping                    |
| position              | Integer | Display order within category            |
| feed_title            | String  | Denormalized from StoryNeutralized       |
| feed_summary          | Text    | Denormalized from StoryNeutralized       |
| source_name           | String  | Denormalized from Source                 |

#### PipelineLog
Audit trail for every pipeline execution.

| Column      | Type     | Description                       |
|------------ |--------- |---------------------------------- |
| id          | Integer  | Primary key                       |
| stage       | String   | Pipeline stage name               |
| status      | String   | success / failure                 |
| message     | Text     | Human-readable log message        |
| metadata    | JSON     | Structured details                |
| created_at  | DateTime | Timestamp                         |

#### PipelineRunSummary
Aggregated metrics per pipeline run for health monitoring.

| Column            | Type     | Description                       |
|------------------ |--------- |---------------------------------- |
| id                | Integer  | Primary key                       |
| run_started_at    | DateTime | Pipeline start time               |
| run_completed_at  | DateTime | Pipeline end time                 |
| stories_ingested  | Integer  | Count of new articles             |
| stories_classified| Integer  | Count classified                  |
| stories_neutralized| Integer | Count neutralized                 |
| errors            | JSON     | Error details                     |

#### Prompt
Hot-reloadable LLM prompts, allowing prompt iteration without redeployment.

| Column      | Type     | Description                       |
|------------ |--------- |---------------------------------- |
| id          | Integer  | Primary key                       |
| name        | String   | Prompt identifier (unique)        |
| template    | Text     | Prompt template text              |
| version     | Integer  | Prompt version                    |
| is_active   | Boolean  | Whether this version is live      |
| created_at  | DateTime | Creation timestamp                |

---

## 7. LLM Integration

### Provider Architecture

The neutralizer uses a pluggable provider pattern. Each provider implements a common interface for sending prompts and receiving structured responses.

```
services/neutralizer/
├── __init__.py          # Orchestrator: selects provider, handles fallbacks
├── providers/
│   ├── openai_provider.py      # OpenAI API (gpt-4o-mini)
│   ├── gemini_provider.py      # Google Gemini API (2.0-flash)
│   └── anthropic_provider.py   # Anthropic API (Claude)
└── spans.py             # Pattern-based span detection
```

### Provider Priority

| Priority | Provider  | Model           | Role                          |
|--------- |---------- |---------------- |------------------------------ |
| Primary  | OpenAI    | gpt-4o-mini     | Classification + Neutralization |
| Fallback | Gemini    | 2.0-flash       | Classification fallback        |
| Available| Anthropic | Claude          | Reserved / experimental        |

### Classification Reliability Chain

The classifier attempts up to 4 times before falling back to keyword matching:

```
Attempt 1: gpt-4o-mini  + full classification prompt
    |
    v (failure)
Attempt 2: gpt-4o-mini  + simplified prompt (fewer instructions)
    |
    v (failure)
Attempt 3: gemini-2.0-flash + full classification prompt
    |
    v (failure)
Attempt 4: enhanced_keyword_classifier (deterministic, always succeeds)
```

Each attempt is logged with the model used, enabling analysis of per-provider reliability rates.

### Neutralization Modes

**Synthesis Mode (Primary):**
The LLM receives the original article body and produces a complete neutral rewrite. The output is plain text free of manipulative language. This mode produces all 6 output fields (feed_title, feed_summary, detail_title, detail_brief, detail_full, spans) in a single structured JSON response.

**Synthesis Fallback:**
When the primary synthesis response is garbled (unparseable JSON, missing fields), the system retries with a simplified synthesis prompt. If this also fails, the article is marked `failed_garbled`.

**Span Detection:**
Span detection operates separately from synthesis. Pattern matching runs against the original body text to identify manipulative phrases, mapping them to the 115-type manipulation taxonomy defined in `taxonomy.py`. This separation ensures that span annotations are always grounded in the original text, not in the LLM's rewrite.

### Model Selection

Both classification and neutralization use `gpt-4o-mini` in production. This model was selected for its balance of quality, speed, and cost:
- Fast enough for batch processing (hundreds of articles per pipeline run)
- Sufficient quality for neutral rewriting and classification
- Cost-effective at scale

The debug endpoint also uses `gpt-4o-mini` for consistency with production behavior.

---

## 8. API Architecture

### Endpoint Overview

#### V1 Endpoints

**Brief Endpoints (`/v1/brief`)**

| Method | Path                | Auth     | Cache   | Description                    |
|------- |-------------------- |--------- |-------- |------------------------------- |
| GET    | `/v1/brief`         | Public   | 15min   | Current daily brief            |
| GET    | `/v1/brief/latest`  | Public   | 15min   | Latest brief (alias)           |

**Story Endpoints (`/v1/stories`)**

| Method | Path                              | Auth     | Cache   | Description                    |
|------- |---------------------------------- |--------- |-------- |------------------------------- |
| GET    | `/v1/stories/{id}`                | Public   | 1hr     | Full story detail              |
| GET    | `/v1/stories/{id}/transparency`   | Public   | 1hr     | Transparency spans             |
| GET    | `/v1/stories/{id}/debug`          | Public   | None    | Debug info (dev only)          |

**Source Endpoints (`/v1/sources`)**

| Method | Path                | Auth     | Cache   | Description                    |
|------- |-------------------- |--------- |-------- |------------------------------- |
| GET    | `/v1/sources`       | Public   | None    | List active sources            |

**Admin Endpoints (`/v1/admin`)**

| Method | Path                       | Auth     | Rate Limit | Description                    |
|------- |--------------------------- |--------- |----------- |------------------------------- |
| POST   | `/v1/admin/ingest`         | Admin    | 10/min     | Trigger ingestion              |
| POST   | `/v1/admin/classify`       | Admin    | 10/min     | Trigger classification         |
| POST   | `/v1/admin/neutralize`     | Admin    | 10/min     | Trigger neutralization         |
| POST   | `/v1/admin/brief`          | Admin    | 10/min     | Trigger brief assembly         |
| POST   | `/v1/admin/pipeline`       | Admin    | 5/min      | Trigger full pipeline          |

#### V2 Endpoints

| Method | Path                       | Auth     | Description                    |
|------- |--------------------------- |--------- |------------------------------- |
| POST   | `/v2/pipeline/*`           | Admin    | V2 pipeline operations         |

### Caching Strategy

Caching is implemented using `cachetools.TTLCache` (in-memory, per-process):

```python
# Cache configuration
brief_cache     = TTLCache(maxsize=10,  ttl=900)    # 15 minutes
story_cache     = TTLCache(maxsize=500, ttl=3600)   # 1 hour
transparency_cache = TTLCache(maxsize=500, ttl=3600) # 1 hour
```

**Cache behavior:**
- Response headers include `Cache-Control` with appropriate `max-age`.
- `X-Cache: HIT` or `X-Cache: MISS` header indicates cache status.
- Brief cache is explicitly invalidated after `POST /v1/admin/brief` or `POST /v1/admin/pipeline` to ensure fresh data is served immediately after a pipeline run.

### Rate Limiting

Rate limits are enforced via `slowapi` middleware:

| Scope            | Limit     | Description                              |
|----------------- |---------- |----------------------------------------- |
| Global (public)  | 100/min   | All public endpoints combined            |
| Admin endpoints  | 10/min    | Per admin endpoint                       |
| Pipeline trigger | 5/min     | Full pipeline trigger specifically       |

Rate limit responses return HTTP 429 with a `Retry-After` header.

---

## 9. Security Architecture

### Authentication

Admin endpoints are protected by API key authentication using timing-safe comparison:

```python
import secrets

def verify_admin_key(provided_key: str) -> bool:
    expected_key = config.ADMIN_API_KEY
    if not expected_key:
        # Fail-closed: if ADMIN_API_KEY is not configured, deny all access
        return False
    return secrets.compare_digest(provided_key, expected_key)
```

**Key design decisions:**
- **Timing-safe comparison** (`secrets.compare_digest`) prevents timing side-channel attacks.
- **Fail-closed** behavior: if `ADMIN_API_KEY` is not set in the environment, all admin requests are denied. This prevents accidental exposure in misconfigured deployments.

### CORS

Cross-Origin Resource Sharing is restricted to configured origins only:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,  # Explicit whitelist
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

### SSL / TLS

- All RSS feed fetches use SSL verification (`verify=True`).
- No option to disable SSL verification exists in production code.

### Error Response Sanitization

All error responses are sanitized to prevent leaking internal state:

```python
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    # Log full traceback internally
    logger.exception("Unhandled exception")
    # Return sanitized response to client
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )
```

No stack traces, file paths, or internal identifiers are ever exposed in API responses.

### Dependency Security

All dependencies are pinned to exact versions in `Pipfile.lock`, ensuring reproducible builds and preventing supply chain attacks through version drift.

### Configuration Validation

`pydantic-settings` validates all environment variables at application startup. Missing or invalid configuration causes immediate startup failure, preventing the application from running in a misconfigured state.

---

## 10. Infrastructure & Deployment

### Deployment Topology

```
+---------------------+         +---------------------+
|     Railway          |         |     AWS              |
|                     |         |                     |
|  +---------------+  |         |  +---------------+  |
|  | ntrl-api      |  |  HTTPS  |  |  S3 Bucket    |  |
|  | (FastAPI)     |<-+-------->+  | ntrl-raw-     |  |
|  | Auto-deploy   |  |         |  | content       |  |
|  +-------+-------+  |         |  +---------------+  |
|          |           |         +---------------------+
|  +-------v-------+  |
|  | PostgreSQL    |  |         +---------------------+
|  | (Internal)    |  |         |     Expo / EAS       |
|  +---------------+  |         |                     |
|                     |         |  +---------------+  |
|  +---------------+  |         |  | ntrl-app      |  |
|  | Cron Job      |  |         |  | iOS + Android |  |
|  | Every 4 hours |  |         |  | EAS Build     |  |
|  +---------------+  |         |  +---------------+  |
+---------------------+         +---------------------+
```

### Backend Deployment (Railway)

| Aspect           | Detail                                          |
|----------------- |------------------------------------------------ |
| Platform         | Railway                                          |
| Trigger          | Auto-deploy on push to `main`                    |
| Build time       | ~1 minute 30 seconds                             |
| Deploy time      | ~20 seconds                                      |
| Database         | Railway PostgreSQL (internal networking)          |
| Cron schedule    | Every 4 hours (pipeline trigger)                 |
| Health check     | Built-in Railway health monitoring               |

### Frontend Deployment (Expo / EAS)

| Aspect           | Detail                                          |
|----------------- |------------------------------------------------ |
| Platform         | Expo Application Services (EAS)                  |
| Build system     | EAS Build                                        |
| Targets          | iOS (App Store), Android (Google Play)           |
| OTA updates      | Expo Updates for JS bundle changes               |

### Storage (AWS S3)

| Aspect           | Detail                                          |
|----------------- |------------------------------------------------ |
| Bucket           | `ntrl-raw-content`                               |
| Contents         | Raw article body text files                      |
| Access           | Backend service via AWS SDK (IAM credentials)    |
| Fallback         | Local filesystem for development environments    |

---

## 11. Data Flow

### End-to-End Pipeline Flow

```
                        EXTERNAL
                    +-------------+
                    |  RSS Feeds  |
                    +------+------+
                           |
                    [STAGE 1: INGEST]
                           |
               +-----------+-----------+
               |                       |
        +------v------+        +------v------+
        |  PostgreSQL  |        |    AWS S3    |
        |              |        |              |
        | StoryRaw     |        | body.txt     |
        | (metadata)   |        | (full text)  |
        +------+------+        +------+------+
               |                       |
               +-----------+-----------+
                           |
                    [STAGE 2: CLASSIFY]
                           |
                    Read body from S3
                    (first 2000 chars)
                           |
               +-----------+-----------+
               |                       |
        +------v------+        +------v------+
        | LLM Chain   |        | Keyword     |
        | gpt-4o-mini |        | Fallback    |
        | gemini-2.0  |        | (<1%)       |
        +------+------+        +------+------+
               |                       |
               +-----------+-----------+
                           |
                    domain_mapper
                    domain + geo --> feed_category
                           |
                    Update StoryRaw
                    (domain, feed_category, tags)
                           |
                    [STAGE 3: NEUTRALIZE]
                           |
                    Read body from S3
                    (full text)
                           |
                    +------v------+
                    | LLM Synth   |
                    | gpt-4o-mini |
                    +------+------+
                           |
               +-----------+-----------+-----------+
               |           |           |           |
        +------v--+ +------v--+ +------v--+ +-----v------+
        | Story   | | Transp. | | Manip.  | | Status     |
        | Neutral.| | Spans   | | Spans   | | Tracking   |
        +---------+ +---------+ +---------+ +------------+
                           |
                    [STAGE 4: BRIEF ASSEMBLE]
                           |
                    Group by feed_category
                    Order: World, U.S., Local, ...
                           |
               +-----------+-----------+
               |                       |
        +------v------+        +------v------+
        | DailyBrief  |        | DailyBrief  |
        | (versioned) |        | Items       |
        +------+------+        | (denorm.)   |
               |               +------+------+
               |                      |
               +----------+-----------+
                          |
                   [API LAYER]
                          |
          +---------------+---------------+
          |               |               |
   +------v------+ +------v------+ +------v------+
   | GET /brief  | | GET /story  | | GET /transp |
   | (15min TTL) | | (1hr TTL)   | | (1hr TTL)   |
   +------+------+ +------+------+ +------+------+
          |               |               |
          +-------+-------+-------+-------+
                  |               |
           +------v------+ +------v------+
           | TodayScreen | | ArticleView |
           | Sections    | | Brief/Full  |
           |             | | /Ntrl tabs  |
           +-------------+ +-------------+
                  ntrl-app (Mobile)
```

### Read Path (Mobile App)

1. **TodayScreen** loads: `GET /v1/brief` returns the latest DailyBrief with items grouped by feed_category.
2. User taps an article: navigates to `ArticleDetailScreen` with `story_neutralized_id`.
3. **ArticleDetailScreen** loads: `GET /v1/stories/{id}` returns the full neutralized story.
4. User switches to "Ntrl" tab: `GET /v1/stories/{id}/transparency` returns TransparencySpan and ManipulationSpan data.
5. **NtrlContent** component renders the original text with highlighted spans showing what was changed and why.

---

## 12. Frontend Architecture

### Navigation Structure

The app uses React Navigation with a Native Stack navigator:

```
Root Navigator (Native Stack)
├── Main Tab Navigator
│   ├── TodayScreen          # Feed: session-filtered articles
│   ├── SectionsScreen       # Browse by category
│   ├── SearchScreen         # Search articles
│   └── ProfileScreen        # User preferences
│
├── ArticleDetailScreen      # Full article (push from any list)
│   ├── Brief tab            # Neutralized brief (detail_brief)
│   ├── Full tab             # Neutralized full text (detail_full)
│   └── Ntrl tab             # Transparency view (NtrlContent)
│
└── SettingsScreen           # App settings (push from Profile)
```

### Screen Responsibilities

| Screen                  | Data Source              | Key Components                       |
|------------------------ |------------------------ |------------------------------------- |
| TodayScreen             | `GET /v1/brief`          | Article cards, category headers      |
| SectionsScreen          | `GET /v1/brief`          | Category list, article cards         |
| ArticleDetailScreen     | `GET /v1/stories/{id}`   | SegmentedControl, ArticleBrief, NtrlContent |
| SearchScreen            | `GET /v1/stories?q=`     | Search input, result list            |
| ProfileScreen           | Local storage            | Topic preferences, reading history   |
| SettingsScreen          | Local storage            | Theme toggle, notification prefs     |

### Theme System

The app supports dynamic light and dark mode through a centralized theme system:

```
theme/
├── colors.ts      # Color tokens for light and dark palettes
├── typography.ts   # Font family, sizes, weights, line heights
├── spacing.ts      # Consistent spacing scale
└── index.ts        # useTheme() hook export
```

**Usage pattern:**

```typescript
const { colors, typography, spacing } = useTheme();

// Components automatically re-render when the system theme changes
<Text style={{ color: colors.text.primary, ...typography.body }}>
  Article text
</Text>
```

The `useTheme()` hook responds to the device's color scheme preference and provides the appropriate token set. All components consume theme tokens rather than hardcoded values, ensuring consistent appearance across the app.

### Key Components

**NtrlContent** renders the transparency view:
- Receives the original article text and an array of TransparencySpan / ManipulationSpan objects.
- Highlights manipulative phrases inline with color-coded annotations.
- Tapping a highlight reveals: the original text, the action taken (removed, replaced, softened), and the reason.

**ArticleBrief** renders the neutralized briefing:
- Receives `detail_brief` text.
- Renders structured paragraphs with typography from the theme system.

**SegmentedControl** provides the tab switcher on the article detail screen:
- Three segments: Brief, Full, Ntrl.
- Manages active state and triggers content swap.

---

## 13. Monitoring & Observability

### Pipeline Health

The `PipelineRunSummary` model captures per-run metrics:

```
stories_ingested       # New articles fetched
stories_classified     # Articles successfully classified
stories_neutralized    # Articles successfully neutralized
errors                 # Structured error details (JSON)
run_started_at         # Pipeline start timestamp
run_completed_at       # Pipeline end timestamp
```

These summaries enable trend analysis: ingestion rates, classification success rates, neutralization failure rates, and pipeline duration.

### Pipeline Logging

Every pipeline stage writes to `PipelineLog`:

```
stage    # ingest | classify | neutralize | brief_assemble
status   # success | failure
message  # Human-readable description
metadata # JSON with structured details (article IDs, error messages, timings)
```

### Neutralization Status Tracking

Each `StoryNeutralized` record carries a `neutralization_status` field that enables aggregate health queries:

```sql
-- Neutralization success rate for today
SELECT
    neutralization_status,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM story_neutralized
WHERE created_at >= CURRENT_DATE
GROUP BY neutralization_status;
```

### Classification Method Tracking

Each `StoryRaw` record tracks which classifier succeeded:

```sql
-- Classification method distribution
SELECT
    classification_method,
    classification_model,
    COUNT(*) as count
FROM story_raw
WHERE classified_at >= CURRENT_DATE
GROUP BY classification_method, classification_model;
```

This reveals how often the system falls back to simpler classifiers or the keyword fallback.

### Alerting

The `alerts.py` service monitors pipeline health and can notify when:
- Ingestion fetches zero new articles.
- Classification failure rate exceeds threshold.
- Neutralization failure rate exceeds threshold.
- Pipeline duration exceeds expected bounds.

### Cache Observability

The `X-Cache` response header (`HIT` / `MISS`) allows monitoring of cache hit rates at the HTTP layer. Combined with cache TTL configuration, this data helps tune cache sizes and expiration windows.

### API Rate Limit Monitoring

`slowapi` tracks rate limit violations. HTTP 429 responses in access logs indicate when clients are being throttled, useful for identifying abuse or misconfigured clients.

---

## Appendix: Constants Reference

### Feed Categories (Fixed Display Order)

| Index | Category    |
|------ |------------ |
| 0     | World       |
| 1     | U.S.        |
| 2     | Local       |
| 3     | Business    |
| 4     | Technology  |
| 5     | Science     |
| 6     | Health      |
| 7     | Environment |
| 8     | Sports      |
| 9     | Culture     |

### Manipulation Taxonomy

The v2 taxonomy (`taxonomy.py`) defines **115 manipulation types** organized into categories. Each type has a name, description, and severity range. ManipulationSpan records reference these types for structured analysis of bias and manipulative language patterns.

### Rate Limits

| Scope              | Limit     |
|------------------- |---------- |
| Global (public)    | 100/min   |
| Admin endpoints    | 10/min    |
| Pipeline triggers  | 5/min     |

### Cache TTLs

| Endpoint           | TTL       |
|------------------- |---------- |
| Brief              | 15 min    |
| Story detail       | 1 hour    |
| Transparency data  | 1 hour    |
