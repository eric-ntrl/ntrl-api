# NTRL API Reference

Complete reference for all NTRL API endpoints. The API is organized into two versions:

- **V1** -- Core news pipeline endpoints (brief, stories, sources, admin)
- **V2** -- Standalone article processing endpoints (scan, process, batch, transparency)

Base URL: configured per environment (e.g., `https://api.ntrl.news` or `http://localhost:8000`).

---

## Table of Contents

- [Authentication](#authentication)
- [Rate Limiting](#rate-limiting)
- [Caching](#caching)
- [V1 Endpoints](#v1-endpoints)
  - [Brief](#brief)
  - [Stories](#stories)
  - [Sources](#sources)
  - [Admin](#admin)
  - [Prompts](#prompts)
- [V2 Endpoints](#v2-endpoints)
  - [Scan](#post-v2scan)
  - [Process](#post-v2process)
  - [Batch](#post-v2batch)
  - [Transparency](#post-v2transparency)
- [Error Responses](#error-responses)

---

## Authentication

Admin endpoints (all under `/v1/` prefixed with admin operations) require an API key passed via the `X-API-Key` HTTP header.

- The key is validated using timing-safe comparison (`secrets.compare_digest`) to prevent timing attacks.
- If the `ADMIN_API_KEY` environment variable is not set, authentication **fails closed** -- all admin requests are rejected.

```
X-API-Key: <your-admin-api-key>
```

Public endpoints (`GET /v1/brief`, `GET /v1/stories/*`) do not require authentication.

---

## Rate Limiting

| Scope | Limit |
|-------|-------|
| Global (all endpoints) | 100 requests / minute |
| Admin endpoints | 10 requests / minute |
| Pipeline triggers (`/v1/pipeline/*`, `/v1/ingest/run`, etc.) | 5 requests / minute |

Exceeding the limit returns `429 Too Many Requests`.

---

## Caching

Server-side response caching is applied to select read endpoints. Cached responses include the `X-Cache` header indicating `HIT` or `MISS`.

| Endpoint | TTL | Max Entries | Invalidation Trigger |
|----------|-----|-------------|----------------------|
| `GET /v1/brief` | 15 minutes | 10 | `POST /v1/brief/run` |
| `GET /v1/stories/{story_id}` | 1 hour | 200 | None |
| `GET /v1/stories/{story_id}/transparency` | 1 hour | 200 | None |

---

## V1 Endpoints

### Brief

#### GET /v1/brief

Returns the current daily brief -- a curated collection of neutralized stories organized by section.

**Authentication:** None

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `hours` | integer | No | None | Filter to stories published within the last N hours. Must be between 1 and 168 (7 days). |

**Response:** `200 OK`

```json
{
  "id": "uuid-string",
  "brief_date": "2026-01-28",
  "cutoff_time": "2026-01-27T12:00:00Z",
  "assembled_at": "2026-01-28T06:30:00Z",
  "sections": [
    {
      "name": "politics",
      "display_name": "Politics",
      "order": 1,
      "stories": [
        {
          "id": "uuid-string",
          "feed_title": "Neutralized headline text",
          "feed_summary": "One-paragraph neutralized summary of the article.",
          "source_name": "Example News",
          "source_url": "https://example.com/article",
          "published_at": "2026-01-28T03:15:00Z",
          "has_manipulative_content": true,
          "position": 1,
          "detail_title": "Full neutralized title",
          "detail_brief": "Multi-paragraph neutralized brief",
          "detail_full": "Full neutralized article body",
          "disclosure": "This article contained emotional language that was neutralized."
        }
      ],
      "story_count": 5
    }
  ],
  "total_stories": 25,
  "is_empty": false,
  "empty_message": null
}
```

**Error Responses:**

- `404 Not Found` -- No brief is currently available.

**Example:**

```bash
# Get the current brief
curl -s https://api.ntrl.news/v1/brief

# Get the brief filtered to the last 6 hours
curl -s "https://api.ntrl.news/v1/brief?hours=6"
```

---

### Stories

#### GET /v1/stories

List stories with before/after comparison data. Supports filtering by source and neutralization status.

**Authentication:** None

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source_slug` | string | No | None | Filter stories by source slug (e.g., `nytimes`). |
| `neutralized_only` | boolean | No | None | If true, return only neutralized stories. |
| `limit` | integer | No | 50 | Maximum number of stories to return. |
| `offset` | integer | No | 0 | Number of stories to skip for pagination. |

**Response:** `200 OK`

```json
{
  "stories": [
    {
      "id": "uuid-string",
      "original_title": "Original headline from the source",
      "original_description": "Original description or lede from the RSS feed",
      "feed_title": "Neutralized headline",
      "feed_summary": "Neutralized summary paragraph",
      "source_name": "Example News",
      "source_slug": "example-news",
      "source_url": "https://example.com/article",
      "published_at": "2026-01-28T03:15:00Z",
      "section": "politics",
      "has_manipulative_content": true,
      "is_neutralized": true
    }
  ],
  "total": 142
}
```

**Example:**

```bash
# List all stories (default limit 50)
curl -s https://api.ntrl.news/v1/stories

# List neutralized stories from a specific source
curl -s "https://api.ntrl.news/v1/stories?source_slug=nytimes&neutralized_only=true&limit=20"

# Paginate results
curl -s "https://api.ntrl.news/v1/stories?limit=10&offset=10"
```

---

#### GET /v1/stories/{story_id}

Get the full detail view for a single story.

**Authentication:** None

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `story_id` | string (UUID) | The unique identifier of the story. |

**Response:** `200 OK`

```json
{
  "id": "uuid-string",
  "feed_title": "Neutralized headline",
  "feed_summary": "Neutralized summary paragraph",
  "detail_title": "Full neutralized title for the detail view",
  "detail_brief": "Multi-paragraph neutralized brief for medium-depth reading",
  "detail_full": "Complete neutralized article body",
  "disclosure": "This article contained loaded language and framing bias that was neutralized.",
  "has_manipulative_content": true,
  "source_name": "Example News",
  "source_url": "https://example.com/article",
  "published_at": "2026-01-28T03:15:00Z",
  "section": "politics"
}
```

**Caching:** 1-hour TTL. Check `X-Cache` response header.

**Example:**

```bash
curl -s https://api.ntrl.news/v1/stories/550e8400-e29b-41d4-a716-446655440000
```

---

#### GET /v1/stories/{story_id}/transparency

Get the full transparency view for a story, including original text, neutralized text, and annotated manipulation spans showing exactly what was changed and why.

**Authentication:** None

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `story_id` | string (UUID) | The unique identifier of the story. |

**Response:** `200 OK`

```json
{
  "id": "uuid-string",
  "original_title": "Original headline with loaded language",
  "original_description": "Original RSS description",
  "original_body": "Full original article body text...",
  "original_body_available": true,
  "original_body_expired": false,
  "feed_title": "Neutralized headline",
  "feed_summary": "Neutralized summary",
  "detail_full": "Full neutralized article body",
  "spans": [
    {
      "start_char": 45,
      "end_char": 62,
      "original_text": "slammed critics",
      "action": "replace",
      "reason": "Emotionally loaded verb implying aggression",
      "replacement_text": "responded to critics"
    },
    {
      "start_char": 130,
      "end_char": 155,
      "original_text": "radical policy overhaul",
      "action": "replace",
      "reason": "Loaded adjective framing the policy negatively",
      "replacement_text": "significant policy change"
    }
  ],
  "disclosure": "This article contained emotionally loaded language that was neutralized.",
  "has_manipulative_content": true,
  "source_url": "https://example.com/article",
  "model_name": "claude-sonnet-4-20250514",
  "prompt_version": "v3.2",
  "processed_at": "2026-01-28T06:00:00Z"
}
```

**Span Object Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `start_char` | integer | Starting character index in the original body. |
| `end_char` | integer | Ending character index in the original body. |
| `original_text` | string | The exact text from the original that was flagged. |
| `action` | string | The action taken (e.g., `replace`, `remove`, `rephrase`). |
| `reason` | string | Human-readable explanation of why this text was flagged. |
| `replacement_text` | string | The neutralized replacement text. |

**Caching:** 1-hour TTL. Check `X-Cache` response header.

**Example:**

```bash
curl -s https://api.ntrl.news/v1/stories/550e8400-e29b-41d4-a716-446655440000/transparency
```

---

#### GET /v1/stories/{story_id}/debug

Debug endpoint that returns truncated content and diagnostic information for a story.

**Authentication:** None

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `story_id` | string (UUID) | The unique identifier of the story. |

**Response:** `200 OK`

```json
{
  "story_id": "uuid-string",
  "original_body": "First 500 characters of the original body...",
  "original_body_length": 4250,
  "original_body_available": true,
  "detail_full": "First 500 characters of the neutralized full text...",
  "detail_full_length": 4100,
  "detail_brief": "First 500 characters of the neutralized brief...",
  "detail_brief_length": 1200,
  "span_count": 7,
  "spans_sample": [
    {
      "start_char": 45,
      "end_char": 62,
      "original_text": "slammed critics",
      "action": "replace",
      "reason": "Emotionally loaded verb",
      "replacement_text": "responded to critics"
    }
  ],
  "model_used": "claude-sonnet-4-20250514",
  "has_manipulative_content": true,
  "detail_full_readable": true,
  "issues": []
}
```

**Notes:**
- `original_body` and `detail_full` are truncated to 500 characters.
- `spans_sample` includes up to 3 spans.
- `issues` lists any detected problems (e.g., missing body, zero spans when manipulation flagged).

**Example:**

```bash
curl -s https://api.ntrl.news/v1/stories/550e8400-e29b-41d4-a716-446655440000/debug
```

---

#### GET /v1/stories/{story_id}/debug/spans

Run fresh span detection on a story and return full diagnostic trace of the detection pipeline. Useful for debugging why spans were or were not found.

**Authentication:** None

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `story_id` | string (UUID) | The unique identifier of the story. |

**Response:** `200 OK`

```json
{
  "story_id": "uuid-string",
  "original_body_preview": "First portion of original body...",
  "original_body_length": 4250,
  "llm_raw_response": "Raw text returned by the LLM for span detection",
  "llm_phrases_count": 12,
  "llm_phrases": [
    "slammed critics",
    "radical policy overhaul",
    "devastating blow"
  ],
  "pipeline_trace": {
    "after_position_matching": 10,
    "after_quote_filter": 9,
    "after_false_positive_filter": 7,
    "phrases_not_found_in_text": ["phrase that didn't match"],
    "phrases_filtered_by_quotes": ["quoted phrase removed"],
    "phrases_filtered_as_false_positives": ["acceptable phrase removed"]
  },
  "final_span_count": 7,
  "final_spans": [
    {
      "start_char": 45,
      "end_char": 62,
      "original_text": "slammed critics",
      "action": "replace",
      "reason": "Emotionally loaded verb",
      "replacement_text": "responded to critics"
    }
  ],
  "model_used": "claude-sonnet-4-20250514"
}
```

**Pipeline Trace Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `after_position_matching` | integer | Spans remaining after matching LLM phrases to positions in text. |
| `after_quote_filter` | integer | Spans remaining after removing phrases inside direct quotes. |
| `after_false_positive_filter` | integer | Spans remaining after removing false positives. |
| `phrases_not_found_in_text` | string[] | Phrases the LLM flagged but could not be located in the text. |
| `phrases_filtered_by_quotes` | string[] | Phrases removed because they appeared inside direct quotes. |
| `phrases_filtered_as_false_positives` | string[] | Phrases removed by the false-positive filter. |

**Example:**

```bash
curl -s https://api.ntrl.news/v1/stories/550e8400-e29b-41d4-a716-446655440000/debug/spans
```

---

### Sources

#### GET /v1/sources

List all configured RSS sources.

**Authentication:** None

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `active_only` | boolean | No | None | If true, return only active sources. |

**Response:** `200 OK`

```json
{
  "sources": [
    {
      "id": "uuid-string",
      "name": "Example News",
      "slug": "example-news",
      "rss_url": "https://example.com/rss/feed.xml",
      "default_section": "politics",
      "is_active": true,
      "created_at": "2026-01-15T10:00:00Z"
    }
  ],
  "total": 12
}
```

**Example:**

```bash
# List all sources
curl -s https://api.ntrl.news/v1/sources

# List only active sources
curl -s "https://api.ntrl.news/v1/sources?active_only=true"
```

---

#### POST /v1/sources

Add a new RSS source.

**Authentication:** None

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `name` | string | Yes | -- | Display name for the source. |
| `slug` | string | Yes | -- | URL-safe unique identifier (e.g., `nytimes`). |
| `rss_url` | string | Yes | -- | Full URL to the RSS feed. |
| `default_section` | string | No | None | Default section for stories from this source. |
| `is_active` | boolean | No | true | Whether the source is active for ingestion. |

**Response:** `201 Created`

```json
{
  "id": "uuid-string",
  "name": "Example News",
  "slug": "example-news",
  "rss_url": "https://example.com/rss/feed.xml",
  "default_section": "politics",
  "is_active": true,
  "created_at": "2026-01-28T12:00:00Z"
}
```

**Error Responses:**

- `409 Conflict` -- A source with the given slug already exists.

**Example:**

```bash
curl -s -X POST https://api.ntrl.news/v1/sources \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Example News",
    "slug": "example-news",
    "rss_url": "https://example.com/rss/feed.xml",
    "default_section": "politics"
  }'
```

---

#### DELETE /v1/sources/{slug}

Remove or deactivate a source. If the source has associated stories, it is deactivated rather than deleted to preserve referential integrity.

**Authentication:** None

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `slug` | string | The unique slug of the source to remove. |

**Response:** `204 No Content`

No response body.

**Example:**

```bash
curl -s -X DELETE https://api.ntrl.news/v1/sources/example-news
```

---

### Admin

All admin endpoints require the `X-API-Key` header.

#### GET /v1/status

Returns system health, configuration, and pipeline statistics.

**Authentication:** Required (`X-API-Key`)

**Response:** `200 OK`

```json
{
  "status": "operational",
  "health": "healthy",
  "code_version": "1.4.2",
  "neutralizer_provider": "anthropic",
  "neutralizer_model": "claude-sonnet-4-20250514",
  "neutralizer_error": null,
  "has_google_api_key": false,
  "has_openai_api_key": true,
  "has_anthropic_api_key": true,
  "has_aws_credentials": true,
  "s3_bucket": "ntrl-storage-prod",
  "total_articles_ingested": 15420,
  "total_articles_neutralized": 12890,
  "total_sources": 18,
  "last_ingest": "2026-01-28T06:00:00Z",
  "last_neutralize": "2026-01-28T06:05:00Z",
  "last_brief": "2026-01-28T06:30:00Z",
  "latest_pipeline_run": "2026-01-28T06:00:00Z",
  "thresholds": {}
}
```

**Example:**

```bash
curl -s https://api.ntrl.news/v1/status \
  -H "X-API-Key: $ADMIN_API_KEY"
```

---

#### POST /v1/ingest/run

Trigger RSS feed ingestion. Fetches new articles from configured sources.

**Authentication:** Required (`X-API-Key`)

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `source_slugs` | string[] | No | All active sources | Limit ingestion to specific sources by slug. |
| `max_items_per_source` | integer | No | None | Maximum articles to ingest per source. |

**Response:** `200 OK`

```json
{
  "status": "completed",
  "started_at": "2026-01-28T06:00:00Z",
  "finished_at": "2026-01-28T06:00:45Z",
  "duration_ms": 45000,
  "sources_processed": 12,
  "total_ingested": 87,
  "total_skipped_duplicate": 23,
  "source_results": [
    {
      "source_slug": "nytimes",
      "ingested": 8,
      "skipped_duplicate": 3
    }
  ],
  "errors": []
}
```

**Example:**

```bash
# Ingest from all sources
curl -s -X POST https://api.ntrl.news/v1/ingest/run \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'

# Ingest from specific sources with a cap
curl -s -X POST https://api.ntrl.news/v1/ingest/run \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "source_slugs": ["nytimes", "washpost"],
    "max_items_per_source": 10
  }'
```

---

#### POST /v1/classify/run

Trigger article classification. Assigns sections and flags articles for neutralization.

**Authentication:** Required (`X-API-Key`)

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `limit` | integer | No | 25 | Maximum number of articles to classify. |
| `force` | boolean | No | false | Re-classify already-classified articles. |
| `story_ids` | string[] | No | None | Classify specific stories by ID. |

**Response:** `200 OK`

```json
{
  "status": "completed",
  "started_at": "2026-01-28T06:01:00Z",
  "finished_at": "2026-01-28T06:01:30Z",
  "duration_ms": 30000,
  "classify_total": 25,
  "classify_success": 23,
  "classify_llm": 20,
  "classify_keyword_fallback": 3,
  "classify_failed": 2,
  "errors": []
}
```

**Response Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `classify_total` | integer | Total articles attempted. |
| `classify_success` | integer | Successfully classified articles. |
| `classify_llm` | integer | Articles classified by the LLM. |
| `classify_keyword_fallback` | integer | Articles classified using keyword fallback when the LLM failed. |
| `classify_failed` | integer | Articles that could not be classified. |

**Example:**

```bash
curl -s -X POST https://api.ntrl.news/v1/classify/run \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 50}'
```

---

#### POST /v1/neutralize/run

Trigger the neutralization pipeline on classified articles.

**Authentication:** Required (`X-API-Key`)

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `story_ids` | string[] | No | None | Neutralize specific stories by ID. |
| `force` | boolean | No | false | Re-neutralize already-neutralized articles. |
| `limit` | integer | No | None | Maximum number of articles to neutralize. |
| `max_workers` | integer | No | None | Maximum concurrent workers for parallel processing. |

**Response:** `200 OK`

```json
{
  "status": "completed",
  "started_at": "2026-01-28T06:02:00Z",
  "finished_at": "2026-01-28T06:04:30Z",
  "duration_ms": 150000,
  "total_processed": 45,
  "total_skipped": 5,
  "total_failed": 2,
  "story_results": [
    {
      "story_id": "uuid-string",
      "status": "success",
      "has_manipulative_content": true,
      "span_count": 7
    }
  ]
}
```

**Example:**

```bash
# Neutralize up to 100 articles with 5 workers
curl -s -X POST https://api.ntrl.news/v1/neutralize/run \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 100, "max_workers": 5}'

# Force re-neutralize a specific story
curl -s -X POST https://api.ntrl.news/v1/neutralize/run \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "story_ids": ["550e8400-e29b-41d4-a716-446655440000"],
    "force": true
  }'
```

---

#### POST /v1/brief/run

Trigger assembly of a new daily brief from neutralized stories.

**Authentication:** Required (`X-API-Key`)

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `cutoff_hours` | integer | No | None | Include stories from the last N hours. |
| `force` | boolean | No | false | Rebuild the brief even if one already exists for today. |

**Response:** `200 OK`

```json
{
  "status": "completed",
  "started_at": "2026-01-28T06:30:00Z",
  "finished_at": "2026-01-28T06:30:05Z",
  "duration_ms": 5000,
  "brief_id": "uuid-string",
  "brief_date": "2026-01-28",
  "cutoff_time": "2026-01-27T06:30:00Z",
  "total_stories": 25,
  "is_empty": false,
  "empty_reason": null,
  "sections": [
    {
      "name": "politics",
      "story_count": 8
    },
    {
      "name": "technology",
      "story_count": 5
    }
  ],
  "error": null
}
```

**Example:**

```bash
# Assemble a new brief
curl -s -X POST https://api.ntrl.news/v1/brief/run \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'

# Force rebuild with custom cutoff
curl -s -X POST https://api.ntrl.news/v1/brief/run \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"cutoff_hours": 12, "force": true}'
```

---

#### POST /v1/pipeline/run

Run the full pipeline end-to-end: ingest, classify, neutralize, and assemble the brief.

**Authentication:** Required (`X-API-Key`)

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `max_items_per_source` | integer | No | 20 | Maximum articles to ingest per source. |
| `classify_limit` | integer | No | 200 | Maximum articles to classify. |
| `neutralize_limit` | integer | No | 100 | Maximum articles to neutralize. |
| `max_workers` | integer | No | 5 | Maximum concurrent neutralization workers. |
| `cutoff_hours` | integer | No | 24 | Brief cutoff window in hours. |

**Response:** `200 OK`

```json
{
  "status": "completed",
  "started_at": "2026-01-28T06:00:00Z",
  "finished_at": "2026-01-28T06:10:00Z",
  "total_duration_ms": 600000,
  "stages": [
    {
      "name": "ingest",
      "status": "completed",
      "duration_ms": 45000
    },
    {
      "name": "classify",
      "status": "completed",
      "duration_ms": 30000
    },
    {
      "name": "neutralize",
      "status": "completed",
      "duration_ms": 480000
    },
    {
      "name": "brief",
      "status": "completed",
      "duration_ms": 5000
    }
  ],
  "summary": {
    "total_ingested": 87,
    "total_classified": 87,
    "total_neutralized": 45,
    "brief_stories": 25
  }
}
```

**Example:**

```bash
curl -s -X POST https://api.ntrl.news/v1/pipeline/run \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "max_items_per_source": 20,
    "classify_limit": 200,
    "neutralize_limit": 100,
    "max_workers": 5,
    "cutoff_hours": 24
  }'
```

---

#### POST /v1/pipeline/scheduled-run

Run the pipeline on a schedule (designed for Railway cron jobs). Returns a flat response with trace ID for observability.

**Authentication:** Required (`X-API-Key`)

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `max_items_per_source` | integer | No | 25 | Maximum articles to ingest per source. |
| `classify_limit` | integer | No | 200 | Maximum articles to classify. |
| `neutralize_limit` | integer | No | 25 | Maximum articles to neutralize. |
| `max_workers` | integer | No | 5 | Maximum concurrent neutralization workers. |
| `cutoff_hours` | integer | No | 24 | Brief cutoff window in hours. |

**Response:** `200 OK`

```json
{
  "status": "completed",
  "trace_id": "sched-20260128-063000-abc123",
  "started_at": "2026-01-28T06:30:00Z",
  "finished_at": "2026-01-28T06:40:00Z",
  "duration_ms": 600000,
  "ingest_sources_processed": 12,
  "ingest_total_ingested": 87,
  "ingest_total_skipped_duplicate": 23,
  "classify_total": 87,
  "classify_success": 85,
  "classify_failed": 2,
  "neutralize_total_processed": 45,
  "neutralize_total_skipped": 5,
  "neutralize_total_failed": 2,
  "brief_story_count": 25,
  "brief_section_count": 5,
  "alerts": []
}
```

**Notes:**

- The `trace_id` is unique to each run and can be used to correlate logs.
- The `alerts` array contains warning messages if any stage had issues.

**Example:**

```bash
curl -s -X POST https://api.ntrl.news/v1/pipeline/scheduled-run \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

#### POST /v1/grade

Grade neutralized text against the NTRL canon rules. Validates that neutralization meets quality standards.

**Authentication:** Required (`X-API-Key`)

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `original_text` | string | Yes | -- | The original article body text. |
| `neutral_text` | string | Yes | -- | The neutralized article body text. |
| `original_headline` | string | No | None | The original headline. |
| `neutral_headline` | string | No | None | The neutralized headline. |

**Response:** `200 OK`

```json
{
  "overall_pass": true,
  "results": [
    {
      "rule": "no_loaded_language",
      "passed": true,
      "details": "No emotionally loaded language detected."
    },
    {
      "rule": "factual_accuracy",
      "passed": true,
      "details": "No factual claims added or removed."
    },
    {
      "rule": "tone_neutrality",
      "passed": false,
      "details": "Paragraph 3 still contains a slightly editorial tone."
    }
  ]
}
```

**Example:**

```bash
curl -s -X POST https://api.ntrl.news/v1/grade \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "original_text": "The senator slammed the radical proposal...",
    "neutral_text": "The senator criticized the proposed policy change...",
    "original_headline": "Senator SLAMS radical bill",
    "neutral_headline": "Senator criticizes proposed bill"
  }'
```

---

#### POST /v1/reset

Reset all data. **Testing only -- disabled in production environments.**

**Authentication:** Required (`X-API-Key`)

**Response:** `200 OK`

```json
{
  "status": "completed",
  "started_at": "2026-01-28T12:00:00Z",
  "finished_at": "2026-01-28T12:00:05Z",
  "duration_ms": 5000,
  "db_deleted": true,
  "storage_deleted": true,
  "warning": "All data has been permanently deleted."
}
```

**Example:**

```bash
curl -s -X POST https://api.ntrl.news/v1/reset \
  -H "X-API-Key: $ADMIN_API_KEY"
```

---

### Prompts

All prompt endpoints require the `X-API-Key` header.

#### GET /v1/prompts

List all configured prompts.

**Authentication:** Required (`X-API-Key`)

**Query Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `model` | string | No | None | Filter prompts by model name (e.g., `claude-sonnet-4-20250514`). |

**Response:** `200 OK`

```json
{
  "prompts": [
    {
      "name": "neutralize-v3",
      "model": "claude-sonnet-4-20250514",
      "is_active": true,
      "system_prompt": "You are a neutral news editor...",
      "user_prompt_template": "Neutralize the following article:\n\n{article_body}"
    }
  ],
  "active_model": "claude-sonnet-4-20250514"
}
```

**Example:**

```bash
# List all prompts
curl -s https://api.ntrl.news/v1/prompts \
  -H "X-API-Key: $ADMIN_API_KEY"

# Filter by model
curl -s "https://api.ntrl.news/v1/prompts?model=claude-sonnet-4-20250514" \
  -H "X-API-Key: $ADMIN_API_KEY"
```

---

#### GET /v1/prompts/{name}

Get a specific prompt by name.

**Authentication:** Required (`X-API-Key`)

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | string | The name of the prompt. |

**Response:** `200 OK`

```json
{
  "name": "neutralize-v3",
  "model": "claude-sonnet-4-20250514",
  "is_active": true,
  "system_prompt": "You are a neutral news editor...",
  "user_prompt_template": "Neutralize the following article:\n\n{article_body}"
}
```

**Example:**

```bash
curl -s https://api.ntrl.news/v1/prompts/neutralize-v3 \
  -H "X-API-Key: $ADMIN_API_KEY"
```

---

#### PUT /v1/prompts/{name}

Create or update a prompt.

**Authentication:** Required (`X-API-Key`)

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | string | The name of the prompt to create or update. |

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `system_prompt` | string | Yes | The system prompt text. |
| `user_prompt_template` | string | Yes | The user prompt template with `{placeholders}`. |
| `model` | string | No | The target model name. |

**Response:** `200 OK`

**Example:**

```bash
curl -s -X PUT https://api.ntrl.news/v1/prompts/neutralize-v4 \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "system_prompt": "You are a neutral, fact-focused news editor...",
    "user_prompt_template": "Rewrite the following article to remove bias:\n\n{article_body}",
    "model": "claude-sonnet-4-20250514"
  }'
```

---

#### POST /v1/prompts/{name}/activate

Activate a prompt for use with its associated model.

**Authentication:** Required (`X-API-Key`)

**Path Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | string | The name of the prompt to activate. |

**Response:** `200 OK`

**Example:**

```bash
curl -s -X POST https://api.ntrl.news/v1/prompts/neutralize-v4/activate \
  -H "X-API-Key: $ADMIN_API_KEY"
```

---

#### POST /v1/prompts/test

Test a prompt configuration on sample articles without saving. Returns neutralization results for evaluation.

**Authentication:** Required (`X-API-Key`)

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `limit` | integer | No | 10 | Number of sample articles to test on. |
| `system_prompt` | string | No | None | Override system prompt for testing. |
| `user_prompt_template` | string | No | None | Override user prompt template for testing. |

**Response:** `200 OK`

```json
{
  "results": [
    {
      "story_id": "uuid-string",
      "original_title": "Senator SLAMS radical bill",
      "neutralized_title": "Senator criticizes proposed bill",
      "has_manipulative_content": true,
      "span_count": 5
    }
  ]
}
```

**Example:**

```bash
curl -s -X POST https://api.ntrl.news/v1/prompts/test \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "limit": 5,
    "system_prompt": "You are a neutral editor. Remove all emotional language.",
    "user_prompt_template": "Neutralize this:\n\n{article_body}"
  }'
```

---

## V2 Endpoints

V2 endpoints provide standalone article processing. They do not interact with the story database or pipeline -- they accept raw text and return processed results.

---

### POST /v2/scan

Scan an article for manipulative language without applying fixes. Detection only.

**Authentication:** None

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `body` | string | Yes | -- | The article body text to scan. |
| `title` | string | No | None | The article title/headline to scan. |
| `enable_semantic` | boolean | No | false | Enable deeper semantic analysis (slower, more thorough). |

**Response:** `200 OK`

```json
{
  "body_detections": 7,
  "title_detections": 2,
  "total_detections": 9,
  "scan_time_ms": 1250,
  "detections_by_category": {
    "loaded_language": 4,
    "framing_bias": 3,
    "emotional_appeal": 2
  },
  "detections_by_severity": {
    "high": 3,
    "medium": 4,
    "low": 2
  },
  "body_spans": [
    {
      "start_char": 45,
      "end_char": 62,
      "text": "slammed critics",
      "category": "loaded_language",
      "severity": "high",
      "reason": "Emotionally loaded verb implying aggression"
    }
  ],
  "title_spans": [
    {
      "start_char": 0,
      "end_char": 15,
      "text": "Senator SLAMS",
      "category": "loaded_language",
      "severity": "high",
      "reason": "Capitalized emotionally loaded verb in headline"
    }
  ]
}
```

**Example:**

```bash
curl -s -X POST https://api.ntrl.news/v2/scan \
  -H "Content-Type: application/json" \
  -d '{
    "body": "The senator slammed critics of the radical proposal, calling it a devastating blow to hardworking families.",
    "title": "Senator SLAMS radical bill in fiery speech"
  }'
```

---

### POST /v2/process

Full processing pipeline: scan for manipulative language, then apply neutralization fixes. Returns both the neutralized text and detection statistics.

**Authentication:** None

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `body` | string | Yes | -- | The article body text. |
| `title` | string | No | None | The article title/headline. |
| `deck` | string | No | None | The article deck/subheadline. |
| `enable_semantic` | boolean | No | false | Enable deeper semantic analysis. |
| `mock_mode` | boolean | No | false | Return mock results without calling the LLM (for testing). |
| `force` | boolean | No | false | Skip cache and force reprocessing. |

**Response:** `200 OK`

```json
{
  "detail_full": "The senator criticized the proposed policy change, saying it would significantly affect working families.",
  "detail_brief": "A senator responded to the proposed legislation, expressing concerns about its impact on families.",
  "feed_title": "Senator criticizes proposed bill",
  "feed_summary": "A senator criticized the proposed policy change during a floor speech.",
  "total_detections": 9,
  "total_changes": 7,
  "passed_validation": true,
  "total_time_ms": 3500,
  "scan_time_ms": 1250,
  "fix_time_ms": 2250,
  "cache_hit": false,
  "detections_by_category": {
    "loaded_language": 4,
    "framing_bias": 3,
    "emotional_appeal": 2
  },
  "changes_by_action": {
    "replace": 5,
    "remove": 1,
    "rephrase": 1
  }
}
```

**Output Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `detail_full` | string | Full neutralized article body. |
| `detail_brief` | string | Condensed neutralized brief. |
| `feed_title` | string | Neutralized headline for feed display. |
| `feed_summary` | string | Neutralized one-paragraph summary. |
| `total_detections` | integer | Total manipulation instances detected. |
| `total_changes` | integer | Total changes applied. |
| `passed_validation` | boolean | Whether the output passed quality validation. |
| `total_time_ms` | integer | Total processing time in milliseconds. |
| `scan_time_ms` | integer | Time spent on detection. |
| `fix_time_ms` | integer | Time spent applying fixes. |
| `cache_hit` | boolean | Whether the result was served from cache. |

**Example:**

```bash
curl -s -X POST https://api.ntrl.news/v2/process \
  -H "Content-Type: application/json" \
  -d '{
    "body": "The senator slammed critics of the radical proposal, calling it a devastating blow to hardworking families. The controversial measure has sparked outrage among opponents.",
    "title": "Senator SLAMS radical bill in fiery speech",
    "deck": "Opponents outraged by sweeping changes"
  }'
```

---

### POST /v2/batch

Process multiple articles in a single request. Maximum 100 articles per batch.

**Authentication:** None

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `articles` | array | Yes | -- | Array of article objects (max 100). |
| `articles[].article_id` | string | Yes | -- | Caller-defined unique ID for the article. |
| `articles[].body` | string | Yes | -- | The article body text. |
| `articles[].title` | string | No | None | The article title/headline. |
| `enable_semantic` | boolean | No | false | Enable semantic analysis for all articles. |
| `mock_mode` | boolean | No | false | Return mock results for all articles. |

**Response:** `200 OK`

```json
{
  "total_articles": 3,
  "successful": 3,
  "failed": 0,
  "total_time_ms": 10500,
  "avg_time_per_article_ms": 3500,
  "results": [
    {
      "article_id": "article-001",
      "status": "success",
      "detail_full": "Neutralized body text...",
      "feed_title": "Neutralized headline",
      "total_detections": 5,
      "total_changes": 4,
      "processing_time_ms": 3200
    },
    {
      "article_id": "article-002",
      "status": "success",
      "detail_full": "Neutralized body text...",
      "feed_title": "Neutralized headline",
      "total_detections": 3,
      "total_changes": 2,
      "processing_time_ms": 2800
    }
  ]
}
```

**Example:**

```bash
curl -s -X POST https://api.ntrl.news/v2/batch \
  -H "Content-Type: application/json" \
  -d '{
    "articles": [
      {
        "article_id": "article-001",
        "body": "The senator slammed the radical proposal...",
        "title": "Senator SLAMS bill"
      },
      {
        "article_id": "article-002",
        "body": "Opponents blasted the controversial measure...",
        "title": "Critics blast new policy"
      }
    ],
    "enable_semantic": false
  }'
```

---

### POST /v2/transparency

Generate a full transparency package for an article, including detection spans, neutralized output, and an explanation of all changes.

**Authentication:** None

**Request Body:**

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `body` | string | Yes | -- | The article body text. |
| `title` | string | No | None | The article title/headline. |

**Response:** `200 OK`

```json
{
  "original_body": "The senator slammed critics of the radical proposal...",
  "original_title": "Senator SLAMS radical bill",
  "neutralized_body": "The senator criticized the proposed policy change...",
  "neutralized_title": "Senator criticizes proposed bill",
  "total_detections": 5,
  "total_changes": 4,
  "spans": [
    {
      "start_char": 13,
      "end_char": 28,
      "original_text": "slammed critics",
      "action": "replace",
      "reason": "Emotionally loaded verb implying aggression",
      "replacement_text": "criticized"
    }
  ],
  "disclosure": "This article contained emotionally loaded language that was neutralized.",
  "processing_time_ms": 3500
}
```

**Example:**

```bash
curl -s -X POST https://api.ntrl.news/v2/transparency \
  -H "Content-Type: application/json" \
  -d '{
    "body": "The senator slammed critics of the radical proposal, calling it a devastating blow to hardworking families.",
    "title": "Senator SLAMS radical bill"
  }'
```

---

## Error Responses

All endpoints return standard HTTP error codes with a consistent JSON error body:

```json
{
  "detail": "Human-readable error message describing what went wrong."
}
```

### Common Error Codes

| Code | Meaning | Common Causes |
|------|---------|---------------|
| `400` | Bad Request | Invalid request body, missing required fields, validation errors. |
| `401` | Unauthorized | Missing or invalid `X-API-Key` header on admin endpoints. |
| `404` | Not Found | Story, source, prompt, or brief not found. |
| `409` | Conflict | Duplicate resource (e.g., source slug already exists). |
| `422` | Unprocessable Entity | Request body is syntactically valid JSON but semantically invalid (e.g., `hours=0`). |
| `429` | Too Many Requests | Rate limit exceeded. Retry after the limit window resets. |
| `500` | Internal Server Error | Unexpected server error. Check logs for details. |
