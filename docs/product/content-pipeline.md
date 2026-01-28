# NTRL Content Pipeline Specification

> **Version**: 1.0
> **Last updated**: January 2026
> **Status**: Production (Railway staging)

---

## Core Architecture Principle

**The original article body is the single source of truth.** Every user-facing
output -- title, summary, brief, full article, transparency spans -- is derived
from the scraped article body stored in S3. The RSS title and description are
stored for audit and deduplication purposes but are **never** used as input to
the neutralization stage.

```
INGEST:          RSS --> Database (metadata) + S3 (body.txt)
CLASSIFY:        body.txt --> domain (20) + feed_category (10) + tags
NEUTRALIZE:      body.txt --> ALL outputs (title, summary, brief, full, spans)
BRIEF ASSEMBLE:  Group by feed_category (10 categories) --> DailyBrief
```

---

## Pipeline Flow Diagram

```
                        +-------------+
                        |  RSS Feeds  |
                        | (N sources) |
                        +------+------+
                               |
                      STAGE 1: INGEST
                               |
          +--------------------+---------------------+
          |                                          |
  +-------v--------+                       +---------v---------+
  |    Postgres     |                       |     Amazon S3     |
  |  (StoryRaw)    |                       |  raw/<id>/body    |
  | - metadata      |                       |  (gzip text/plain)|
  | - url_hash      |                       +-------------------+
  | - title_hash    |                                |
  +---------+-------+                                |
            |                                        |
   STAGE 2: CLASSIFY                                 |
            |                                        |
            v                                        |
  +---------+-------+                                |
  |  LLM Classifier |<-------(first 2000 chars)------+
  |  Reliability     |
  |  Chain (4 tries) |
  +--------+--------+
           |
           | domain (20) + geography --> feed_category (10)
           |
           v
  +--------+--------+
  |    StoryRaw     |
  | + domain         |
  | + feed_category  |
  | + classified_at  |
  +--------+--------+
           |
  STAGE 3: NEUTRALIZE
           |
           v
  +--------+--------+          +-------------------+
  |  LLM Neutralizer|<--------|   S3 (full body)   |
  |  (3 LLM calls)  |          +-------------------+
  +--+----+----+----+
     |    |    |
     |    |    +---> feed_title, feed_summary, detail_title   (Call 3: Compress)
     |    +--------> detail_brief                              (Call 2: Synthesize)
     +-------------> detail_full + transparency_spans          (Call 1: Filter)
                         |
                         v
               +---------+---------+
               | StoryNeutralized  |
               | - 6 text outputs  |
               | - status tracking |
               +--------+----------+
                        |
           STAGE 4: BRIEF ASSEMBLE
                        |
                        v
               +--------+---------+
               |   DailyBrief     |
               | + DailyBriefItem |
               | (denormalized)   |
               +------------------+
```

---

## Stage 1: INGEST

| Property | Value |
|---|---|
| **Service** | `app/services/ingestion.py` -- `IngestionService` |
| **Trigger** | `POST /v1/ingest/run` (admin) or via `POST /v1/pipeline/scheduled-run` |
| **Input** | Active RSS sources (from `Source` table) |
| **Output** | `StoryRaw` rows with S3 content URIs |
| **Dev limit** | Max 25 articles per source per run |

### Process

```
For each active source:
  1. Fetch RSS feed (SSL verified, 30s timeout, custom User-Agent)
  2. Parse entries via feedparser (capped at max_items)
  3. For each entry:
     a. Extract metadata: title, description, URL, author, published_at
     b. Compute url_hash (SHA-256) and title_hash for deduplication
     c. Check against Deduper -- skip if duplicate
     d. Scrape full article body from source URL (BodyExtractor)
        - Primary: requests + readability
        - Fallback: newspaper3k
        - Retries with exponential backoff
     e. Deduplicate paragraphs (_deduplicate_paragraphs)
        - Splits on double newlines
        - Removes duplicate paragraphs > 50 chars (normalized lowercase)
        - Preserves short paragraphs unconditionally
     f. Classify section (legacy SectionClassifier -- 5 values)
     g. Upload body to S3 (raw/ prefix, gzip compressed, 30-day TTL)
     h. Create StoryRaw row in Postgres
     i. Log PipelineLog entry
```

