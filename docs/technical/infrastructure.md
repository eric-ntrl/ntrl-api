# NTRL Infrastructure

> **Version:** 1.0
> **Last Updated:** 2026-01-28
> **Status:** Living document

---

## Table of Contents

1. [Infrastructure Overview](#1-infrastructure-overview)
2. [System Topology](#2-system-topology)
3. [Component Inventory](#3-component-inventory)
4. [Railway (Backend & Database)](#4-railway-backend--database)
5. [AWS S3 (Object Storage)](#5-aws-s3-object-storage)
6. [LLM Providers](#6-llm-providers)
7. [Frontend Infrastructure](#7-frontend-infrastructure)
8. [Environment Configuration](#8-environment-configuration)
9. [Networking & Data Flow](#9-networking--data-flow)
10. [Rate Limiting & Caching](#10-rate-limiting--caching)
11. [Security Posture](#11-security-posture)
12. [Monitoring & Alerting](#12-monitoring--alerting)
13. [Staging Environment](#13-staging-environment)
14. [Development Limits & Production Scaling](#14-development-limits--production-scaling)
15. [Operational Reference](#15-operational-reference)

---

## 1. Infrastructure Overview

NTRL runs on a lean, managed-service architecture. The backend API and database are hosted on Railway. Article body text is stored in AWS S3. LLM processing is handled by OpenAI (primary) with Google Gemini as fallback. The mobile app is built and distributed through Expo Application Services (EAS).

There are no self-managed servers, no Kubernetes clusters, and no custom CI/CD pipelines beyond what Railway and EAS provide out of the box.

```
+============================================================================+
|                        NTRL Infrastructure Map                             |
+============================================================================+
|                                                                            |
|   +-----------+     +------------------+     +---------------------------+ |
|   |  Railway  |     |    AWS           |     |   LLM Providers           | |
|   |           |     |                  |     |                           | |
|   | API       |---->| S3               |     | OpenAI (gpt-4o-mini)      | |
|   | PostgreSQL|     | ntrl-raw-content |     | Gemini (2.0-flash)        | |
|   | Cron      |     |                  |     | Anthropic (available)     | |
|   +-----------+     +------------------+     +---------------------------+ |
|        ^                                              ^                    |
|        |                                              |                    |
|        |  HTTPS / REST                    LLM API calls                    |
|        |                                              |                    |
|   +----+----+                                   +-----+------+            |
|   |  Expo / |                                   | ntrl-api   |            |
|   |  EAS    |                                   | (FastAPI)  |            |
|   | iOS     |                                   +------------+            |
|   | Android |                                                             |
|   +---------+                                                             |
|                                                                            |
+============================================================================+
```

### Design Principles

- **Managed services only.** No infrastructure to patch, scale, or babysit.
- **Auto-deploy on push.** Merging to `main` triggers build and deploy with no manual steps.
- **Fail-fast configuration.** All environment variables are validated at startup via pydantic-settings; missing config crashes the process immediately rather than failing silently at runtime.
- **Storage separation.** Metadata lives in PostgreSQL; article bodies live in S3. This keeps the database lean and allows storage to scale independently.

---

## 2. System Topology

### Full Architecture Diagram

```
                           EXTERNAL SERVICES
    +----------------------------------------------------------+
    |                                                          |
    |   +-------------+    +-----------+    +--------------+   |
    |   | RSS Feeds   |    | OpenAI    |    | Google       |   |
    |   | (100+ feeds)|    | API       |    | Gemini API   |   |
    |   +------+------+    +-----+-----+    +------+-------+   |
    |          |                 |                  |           |
    +----------|-----------------|------------------|----------+
               |                 |                  |
               v                 v                  v
    +----------------------------------------------------------+
    |                    RAILWAY PLATFORM                       |
    |                                                          |
    |   +--------------------------------------------------+   |
    |   |              ntrl-api (FastAPI)                   |   |
    |   |                                                  |   |
    |   |  +------------+  +------------+  +------------+  |   |
    |   |  | Ingestion  |  | Classifier |  | Neutralizer|  |   |
    |   |  | Service    |  | Service    |  | Service    |  |   |
    |   |  +-----+------+  +-----+------+  +-----+------+  |   |
    |   |        |               |               |          |   |
    |   |  +-----v------+  +----v-------+  +----v-------+  |   |
    |   |  | Body       |  | LLM Chain  |  | LLM Synth  |  |   |
    |   |  | Extraction |  | (4 attempts|  | + Span Det. |  |   |
    |   |  +-----+------+  +----+-------+  +----+-------+  |   |
    |   |        |               |               |          |   |
    |   |  +-----v---------v----v----+-----------v------+   |   |
    |   |  |         REST API Layer                     |   |   |
    |   |  |  /v1/brief  /v1/stories  /v1/admin         |   |   |
    |   |  |  /v1/sources /v1/status  /v1/pipeline      |   |   |
    |   |  +----+-----------------------------------+---+   |   |
    |   +-------|-----------------------------------|-------+   |
    |           |                                   |           |
    |   +-------v-------+                           |           |
    |   | PostgreSQL    |                           |           |
    |   | (Internal)    |                           |           |
    |   |               |                           |           |
    |   | stories_raw   |                           |           |
    |   | stories_neut  |                           |           |
    |   | daily_briefs  |                           |           |
    |   | sources       |                           |           |
    |   | pipeline_logs |                           |           |
    |   | prompts       |                           |           |
    |   +---------------+                           |           |
    |                                               |           |
    +-----------------------------------------------|----------+
                                                    |
                                          +---------v---------+
                                          |     AWS S3        |
                                          |                   |
                                          | ntrl-raw-content  |
                                          | Region: us-east-1 |
                                          | Prefix: raw/      |
                                          | (gzip plain text) |
                                          +-------------------+
                   |
                   |  HTTPS / JSON
                   v
    +----------------------------------------------------------+
    |                    EXPO / EAS                             |
    |                                                          |
    |   +--------------------------------------------------+   |
    |   |              ntrl-app                             |   |
    |   |  React Native 0.81.5 + Expo 54 + TypeScript      |   |
    |   |                                                  |   |
    |   |  +-------------+  +---------------+              |   |
    |   |  | iOS App     |  | Android App   |              |   |
    |   |  | (App Store) |  | (Google Play) |              |   |
    |   |  +-------------+  +---------------+              |   |
    |   +--------------------------------------------------+   |
    +----------------------------------------------------------+
```

### Connection Map

```
ntrl-app  --[HTTPS/REST]--> ntrl-api (Railway)
ntrl-api  --[Internal]----> PostgreSQL (Railway)
ntrl-api  --[HTTPS]-------> AWS S3 (us-east-1)
ntrl-api  --[HTTPS]-------> OpenAI API
ntrl-api  --[HTTPS]-------> Google Gemini API
ntrl-api  <--[HTTP POST]--- Railway Cron (every 4 hours)
RSS Feeds --[HTTP GET]----> ntrl-api (Ingestion Service)
```

All connections are encrypted. The PostgreSQL connection uses Railway's internal networking (no public exposure). All external API calls use HTTPS with SSL verification enabled.

---

## 3. Component Inventory

| Component | Platform | Technology | Details |
|-----------|----------|------------|---------|
| Backend API | Railway | FastAPI / Python 3.11 | Auto-deploys from `main`. Build ~1m30s, deploy ~20s |
| Database | Railway PostgreSQL | SQLAlchemy + Alembic | Internal connection, managed by Railway |
| Object Storage | AWS S3 | boto3 | Bucket: `ntrl-raw-content`, Region: `us-east-1` |
| Frontend | Expo / EAS Build | React Native 0.81.5, Expo 54 | iOS and Android native apps |
| LLM (Primary) | OpenAI | gpt-4o-mini | Classification, neutralization, span detection |
| LLM (Fallback) | Google Gemini | gemini-2.0-flash | Classification fallback, span detection fallback |
| LLM (Available) | Anthropic | Claude | Available but not primary; can be activated |
| NLP | spaCy | en_core_web_sm | Lazy-loaded via `@lru_cache` |
| Scheduler | Railway Cron | `0 */4 * * *` | Triggers pipeline every 4 hours |
| Rate Limiting | slowapi | In-process middleware | Per-endpoint limits |
| Caching | cachetools | TTLCache (in-memory) | Per-process, per-endpoint TTLs |
| Config Validation | pydantic-settings | Startup validation | Fail-fast on missing env vars |

---

## 4. Railway (Backend & Database)

### Deployment Configuration

| Aspect | Detail |
|--------|--------|
| Platform | Railway |
| Deployment method | Dockerfile-based |
| Trigger | Auto-deploy on push to `main` |
| Build time | ~1 minute 30 seconds |
| Deploy time | ~20 seconds |
| Runtime | Python 3.11 |
| Web server | Uvicorn (ASGI) |
| Health check | Railway built-in + `/v1/status` endpoint |

### Deployment Flow

```
Developer pushes to main
        |
        v
Railway detects push
        |
        v
Dockerfile build (~1m30s)
        |
        v
Container start
        |
        v
Alembic migrations run automatically (CMD in Dockerfile)
        |
        v
Uvicorn starts, pydantic-settings validates env vars
        |
        v
Application serving traffic (~20s after build completes)
```

### Cron Job

| Setting | Value |
|---------|-------|
| Schedule | `0 */4 * * *` (every 4 hours: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC) |
| Action | `POST /v1/pipeline/scheduled-run` |
| Auth | `X-API-Key` header with admin key |
| Body | `{}` (uses default pipeline parameters) |

The cron job triggers a full 4-stage pipeline run: ingest, classify, neutralize, and brief assembly. Each run creates a `PipelineRunSummary` record with health metrics.

### PostgreSQL Database

| Aspect | Detail |
|--------|--------|
| Provider | Railway managed PostgreSQL |
| Connection | Internal networking (not publicly exposed) |
| Connection string | `DATABASE_URL` env var (auto-set by Railway) |
| ORM | SQLAlchemy (declarative models) |
| Migrations | Alembic (linear chain, single-head required) |
| Backup | Railway managed |

#### Key Tables

| Table | Purpose |
|-------|---------|
| `sources` | RSS feed configurations |
| `stories_raw` | Ingested article metadata |
| `stories_neutralized` | LLM-generated neutral content |
| `transparency_spans` | Simple manipulative phrase annotations |
| `manipulation_spans` | Rich taxonomy-based span annotations |
| `daily_briefs` | Versioned daily brief containers |
| `daily_brief_items` | Individual stories within a brief (denormalized) |
| `pipeline_logs` | Per-stage audit trail |
| `pipeline_run_summaries` | Aggregated health metrics per run |
| `prompts` | Hot-reloadable LLM prompt templates |

#### Database Indexes

Performance-critical indexes are defined on:

| Column(s) | Table | Purpose |
|-----------|-------|---------|
| `url_hash` | `stories_raw` | Deduplication lookups |
| `title_hash` | `stories_raw` | Title-based dedup |
| `published_at` | `stories_raw` | Time-range queries |
| `domain` | `stories_raw` | Classification queries |
| `feed_category` | `stories_raw` | Category grouping |
| `is_current` | `stories_neutralized` | Latest version lookups |
| `neutralization_status` | `stories_neutralized` | Health metric queries |

#### Migration Discipline

Alembic migrations must maintain a single linear chain. The project enforces single-head migrations to prevent branching conflicts:

```bash
# Verify single head before adding a new migration
alembic heads
# Should return exactly one revision

# Create a new migration
alembic revision --autogenerate -m "description"

# Always set down_revision to the current single head
```

A multiple-heads incident in January 2026 required manual resolution. Always verify `alembic heads` returns a single revision before committing a new migration.

---

## 5. AWS S3 (Object Storage)

### Configuration

| Aspect | Detail |
|--------|--------|
| Bucket | `ntrl-raw-content` |
| Region | `us-east-1` |
| Key prefix | `raw/` |
| Content format | gzip-compressed plain text |
| Retention | 30 days (configurable via `RAW_CONTENT_RETENTION_DAYS`) |
| Access | IAM credentials (NOT public) |
| Local fallback | Filesystem-based storage for development |

### S3 Client Tuning

The S3 client is configured with reduced defaults to minimize latency impact on the pipeline:

| Parameter | Value | Default | Rationale |
|-----------|-------|---------|-----------|
| Max retries | 2 | 3 | Reduce tail latency on transient failures |
| Read timeout | 15s | 30s | Fail faster; articles are small text files |
| Download timeout | 8s per article | -- | ThreadPoolExecutor per-task timeout |

### Object Lifecycle

```
INGEST:   Article body extracted --> gzip --> PUT to s3://ntrl-raw-content/raw/{key}
CLASSIFY: GET body from S3 --> read first 2000 chars --> LLM classification
NEUTRALIZE: GET body from S3 --> read full text --> LLM neutralization
EXPIRE:   Objects older than 30 days --> eligible for cleanup
```

### Storage Architecture Diagram

```
+-------------------------------------------+
|          ntrl-raw-content (S3)            |
|          Region: us-east-1                |
|                                           |
|   raw/                                    |
|   +-- {source_slug}/                      |
|       +-- {url_hash}.txt.gz              |
|       +-- {url_hash}.txt.gz              |
|       +-- ...                            |
|                                           |
|   Access: IAM credentials only            |
|   Encryption: S3 default (SSE-S3)         |
|   Versioning: Not enabled                 |
|   Public access: Blocked                  |
+-------------------------------------------+
```

---

## 6. LLM Providers

### Provider Architecture

The system uses a pluggable provider pattern implemented in `app/services/neutralizer/providers/`. Each provider conforms to a common interface for sending prompts and receiving structured JSON responses.

```
+------------------------------------------------------------------+
|                    LLM Provider Architecture                      |
|                                                                  |
|   +------------------+    +------------------+                   |
|   |  Classification  |    |  Neutralization  |                   |
|   |  Request         |    |  Request         |                   |
|   +--------+---------+    +--------+---------+                   |
|            |                       |                             |
|            v                       v                             |
|   +--------------------------------------------------+          |
|   |           Provider Selection Layer                |          |
|   |   (configured via NEUTRALIZER_PROVIDER env var)   |          |
|   +----+----------------+----------------+-----------+          |
|        |                |                |                       |
|   +----v----+     +-----v-----+    +-----v------+               |
|   | OpenAI  |     | Gemini    |    | Anthropic  |               |
|   | Provider|     | Provider  |    | Provider   |               |
|   |         |     |           |    |            |               |
|   | Model:  |     | Model:    |    | Status:    |               |
|   | gpt-4o- |     | gemini-   |    | Available, |               |
|   | mini    |     | 2.0-flash |    | not active |               |
|   +---------+     +-----------+    +------------+               |
|        |                |                                        |
|   PRIMARY          FALLBACK                                      |
+------------------------------------------------------------------+
```

### Provider Priority

| Priority | Provider | Model | Role |
|----------|----------|-------|------|
| Primary | OpenAI | gpt-4o-mini | All operations: classification, neutralization, span detection |
| Fallback | Google Gemini | gemini-2.0-flash | Classification fallback, span detection fallback |
| Available | Anthropic | Claude | Can be activated via provider configuration switch |
| Testing | Mock | -- | Unit tests only; NOT a production fallback (~5% precision) |

### Classification Reliability Chain

The classifier uses a 4-attempt reliability chain to ensure near-100% classification coverage:

```
Attempt 1: gpt-4o-mini (full prompt)
    |
    +-- success --> done
    |
    +-- failure
         |
         v
Attempt 2: gpt-4o-mini (simplified prompt)
    |
    +-- success --> done
    |
    +-- failure
         |
         v
Attempt 3: gemini-2.0-flash (full prompt)
    |
    +-- success --> done
    |
    +-- failure
         |
         v
Attempt 4: enhanced_keyword_classifier (deterministic)
    |
    +-- always succeeds --> done
```

In production, fewer than 1% of articles reach the keyword fallback. Each attempt is logged with the model used, enabling per-provider reliability analysis.

### Neutralization Flow

```
Original body (from S3)
    |
    v
gpt-4o-mini (synthesis mode)
    |
    +-- valid JSON with 6 fields --> success
    |
    +-- garbled/unparseable
         |
         v
    gpt-4o-mini (simplified synthesis fallback)
         |
         +-- valid JSON --> success
         |
         +-- failure --> mark as "failed_garbled"
```

The 6 output fields produced by synthesis: `feed_title`, `feed_summary`, `detail_title`, `detail_brief`, `detail_full`, `spans`.

---

## 7. Frontend Infrastructure

### Build & Distribution

| Aspect | Detail |
|--------|--------|
| Framework | React Native 0.81.5 |
| Platform SDK | Expo 54 |
| Language | TypeScript 5.9 |
| Build system | EAS Build |
| Platforms | iOS (App Store), Android (Google Play) |
| OTA updates | Expo Updates (JS bundle changes) |
| Unit testing | Jest + React Testing Library |
| E2E testing | Playwright |

### Environment Selection

The frontend determines which API backend to target based on the `EXPO_PUBLIC_ENV` environment variable, resolved through `src/config/index.ts`:

```
EXPO_PUBLIC_ENV="staging"   --> api-staging-7b4d.up.railway.app
EXPO_PUBLIC_ENV="production" --> production API URL
```

### Build Process

```
Developer triggers EAS Build
        |
        v
EAS cloud build (iOS + Android)
        |
        +-- iOS: .ipa artifact --> App Store Connect --> App Store
        |
        +-- Android: .aab artifact --> Google Play Console --> Play Store
```

---

## 8. Environment Configuration

### Railway Environment Variables

All environment variables are managed through the Railway dashboard. Secrets must never be committed to the repository.

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string | Yes (auto-set by Railway) | -- |
| `NEUTRALIZER_PROVIDER` | Active LLM provider | Yes | `"openai"` |
| `OPENAI_API_KEY` | OpenAI API key | Yes | -- |
| `OPENAI_MODEL` | OpenAI model name | Optional | `"gpt-4o-mini"` |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | Google API key (fallback provider) | Recommended | -- |
| `ANTHROPIC_API_KEY` | Anthropic API key | Optional | -- |
| `STORAGE_PROVIDER` | Storage backend | Yes | `"s3"` |
| `S3_BUCKET` | S3 bucket name | Yes | `"ntrl-raw-content"` |
| `S3_REGION` | S3 bucket region | Yes | `"us-east-1"` |
| `AWS_ACCESS_KEY_ID` | AWS IAM access key | Yes | -- |
| `AWS_SECRET_ACCESS_KEY` | AWS IAM secret key | Yes | -- |
| `ADMIN_API_KEY` | Admin endpoint authentication key | Yes | -- |
| `RAW_CONTENT_RETENTION_DAYS` | S3 object retention | Yes | `"30"` |
| `ENVIRONMENT` | Runtime environment | Yes | `"staging"` or `"production"` |

### Configuration Validation

At startup, `pydantic-settings` validates every environment variable. If any required variable is missing or has an invalid value, the application crashes immediately with a descriptive error. This fail-fast behavior prevents the system from running in a misconfigured state.

```
Application start
    |
    v
pydantic-settings loads env vars
    |
    +-- All valid --> continue boot
    |
    +-- Missing/invalid --> crash with error message
         (e.g., "OPENAI_API_KEY: field required")
```

### Environment-Specific Behavior

| Behavior | Staging | Production |
|----------|---------|------------|
| Reset endpoint | Enabled | Disabled |
| Debug endpoints | Enabled | Enabled (auth required) |
| Error detail in responses | Sanitized | Sanitized |
| Auto-deploy trigger | Push to `main` | Push to `main` |

---

## 9. Networking & Data Flow

### Network Topology

```
+------------------+          +----------------------------+
|   Mobile Client  |          |        INTERNET            |
|   (iOS/Android)  |--------->|                            |
+------------------+   HTTPS  |   +--------------------+   |
                              |   | Railway Edge       |   |
                              |   | (TLS termination)  |   |
                              |   +---------+----------+   |
                              |             |              |
                              +-------------|-------------+
                                            |
                              +-------------|-------------+
                              |   RAILWAY INTERNAL NET    |
                              |             |              |
                              |   +---------v----------+   |
                              |   | ntrl-api           |   |
                              |   | (Uvicorn/FastAPI)  |   |
                              |   +---------+----------+   |
                              |             |              |
                              |   +---------v----------+   |
                              |   | PostgreSQL         |   |
                              |   | (internal only)    |   |
                              |   +--------------------+   |
                              +----------------------------+
                                            |
                                   HTTPS (outbound)
                                            |
                              +-------------+-------------+
                              |             |             |
                        +-----v---+  +------v----+  +----v------+
                        | AWS S3  |  | OpenAI    |  | Google    |
                        |         |  | API       |  | Gemini    |
                        +---------+  +-----------+  +-----------+
```

### Inbound Traffic

| Source | Destination | Protocol | Auth |
|--------|-------------|----------|------|
| Mobile app | `/v1/brief`, `/v1/stories/*` | HTTPS | None (public) |
| Mobile app | `/v1/sources` | HTTPS | None (public) |
| Railway cron | `/v1/pipeline/scheduled-run` | HTTP (internal) | `X-API-Key` |
| Admin (manual) | `/v1/admin/*` | HTTPS | `X-API-Key` |

### Outbound Traffic

| Source | Destination | Protocol | Purpose |
|--------|-------------|----------|---------|
| ntrl-api | RSS feeds | HTTPS (SSL verified) | Article ingestion |
| ntrl-api | AWS S3 | HTTPS | Body storage and retrieval |
| ntrl-api | OpenAI API | HTTPS | Classification and neutralization |
| ntrl-api | Google Gemini API | HTTPS | Fallback classification |
| ntrl-api | PostgreSQL | Internal TCP | Data persistence |

### Pipeline Data Flow

```
                    +-------------+
                    |  RSS Feeds  |  (External)
                    +------+------+
                           |
                    [STAGE 1: INGEST]
                     Max 25/source
                           |
               +-----------+-----------+
               |                       |
        +------v------+        +------v------+
        | PostgreSQL  |        |   AWS S3    |
        | StoryRaw    |        |  body.txt   |
        | (metadata)  |        |  (gzipped)  |
        +------+------+        +------+------+
               |                       |
               +-----------+-----------+
                           |
                    [STAGE 2: CLASSIFY]
                     Max 200/run
                           |
                    Read first 2000 chars from S3
                           |
                    LLM reliability chain (4 attempts)
                           |
                    domain (1/20) + feed_category (1/10)
                           |
                    [STAGE 3: NEUTRALIZE]
                     Max 25/run
                           |
                    Read full body from S3
                           |
                    LLM synthesis --> 6 output fields + spans
                           |
                    [STAGE 4: BRIEF ASSEMBLE]
                           |
                    Group by feed_category (10 categories)
                    Fixed order: World, U.S., Local, ...
                           |
                    DailyBrief (versioned) + DailyBriefItems
                           |
                    [CACHE INVALIDATION]
                           |
                    Brief cache cleared --> fresh on next GET
```

---

## 10. Rate Limiting & Caching

### Rate Limiting

Rate limits are enforced in-process via `slowapi` middleware. Limits apply per IP address.

| Scope | Limit | Endpoints |
|-------|-------|-----------|
| Global (public) | 100 requests/minute | All public endpoints |
| Admin endpoints | 10 requests/minute | `/v1/admin/*` |
| Pipeline triggers | 5 requests/minute | `POST /v1/pipeline/*`, `POST /v1/admin/pipeline` |

Exceeded limits return HTTP 429 with a `Retry-After` header.

### Caching

In-memory caching via `cachetools.TTLCache` (per-process, not shared across instances):

| Cache | TTL | Max Entries | Scope |
|-------|-----|-------------|-------|
| Brief response | 15 minutes | 10 | `GET /v1/brief`, `GET /v1/brief/latest` |
| Story detail | 1 hour | 200 | `GET /v1/stories/{id}` |
| Transparency data | 1 hour | 200 | `GET /v1/stories/{id}/transparency` |

#### Cache Behavior

- Responses include `Cache-Control` headers with appropriate `max-age` values.
- `X-Cache: HIT` or `X-Cache: MISS` header indicates cache status on each response.
- Brief cache is explicitly invalidated after `POST /v1/brief/run` and `POST /v1/admin/pipeline` to ensure fresh data is served immediately after a pipeline run.
- Caches are per-process and in-memory. A redeploy clears all caches.

```
Client request
    |
    v
Check TTLCache for key
    |
    +-- HIT --> return cached response (X-Cache: HIT)
    |
    +-- MISS --> execute handler
                    |
                    v
                Store in TTLCache
                    |
                    v
                Return response (X-Cache: MISS)
```

---

## 11. Security Posture

### Authentication

| Mechanism | Scope | Implementation |
|-----------|-------|----------------|
| API key (`X-API-Key` header) | Admin endpoints | `secrets.compare_digest` (timing-safe) |
| No auth | Public endpoints | Brief, stories, sources |

Admin authentication uses timing-safe comparison to prevent timing side-channel attacks. If `ADMIN_API_KEY` is not set in the environment, all admin requests are denied (fail-closed).

### Network Security

| Control | Detail |
|---------|--------|
| TLS | All inbound traffic is TLS-terminated at Railway's edge |
| SSL verification | Enabled on all outbound HTTP requests (RSS fetches, S3, LLM APIs) |
| Database access | Internal Railway networking only; no public endpoint |
| S3 access | IAM credentials; bucket is not publicly readable |
| CORS | Restricted to explicitly configured origins |

### Application Security

| Control | Detail |
|---------|--------|
| Error sanitization | No stack traces, file paths, or internal identifiers in API responses |
| Config validation | pydantic-settings fails fast on missing/invalid config |
| Dependency pinning | All versions pinned in `Pipfile.lock` + `requirements.txt` safety net |
| Reset endpoint | Disabled when `ENVIRONMENT=production` |
| Secrets management | All secrets in Railway environment variables, never in code |

### Security Diagram

```
+---------------------------------------------------------------+
|                     Security Boundaries                        |
|                                                               |
|   PUBLIC (no auth)          ADMIN (API key required)          |
|   +-------------------+    +----------------------------+     |
|   | GET /v1/brief     |    | POST /v1/admin/*           |     |
|   | GET /v1/stories/* |    | POST /v1/pipeline/*        |     |
|   | GET /v1/sources   |    | GET  /v1/status            |     |
|   +-------------------+    +----------------------------+     |
|           |                         |                         |
|           v                         v                         |
|   +---------------------------------------------------+       |
|   |              Rate Limiting (slowapi)               |       |
|   |  Public: 100/min    Admin: 10/min    Pipe: 5/min  |       |
|   +---------------------------------------------------+       |
|           |                                                   |
|           v                                                   |
|   +---------------------------------------------------+       |
|   |              CORS Middleware                       |       |
|   |  Configured origins only                          |       |
|   +---------------------------------------------------+       |
|           |                                                   |
|           v                                                   |
|   +---------------------------------------------------+       |
|   |         Global Exception Handler                  |       |
|   |  Sanitized responses (no internal details)        |       |
|   +---------------------------------------------------+       |
+---------------------------------------------------------------+
```

---

## 12. Monitoring & Alerting

### Health Endpoint

`GET /v1/status` returns comprehensive system health information:

- System status and uptime
- LLM configuration (active provider, model)
- API key presence (not values)
- Article counts (ingested, classified, neutralized)
- Last pipeline run info (timing, counts, errors)
- Health metrics and active alerts

### Pipeline Health Metrics

Each pipeline run produces a `PipelineRunSummary` with:

| Metric | Description | Threshold |
|--------|-------------|-----------|
| `body_download_rate` | Percentage of articles with successfully downloaded bodies | Must be >= 70% |
| `neutralization_rate` | Percentage of articles successfully neutralized | Must be >= 90% |
| `brief_story_count` | Number of stories in the assembled brief | Must be >= 10 |

### Alert Codes

| Alert Code | Condition | Severity |
|------------|-----------|----------|
| `CLASSIFY_FALLBACK_RATE_HIGH` | Keyword fallback used for >1% of articles | Warning |

### Logging

| Log Category | Prefix | Purpose |
|-------------|--------|---------|
| Span detection | `[SPAN_DETECTION]` | Structured logs for manipulation span identification |
| Pipeline stages | Stage name | Per-stage success/failure logging |
| LLM calls | Provider name | Request/response timing, model used |

### Pipeline Observability Model

```
Pipeline Run
    |
    +-- PipelineRunSummary (aggregated metrics)
    |       stories_ingested
    |       stories_classified
    |       stories_neutralized
    |       errors (JSON)
    |       run_started_at / run_completed_at
    |
    +-- PipelineLog entries (per-stage audit trail)
    |       stage: ingest | classify | neutralize | brief_assemble
    |       status: success | failure
    |       message + metadata (JSON)
    |
    +-- StoryRaw records
    |       classification_method: llm | keyword
    |       classification_model: gpt-4o-mini | gemini-2.0-flash | keyword
    |
    +-- StoryNeutralized records
            neutralization_status:
                success | failed_llm | failed_garbled | failed_audit | skipped
```

### Useful Health Queries

**Neutralization success rate for today:**

```sql
SELECT
    neutralization_status,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM story_neutralized
WHERE created_at >= CURRENT_DATE
GROUP BY neutralization_status;
```

**Classification method distribution:**

```sql
SELECT
    classification_method,
    classification_model,
    COUNT(*) as count
FROM story_raw
WHERE classified_at >= CURRENT_DATE
GROUP BY classification_method, classification_model;
```

---

## 13. Staging Environment

| Aspect | Detail |
|--------|--------|
| URL | `https://api-staging-7b4d.up.railway.app` |
| Admin API Key | `$ADMIN_API_KEY` |
| Deploy trigger | Auto-deploy from `main` branch |
| Database | Separate Railway PostgreSQL instance |
| S3 bucket | Shared `ntrl-raw-content` (same as production, different key prefixes) |

### Staging Verification Commands

**Check system status:**

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/status" \
  -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool
```

**Check brief has content:**

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/brief"
```

**Trigger manual pipeline run:**

```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -d '{}'
```

---

## 14. Development Limits & Production Scaling

### Current Limits (Staging/Development)

| Parameter | Current Value | Pipeline Stage |
|-----------|---------------|----------------|
| `max_items_per_source` | 25 articles | Ingestion |
| `classify_limit` | 200 articles | Classification |
| `neutralize_limit` | 25 articles | Neutralization |
| `cutoff_hours` | 24 hours | Brief assembly |

### Production Targets

| Parameter | Target Value | Rationale |
|-----------|--------------|-----------|
| `max_items_per_source` | 50+ | Cover more articles per feed |
| `neutralize_limit` | 100+ | Ensure adequate daily brief content |
| `classify_limit` | 500+ | Match increased ingestion volume |

### Scaling Diagram

```
              CURRENT (Development)              TARGET (Production)
              =====================              ====================

Ingest:       25/source/run                      50+/source/run
                    |                                    |
                    v                                    v
Classify:     200/run                            500+/run
                    |                                    |
                    v                                    v
Neutralize:   25/run                             100+/run
                    |                                    |
                    v                                    v
Brief:        Last 24 hours                      Last 24 hours
              (~50-100 stories)                  (~200-500 stories)
```

### Production Readiness Checklist

- [ ] Increase `max_items_per_source` to 50+
- [ ] Increase `neutralize_limit` to 100+
- [ ] Increase `classify_limit` to 500+
- [ ] Set `ENVIRONMENT=production` in Railway
- [ ] Verify all API keys are production keys (not staging/test)
- [ ] Confirm `ADMIN_API_KEY` is a strong, unique secret
- [ ] Review cron frequency (every 4 hours may need adjustment)
- [ ] Validate S3 retention policy (`RAW_CONTENT_RETENTION_DAYS`)
- [ ] Confirm rollback procedure is understood by all operators
- [ ] Verify reset endpoint is disabled (`ENVIRONMENT=production`)

---

## 15. Operational Reference

### Quick Reference: Infrastructure Access

| Resource | How to Access |
|----------|---------------|
| Railway dashboard | Railway web console |
| PostgreSQL | `railway connect` CLI or Railway dashboard |
| S3 bucket | AWS Console or `aws s3` CLI with IAM credentials |
| Application logs | Railway dashboard (Deployments > Logs) |
| Cron job status | Railway dashboard (Cron section) |
| EAS builds | Expo dashboard |

### Quick Reference: Key URLs

| Environment | URL |
|-------------|-----|
| Staging API | `https://api-staging-7b4d.up.railway.app` |
| Status endpoint | `https://api-staging-7b4d.up.railway.app/v1/status` |
| Brief endpoint | `https://api-staging-7b4d.up.railway.app/v1/brief` |

### Quick Reference: Scheduled Operations

| Operation | Schedule | Mechanism |
|-----------|----------|-----------|
| Pipeline run | Every 4 hours (`0 */4 * * *`) | Railway cron |
| S3 cleanup | 30-day retention | Configurable via `RAW_CONTENT_RETENTION_DAYS` |
| Cache expiry | 15min (brief), 1hr (stories) | In-memory TTLCache auto-eviction |

### Incident Response

**Pipeline not producing content:**

1. Check `/v1/status` for errors and last run time.
2. Check Railway cron job is active.
3. Check `PipelineRunSummary` for recent failures.
4. Verify LLM API keys are valid (check Railway env vars).
5. Trigger manual pipeline run and observe output.

**High keyword fallback rate (>1% of classifications):**

1. Check `CLASSIFY_FALLBACK_RATE_HIGH` alert in pipeline summaries.
2. Verify OpenAI API key is valid and has quota.
3. Verify Gemini API key is valid and has quota.
4. Check classification model responses in pipeline logs.

**S3 download failures:**

1. Check `body_download_rate` in pipeline summaries (threshold: 70%).
2. Verify AWS credentials in Railway env vars.
3. Check S3 bucket permissions.
4. Review S3 client timeout settings (read_timeout: 15s, per-article: 8s).

**Database migration failure:**

1. Check Railway deploy logs for Alembic errors.
2. Verify single migration head: `railway run alembic heads`.
3. If multiple heads, resolve manually (merge or rebase migrations).
4. Rollback via Railway dashboard if the deploy is unhealthy.