### Data Flow

```
RSS Feed
  |
  v
feedparser.parse()
  |
  v
_normalize_entry()
  |-- title, description, URL, author, published_at
  |-- _extract_article_body(url) --> ExtractionResult
  |-- _deduplicate_paragraphs(body)
  |
  v
Deduper.is_duplicate(url, title)
  |
  |-- duplicate? --> skip, increment counter
  |-- new?       --> continue
  |
  v
_upload_body_to_storage(story_id, body, published_at)
  |
  v
StoryRaw(
    id, source_id, original_url, original_title,
    original_description, original_author,
    url_hash, title_hash, published_at, ingested_at,
    raw_content_uri, raw_content_hash,
    raw_content_available=True
)
```

### StoryRaw Key Fields (Ingestion)

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `source_id` | UUID FK | References `Source` |
| `original_url` | String | Source article URL |
| `original_title` | String | RSS title (audit only, not used for neutralization) |
| `original_description` | String | RSS description (audit only) |
| `url_hash` | String | SHA-256 of normalized URL |
| `title_hash` | String | SHA-256 of normalized title |
| `raw_content_uri` | String | S3 URI (e.g., `s3://bucket/raw/<id>/body`) |
| `raw_content_available` | Boolean | Whether body was successfully uploaded |
| `raw_content_encoding` | String | Always `gzip` |

### Ingestion Result Metrics

```python
{
    'total_ingested': int,       # New articles stored
    'total_skipped_duplicate': int,  # Duplicates detected
    'total_body_downloaded': int,    # Successful body extractions
    'total_body_failed': int,        # Failed body extractions
    'sources_processed': int,
    'duration_ms': int,
}
```

---

## Stage 2: CLASSIFY

> Added January 2026. Replaced the 5-section `SectionClassifier` with a
> 20-domain LLM-powered taxonomy mapped to 10 user-facing feed categories.

| Property | Value |
|---|---|
| **Service** | `app/services/llm_classifier.py` -- `LLMClassifier` |
| **Mapping** | `app/services/domain_mapper.py` -- `map_domain_to_feed_category()` |
| **Fallback** | `app/services/enhanced_keyword_classifier.py` -- `classify_by_keywords()` |
| **Trigger** | `POST /v1/classify/run` (admin) or via `POST /v1/pipeline/scheduled-run` |
| **Input** | Unclassified `StoryRaw` entries (where `classified_at IS NULL`) |
| **Output** | Updated `StoryRaw` with domain, feed_category, tags, confidence |
| **Dev limit** | 200 articles per classify run |

### Reliability Chain (4 Attempts)

```
Attempt 1:  gpt-4o-mini    + full prompt (JSON mode)
    |
    +--> parse & validate --> success? --> DONE
    |
    +--> fail
         |
Attempt 2:  gpt-4o-mini    + simplified prompt (JSON mode)
    |
    +--> parse & validate --> success? --> DONE
    |
    +--> fail
         |
Attempt 3:  gemini-2.0-flash + full prompt (JSON mode)
    |
    +--> parse & validate --> success? --> DONE
    |
    +--> fail
         |
Attempt 4:  Enhanced keyword classifier (30-50 keywords per domain)
    |
    +--> always succeeds --> DONE (flagged as method="keyword_fallback")
```

### Process

```
1. Query StoryRaw WHERE classified_at IS NULL, is_duplicate = False
   ORDER BY ingested_at DESC, LIMIT 200
2. Pre-fetch article bodies from S3 in parallel (ThreadPoolExecutor, 5 workers)
   - First 2000 chars only (CLASSIFICATION_BODY_PREFIX_CHARS)
3. For each story:
   a. Build user prompt: TITLE + DESCRIPTION + SOURCE + EXCERPT(2000 chars)
   b. Run reliability chain (4 attempts)
   c. LLM returns JSON:
      {
        "domain": "<1 of 20>",
        "confidence": 0.0-1.0,
        "tags": {
          "geography": "us|local|international|mixed",
          "geography_detail": "...",
          "actors": ["..."],
          "action_type": "legislation|ruling|announcement|...",
          "topic_keywords": ["..."]
        }
      }
   d. map_domain_to_feed_category(domain, geography) --> feed_category
   e. Update StoryRaw: domain, feed_category, classification_tags,
      classification_confidence, classification_model, classification_method,
      classified_at
4. Commit all updates
```

### Domain Taxonomy (20 Values)

| # | Domain | Direct Feed Category |
|---|---|---|
| 1 | `global_affairs` | world |
| 2 | `governance_politics` | *geography-dependent* |
| 3 | `law_justice` | *geography-dependent* |
| 4 | `security_defense` | *geography-dependent* |
| 5 | `crime_public_safety` | *geography-dependent* |
| 6 | `economy_macroeconomics` | business |
| 7 | `finance_markets` | business |
| 8 | `business_industry` | business |
| 9 | `labor_demographics` | business |
| 10 | `infrastructure_systems` | business |
| 11 | `energy` | environment |
| 12 | `environment_climate` | environment |
| 13 | `science_research` | science |
| 14 | `health_medicine` | health |
| 15 | `technology` | technology |
| 16 | `media_information` | technology |
| 17 | `sports_competition` | sports |
| 18 | `society_culture` | culture |
| 19 | `lifestyle_personal` | culture |
| 20 | `incidents_disasters` | *geography-dependent* |

### Geography-Dependent Domain Mapping

Five domains route to different feed categories based on the geography tag:

| Domain | `us` | `local` | `international` | `mixed` |
|---|---|---|---|---|
| `governance_politics` | us | us | world | us |
| `law_justice` | us | us | world | us |
| `security_defense` | us | us | world | us |
| `crime_public_safety` | us | **local** | world | us |
| `incidents_disasters` | us | **local** | world | us |

Note: Only `crime_public_safety` and `incidents_disasters` map to the `local`
feed category. The other three geography-dependent domains map `local` to `us`.

### Feed Categories (10 Values)

| Order | Category | Display Name |
|---|---|---|
| 0 | `world` | World |
| 1 | `us` | U.S. |
| 2 | `local` | Local |
| 3 | `business` | Business |
| 4 | `technology` | Technology |
| 5 | `science` | Science |
| 6 | `health` | Health |
| 7 | `environment` | Environment |
| 8 | `sports` | Sports |
| 9 | `culture` | Culture |

### StoryRaw Classification Columns

| Column | Type | Description |
|---|---|---|
| `domain` | String(40) | Internal domain (1 of 20) |
| `feed_category` | String(32) | User-facing category (1 of 10) |
| `classification_tags` | JSONB | `{geography, geography_detail, actors, action_type, topic_keywords}` |
| `classification_confidence` | Float | 0.0--1.0 (LLM self-reported; 0.0 for keyword fallback) |
| `classification_model` | String(64) | `"gpt-4o-mini"`, `"gemini-2.0-flash"`, or `"keyword"` |
| `classification_method` | String(20) | `"llm"` or `"keyword_fallback"` |
| `classified_at` | DateTime | Timestamp of classification |

### Classification Monitoring

The `CLASSIFY_FALLBACK_RATE_HIGH` alert fires when keyword fallback
exceeds 1% of classified articles. In production (Jan 2026), the LLM success
rate has been 100% with 0 keyword fallbacks across 200+ articles.

---

## Stage 3: NEUTRALIZE

| Property | Value |
|---|---|
| **Service** | `app/services/neutralizer/` (module directory) |
| **Span utilities** | `app/services/neutralizer/spans.py` |
| **Providers** | `app/services/neutralizer/providers/` (OpenAI, Gemini, Anthropic) |
| **Trigger** | `POST /v1/neutralize/run` (admin) or via `POST /v1/pipeline/scheduled-run` |
| **Input** | Pending `StoryRaw` entries with body available in S3 |
| **Output** | `StoryNeutralized` rows with 6 text outputs + spans |
| **Dev limit** | Max 25 articles per neutralize run |

### Process Overview

Neutralization makes **3 LLM calls** per article, each with a shared system
prompt and a task-specific user prompt:

```
                   +--------------------+
                   |  S3: article body  |
                   +--------+-----------+
                            |
             +--------------+--------------+
             |              |              |
     Call 1: Filter   Call 2: Synth  Call 3: Compress
             |              |              |
             v              v              v
       detail_full    detail_brief    feed_title
       + spans                        feed_summary
                                      detail_title
```

### Call 1: Filter and Track (detail_full + spans)

**Purpose**: Remove manipulative language while preserving structure and facts.

```
Input:  Original article body (full text from S3)
Output: detail_full (neutralized article)
        transparency_spans (manipulative phrases detected)

Two sub-steps:
  a. Synthesis mode: LLM rewrites the full article neutrally (plain text)
  b. Span detection: Separate LLM call identifies manipulative phrases

Span Pipeline:
  LLM returns: {"phrases": [{"phrase": "...", "reason": "...", "action": "...", "replacement": "..."}]}
       |
       v
  find_phrase_positions(body, phrases) -- map text to char offsets
       |
       v
  filter_spans_in_quotes(body, spans) -- remove phrases inside quotation marks
       |
       v
  filter_false_positives(spans) -- remove known false positives
       |
       v
  Final TransparencySpan[] with accurate character positions
```

**Manipulation Taxonomy (14 categories)**:

| # | Category | Examples |
|---|---|---|
| 1 | Urgency inflation | BREAKING, JUST IN, scrambling |
| 2 | Emotional triggers | shocking, devastating, slams |
| 3 | Clickbait | You won't believe, Here's what happened |
| 4 | Selling/hype | revolutionary, game-changer |
| 5 | Agenda signaling | radical left, extremist |
| 6 | Loaded verbs | slammed, blasted, admits, claims |
| 7 | Urgency inflation (subtle) | Act now, Before it's too late |
| 8 | Agenda framing | "the crisis at the border" |
| 9 | Sports/event hype | brilliant, blockbuster, massive |
| 10 | Loaded personal descriptors | handsome, menacing, unfriendly |
| 11 | Hyperbolic adjectives | punishing, whopping, staggering |
| 12 | Loaded idioms | came under fire, in the crosshairs |
| 13 | Entertainment/celebrity hype | romantic escape, A-list pair |
| 14 | Editorial voice | we're glad, as it should, Border Czar |

### Call 2: Synthesize (detail_brief)

**Purpose**: Create a concise 3-5 paragraph prose summary.

```
Input:  Original article body (full text from S3)
Output: detail_brief (plain text, no headers or bullets)

Implicit structure:
  Paragraph 1: Grounding -- what happened
  Paragraph 2: Context -- why it matters
  Paragraph 3: State of knowledge -- what is known
  Paragraph 4-5: Uncertainty -- what remains unclear
```

### Call 3: Compress (feed outputs)

**Purpose**: Generate short-form outputs for feed display.

```
Input:  Original article body + detail_brief (for context)
Output:
  - feed_title:    <=6 words preferred, 12 max (55-65 chars)
  - feed_summary:  1-2 sentences, 100-120 chars target, 130 hard max
  - detail_title:  Precise headline for article page (<=100 chars)
```

### Text Length Constraints

| Field | Target | Soft Max | Hard Max |
|---|---|---|---|
| `feed_title` | 55 chars / 6 words | 65 chars | 12 words |
| `feed_summary` | 105 chars | 115 chars | 130 chars |
| `detail_title` | -- | -- | 100 chars |
| `detail_brief` | 3-5 paragraphs | -- | -- |
| `detail_full` | Full article length | -- | -- |

### Neutralization Output (6 Fields)

```python
NeutralizationResult(
    feed_title="...",        # Short headline for feed list
    feed_summary="...",      # 1-2 sentence preview
    detail_title="...",      # Precise headline for article page
    detail_brief="...",      # 3-5 paragraph summary
    detail_full="...",       # Full neutralized article
    has_manipulative_content=True,
    spans=[TransparencySpan(...), ...],
)
```

### Status Tracking

Each neutralized article records its processing outcome:

| Status | Description |
|---|---|
| `success` | All 3 LLM calls succeeded, output passes audit |
| `failed_llm` | LLM API returned an error |
| `failed_garbled` | LLM output was garbled or unreadable |
| `failed_audit` | Output failed quality audit after max retries |
| `skipped` | Article skipped (e.g., no body in S3) |

**Failed articles are stored in the database but are never shown to users.**
Only articles with `neutralization_status = "success"` appear in the brief
and story feeds.

### LLM Provider Chain

| Priority | Provider | Model | Role |
|---|---|---|---|
| 1 (primary) | OpenAI | `gpt-4o-mini` | All neutralization calls |
| 2 (fallback) | Google | `gemini-2.0-flash` | If OpenAI fails |
| 3 (available) | Anthropic | Claude | Configured but not primary |

### Special Handling: Editorial Content

When the `ContentTypeClassifier` detects editorial content (3+ editorial
signals such as "we're glad", "as it should", "Border Czar"), the neutralizer
uses **full synthesis mode** instead of span-guided rewriting. This completely
rewrites the article rather than attempting surgical edits.

The same synthesis fallback triggers when an article has more than 15
transparency spans, indicating heavy manipulation.

---

## Stage 4: BRIEF ASSEMBLE

| Property | Value |
|---|---|
| **Service** | `app/services/brief_assembly.py` -- `BriefAssemblyService` |
| **Trigger** | `POST /v1/brief/run` (admin) or via `POST /v1/pipeline/scheduled-run` |
| **Input** | `StoryNeutralized` with `neutralization_status="success"` and `is_current=True` |
| **Output** | `DailyBrief` + `DailyBriefItem` rows (denormalized for fast reads) |

### Process

```
1. Query qualifying stories:
   - StoryNeutralized.is_current = True
   - StoryNeutralized.neutralization_status = "success"
   - StoryRaw.is_duplicate = False
   - StoryRaw.published_at >= cutoff_time (default: now - 24 hours)

2. Group by StoryRaw.feed_category (10 categories)
   - Articles where feed_category IS NULL are SKIPPED
   - They will appear after the next classify run

3. Sort within each category (deterministic):
   a. published_at DESC (most recent first)
   b. Source priority ASC (AP=1 > Reuters=2 > BBC=3 > NPR=4 > others=99)
   c. Story ID ASC (deterministic tie-breaker)

4. Fixed category display order:
   World -> U.S. -> Local -> Business -> Technology
      -> Science -> Health -> Environment -> Sports -> Culture

5. Mark previous DailyBrief as is_current=False

6. Create DailyBrief row + DailyBriefItem rows (denormalized):
   - feed_title, feed_summary, source_name, original_url
   - section, section_order, position
   - has_manipulative_content flag
```

### Brief Assembly Rules

- **No personalization**: All users see the same brief.
- **No trending or popularity signals**: Order is strictly by recency and source priority.
- **No legacy section fallback**: The `SectionClassifier` (5 sections) was removed
  in Jan 2026 because it defaulted unknown articles to "world", misclassifying
  sports and culture content.
- **Empty categories are included**: Categories with 0 stories still exist in the
  category order (UI can skip them).

### Source Priority

| Rank | Source | Priority Value |
|---|---|---|
| 1 | AP / AP News | 1 |
| 2 | Reuters | 2 |
| 3 | BBC | 3 |
| 4 | NPR | 4 |
| -- | All others | 99 |

### DailyBriefItem Schema (Denormalized)

| Column | Source | Description |
|---|---|---|
| `feed_title` | StoryNeutralized | Short headline |
| `feed_summary` | StoryNeutralized | 1-2 sentence preview |
| `source_name` | Source | e.g., "Associated Press" |
| `original_url` | StoryRaw | Link to original article |
| `published_at` | StoryRaw | Original publication time |
| `section` | StoryRaw.feed_category | Category string |
| `section_order` | FEED_CATEGORY_ORDER | 0-9 |
| `position` | Computed | Position within section |
| `has_manipulative_content` | StoryNeutralized | Boolean flag |

---

## Scheduled Pipeline (Railway Cron)

| Property | Value |
|---|---|
| **Endpoint** | `POST /v1/pipeline/scheduled-run` |
| **Schedule** | Every 4 hours (`0 */4 * * *`) |
| **Auth** | `X-API-Key` header (admin key) |

### Default Parameters

```python
class ScheduledRunRequest:
    max_items_per_source: int = 25     # Max articles to ingest per RSS source
    classify_limit: int = 200          # Max stories to classify per run
    neutralize_limit: int = 25         # Max stories to neutralize per run
    max_workers: int = 5               # Parallel workers for neutralization
    cutoff_hours: int = 24             # Hours to look back for brief assembly
```

### Execution Sequence

```
POST /v1/pipeline/scheduled-run
  |
  +---> Stage 1: INGEST
  |       IngestionService.ingest_all(max_items_per_source=25)
  |
  +---> Stage 2: CLASSIFY
  |       LLMClassifier.classify_pending(limit=200)
  |
  +---> Stage 3: NEUTRALIZE
  |       NeutralizerService.neutralize_pending(limit=25)
  |
  +---> Stage 4: BRIEF ASSEMBLE
  |       BriefAssemblyService.assemble_brief(cutoff_hours=24, force=True)
  |
  +---> Create PipelineRunSummary record
  |       - All 4 stage metrics
  |       - Alert evaluation
  |       - Overall status
  |
  +---> Return ScheduledRunResponse
```

### PipelineRunSummary Record

Every scheduled run produces a summary row with comprehensive health metrics:

```
+-------------------------------+-------------------------------------------+
| Field Group                   | Fields                                    |
+-------------------------------+-------------------------------------------+
| Timing                        | started_at, finished_at, duration_ms      |
|                               | trace_id                                  |
+-------------------------------+-------------------------------------------+
| Ingestion Stats               | ingest_total                              |
|                               | ingest_success                            |
|                               | ingest_body_downloaded                    |
|                               | ingest_body_failed                        |
|                               | ingest_skipped_duplicate                  |
+-------------------------------+-------------------------------------------+
| Classification Stats          | classify_total                            |
|                               | classify_success                          |
|                               | classify_llm                              |
|                               | classify_keyword_fallback                 |
|                               | classify_failed                           |
+-------------------------------+-------------------------------------------+
| Neutralization Stats          | neutralize_total                          |
|                               | neutralize_success                        |
|                               | neutralize_skipped_no_body                |
|                               | neutralize_failed                         |
+-------------------------------+-------------------------------------------+
| Brief Stats                   | brief_story_count                         |
|                               | brief_section_count                       |
+-------------------------------+-------------------------------------------+
| Status                        | status: "completed" | "partial" | "failed" |
|                               | alerts: ["alert_code", ...]               |
|                               | trigger: "scheduled" | "manual" | "api"   |
+-------------------------------+-------------------------------------------+
```

---

## Pipeline Observability

### Audit Trail

**PipelineLog** records are created for every stage execution at the
individual-article level. Each log entry contains:

- `stage`: `ingest`, `classify`, `neutralize`, `brief_assemble`
- `status`: `completed` or `failed`
- `story_raw_id`: FK to the article being processed
- `started_at`, `finished_at`, `duration_ms`: Timing
- `error_message`: Error details if failed
- `trace_id`: Links to the parent pipeline run
- `entry_url`, `entry_url_hash`: For ingestion tracking
- `failure_reason`: Categorized failure type
- `retry_count`: Number of retries attempted

### Alert Thresholds

| Alert Code | Threshold | Description |
|---|---|---|
| `body_download_rate_low` | < 70% | Body download success rate below threshold |
| `neutralization_rate_low` | < 90% | Neutralization success rate below threshold |
| `brief_story_count_low` | < 10 | Brief contains too few stories |
| `classify_fallback_rate_high` | > 1% | Too many articles using keyword classifier |
| `ingestion_zero` | == 0 | No articles ingested in this run |
| `pipeline_failed` | status == "failed" | Overall pipeline run failed |

Alerts are evaluated after each pipeline run via `check_alerts()` and stored
in the `PipelineRunSummary.alerts` JSONB column.

### Structured Logging

All span detection operations use the `[SPAN_DETECTION]` prefix for easy
filtering:

```
[SPAN_DETECTION] Starting LLM call, model=gpt-4o-mini, body_length=4721
[SPAN_DETECTION] LLM responded, response_length=523
[SPAN_DETECTION] LLM returned 17 phrases
[SPAN_DETECTION] Pipeline: position_match=22 -> quote_filter=13 -> fp_filter=13
[SPAN_DETECTION] False positive filter removed 2: ['crisis management', 'public relations']
```

Classification operations use the `[CLASSIFY]` prefix:

```
[CLASSIFY] Classifying 25 pending stories
[CLASSIFY] Success: OpenAI attempt 1, domain=governance_politics
[CLASSIFY] Complete: total=25, success=25, llm=25, keyword_fallback=0, failed=0
```

---

## End-to-End Data Flow Example

This section traces a single article through all 4 stages.

### Stage 1: Article Arrives via RSS

```
Source: AP News (ap-news)
RSS Entry:
  title: "Congress Passes Sweeping Climate Bill in Dramatic Late-Night Vote"
  link: https://apnews.com/article/climate-bill-congress-vote-abc123
  published: 2026-01-28T03:15:00Z
```

**Ingestion actions:**
1. Compute `url_hash = SHA256("https://apnews.com/article/climate-bill-congress-vote-abc123")`
2. Deduper check: not a duplicate
3. Scrape full body from URL (BodyExtractor, ~4800 chars)
4. Deduplicate paragraphs: 2 duplicates removed (image caption repeated intro)
5. Upload to S3: `s3://ntrl-raw/raw/<uuid>/body` (gzip, text/plain)
6. Create StoryRaw row

### Stage 2: Classification

```
Input excerpt (first 2000 chars of body)

gpt-4o-mini returns:
{
  "domain": "governance_politics",
  "confidence": 0.95,
  "tags": {
    "geography": "us",
    "geography_detail": "US Congress, Washington D.C.",
    "actors": ["Congress", "Senate", "House"],
    "action_type": "legislation",
    "topic_keywords": ["climate", "legislation", "vote", "bill"]
  }
}

domain_mapper: governance_politics + us --> "us"
```

**StoryRaw updated:**
- `domain = "governance_politics"`
- `feed_category = "us"`
- `classification_model = "gpt-4o-mini"`
- `classification_method = "llm"`
- `classified_at = 2026-01-28T04:00:00Z`

### Stage 3: Neutralization

```
Call 1 (Filter):
  Input:  Full body (4800 chars from S3)
  Output: detail_full (neutralized, "dramatic" and "sweeping" removed)
          spans: [
            {phrase: "Sweeping", reason: "emotional_trigger", start: 142, end: 150},
            {phrase: "Dramatic Late-Night", reason: "urgency_inflation", start: 87, end: 106},
          ]

Call 2 (Synthesize):
  Input:  Full body (4800 chars from S3)
  Output: detail_brief (4 paragraphs, ~600 chars)

Call 3 (Compress):
  Input:  Full body + detail_brief
  Output:
    feed_title: "Congress Passes Climate Bill in Late-Night Vote"
    feed_summary: "The House and Senate approved the climate legislation after extended debate. The bill now heads to the president."
    detail_title: "Congress Passes Climate Legislation After Late-Night Vote"
```

### Stage 4: Brief Assembly

```
StoryNeutralized (status=success, is_current=True)
+ StoryRaw (feed_category="us", published_at=2026-01-28T03:15:00Z)
+ Source (slug="ap-news", priority=1)

--> DailyBriefItem:
    section="us", section_order=1, position=0 (top of U.S. section)
    feed_title="Congress Passes Climate Bill in Late-Night Vote"
    feed_summary="The House and Senate approved..."
    source_name="Associated Press"
    has_manipulative_content=True
```

---

## Cost-Efficient Development Workflow

### Re-neutralize Specific Articles

Use the `story_ids` parameter to avoid processing entire batches:

```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"story_ids": ["uuid1", "uuid2", "uuid3"], "force": true}'
```

### Test Span Detection Without Saving

The debug endpoint runs detection fresh without writing to the database:

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug/spans" \
  -H "X-API-Key: staging-key-123"
```

Returns the full pipeline trace:
- `llm_raw_response`: Raw LLM JSON
- `llm_phrases_count`: Phrases identified
- `pipeline_trace.after_position_matching`: After char offset resolution
- `pipeline_trace.after_quote_filter`: After removing quoted speech
- `pipeline_trace.after_false_positive_filter`: Final count

### Recommended Workflow for Prompt Changes

1. Pick 5-10 representative articles per change (not hundreds).
2. Target high-manipulation sources (The Sun, Daily Mail) for maximum signal.
3. Run `/debug/spans` first to see what changes before committing.
4. Re-neutralize the test set with `story_ids` + `force: true`.
5. Rebuild brief: `POST /v1/brief/run`.
6. Verify in the app.

---

## API Endpoint Reference

| Method | Endpoint | Stage | Description |
|---|---|---|---|
| `POST` | `/v1/ingest/run` | 1 | Trigger RSS ingestion |
| `POST` | `/v1/classify/run` | 2 | Classify pending articles |
| `POST` | `/v1/neutralize/run` | 3 | Neutralize pending articles |
| `POST` | `/v1/brief/run` | 4 | Assemble daily brief |
| `POST` | `/v1/pipeline/scheduled-run` | All | Run all 4 stages in sequence |
| `GET` | `/v1/status` | -- | System status and pipeline health |
| `GET` | `/v1/stories/{id}/debug` | -- | Article diagnostic info |
| `GET` | `/v1/stories/{id}/debug/spans` | -- | Fresh span detection trace |

All pipeline-trigger endpoints require the `X-API-Key` header with an admin key.

---

## Key Implementation Files

```
app/
+-- services/
|   +-- ingestion.py                    # Stage 1: RSS fetch, body extraction, S3 upload
|   +-- body_extractor.py              # Article body scraping (requests + newspaper3k)
|   +-- deduper.py                     # URL/title hash deduplication
|   +-- classifier.py                  # Legacy 5-section classifier (still used in ingest)
|   +-- llm_classifier.py             # Stage 2: LLM classification (reliability chain)
|   +-- domain_mapper.py              # Domain + geography --> feed_category mapping
|   +-- enhanced_keyword_classifier.py # Keyword fallback (20 domains, 30-50 kw each)
|   +-- neutralizer/
|   |   +-- __init__.py               # Stage 3: Main neutralizer, provider abstraction
|   |   +-- spans.py                  # Span utilities (positions, quotes, false positives)
|   |   +-- providers/                # LLM provider implementations
|   +-- brief_assembly.py             # Stage 4: Deterministic brief grouping
|   +-- alerts.py                     # Pipeline health alerting
|   +-- auditor.py                    # Output quality audit
+-- models.py                          # Domain, FeedCategory, NeutralizationStatus enums
+-- constants.py                       # TextLimits, PipelineDefaults, AlertThresholds
+-- routers/
|   +-- admin.py                       # Pipeline trigger endpoints, scheduled-run
+-- storage/
    +-- factory.py                     # S3/local storage provider factory
```
