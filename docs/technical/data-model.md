# NTRL Data Model

Complete database schema reference for the NTRL platform. All tables use PostgreSQL
with UUID primary keys and are managed through Alembic migrations.

---

## Table of Contents

1. [Enums](#enums)
2. [Entity-Relationship Overview](#entity-relationship-overview)
3. [Tables](#tables)
   - [sources](#sources)
   - [stories_raw](#stories_raw)
   - [stories_neutralized](#stories_neutralized)
   - [transparency_spans](#transparency_spans)
   - [manipulation_spans](#manipulation_spans)
   - [daily_briefs](#daily_briefs)
   - [daily_brief_items](#daily_brief_items)
   - [pipeline_logs](#pipeline_logs)
   - [pipeline_run_summaries](#pipeline_run_summaries)
   - [prompts](#prompts)
4. [Indexes](#indexes)
5. [Migration Chain](#migration-chain)

---

## Enums

### Section (Legacy)

Fixed sections for the daily brief with deterministic ordering. This enum is
**legacy** -- see `FeedCategory` for the current user-facing taxonomy.

| Value | Description |
|-------|-------------|
| `world` | International news |
| `us` | United States domestic news |
| `local` | Local/regional news |
| `business` | Business and economy |
| `technology` | Technology news |

### Domain

20 internal editorial domains used for classification. These are **system-only**
and never exposed to end users.

| Value | Area |
|-------|------|
| `global_affairs` | International relations, diplomacy, treaties |
| `governance_politics` | Government, elections, policy |
| `law_justice` | Legal proceedings, court rulings, legislation |
| `security_defense` | Military, national security, defense policy |
| `crime_public_safety` | Crime reporting, public safety events |
| `economy_macroeconomics` | GDP, inflation, monetary policy |
| `finance_markets` | Stock markets, banking, investments |
| `business_industry` | Corporate news, industry trends |
| `labor_demographics` | Employment, workforce, population data |
| `infrastructure_systems` | Transport, utilities, public works |
| `energy` | Oil, gas, renewables, energy policy |
| `environment_climate` | Climate change, conservation, pollution |
| `science_research` | Scientific discovery, research publications |
| `health_medicine` | Public health, medical advances, pharma |
| `technology` | Tech industry, software, hardware, AI |
| `media_information` | Journalism, social media, information ecosystems |
| `sports_competition` | Professional and amateur sports |
| `society_culture` | Social trends, arts, cultural events |
| `lifestyle_personal` | Consumer, travel, food, personal finance |
| `incidents_disasters` | Natural disasters, accidents, emergencies |

### FeedCategory

10 user-facing categories displayed in the NTRL feed. Each category has a fixed
ordinal position that determines display order in the UI.

| Ordinal | Value | Display Name |
|---------|-------|--------------|
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

### SpanAction

Actions taken on a flagged manipulative span during neutralization.

| Value | Description |
|-------|-------------|
| `removed` | Text was deleted entirely |
| `replaced` | Text was substituted with neutral alternative |
| `softened` | Text was toned down but preserved in meaning |

### SpanReason

Reason a span was flagged as manipulative.

| Value | Description |
|-------|-------------|
| `clickbait` | Sensational language designed to bait clicks |
| `urgency_inflation` | Artificially inflated sense of urgency |
| `emotional_trigger` | Language designed to provoke emotional reaction |
| `selling` | Promotional or advertorial language |
| `agenda_signaling` | Language that signals editorial or political agenda |
| `rhetorical_framing` | Loaded framing or rhetorical devices |
| `editorial_voice` | Opinionated language presented as reporting |

### PipelineStage

Discrete stages in the NTRL processing pipeline.

| Value | Description |
|-------|-------------|
| `ingest` | Fetch and store raw RSS articles |
| `normalize` | Clean and standardize raw content |
| `dedupe` | Detect and flag duplicate stories |
| `neutralize` | Remove manipulative language via LLM |
| `classify` | Assign domain and feed category |
| `brief_assemble` | Build daily brief from classified stories |

### PipelineStatus

Outcome status for any pipeline stage execution.

| Value | Description |
|-------|-------------|
| `started` | Stage has begun processing |
| `completed` | Stage finished successfully |
| `failed` | Stage encountered an error |
| `skipped` | Stage was intentionally bypassed |

### NeutralizationStatus

Outcome of the neutralization step for a single story.

| Value | Description |
|-------|-------------|
| `success` | Neutralization completed normally |
| `failed_llm` | LLM call failed (timeout, error, refusal) |
| `failed_audit` | Output failed post-processing audit checks |
| `failed_garbled` | Output was garbled or incoherent |
| `skipped` | Story was not sent through neutralization |

---

## Entity-Relationship Overview

```
sources
  |
  | 1:N
  v
stories_raw ----self-ref----> stories_raw (duplicate_of)
  |
  | 1:N (ordered desc by version)
  v
stories_neutralized
  |         |         |
  | 1:N     | 1:N     | N:1 (via daily_brief_items)
  v         v         v
transparency_spans    daily_brief_items
              |               |
manipulation_spans    daily_briefs

pipeline_logs ---------> stories_raw (nullable FK)
              ---------> daily_briefs (nullable FK)

pipeline_run_summaries    (standalone, correlated by trace_id)

prompts                   (standalone, hot-reloadable config)
```

### Core Data Flow

1. **sources** define RSS feeds to poll.
2. **stories_raw** stores every ingested article as the single source of truth.
   Deduplication marks rows via `is_duplicate` / `duplicate_of_id`.
3. **stories_neutralized** holds one or more versioned rewrites of each raw story.
   Only the row where `is_current = True` is served to clients.
4. **transparency_spans** and **manipulation_spans** attach to a neutralized
   story, providing character-level markup of what was changed and why.
5. **daily_briefs** aggregate a day's stories into an ordered, sectioned brief.
   **daily_brief_items** join briefs to neutralized stories with denormalized
   display fields for fast reads.
6. **pipeline_logs** record every stage execution for observability.
   **pipeline_run_summaries** roll up a full run into a single row.
7. **prompts** store versioned LLM prompts that the pipeline loads at runtime.

---

## Tables

### sources

RSS feed sources. The set is fixed for the POC phase.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | Unique identifier |
| `name` | String(255) | NOT NULL | Human-readable display name |
| `slug` | String(64) | UNIQUE, NOT NULL | URL-safe identifier, e.g. `"ap"`, `"reuters"` |
| `rss_url` | Text | NOT NULL | Full RSS feed URL |
| `is_active` | Boolean | NOT NULL, DEFAULT `True` | Whether the source is polled |
| `default_section` | String(32) | nullable | Hint for classification when no other signal exists |
| `created_at` | DateTime | NOT NULL | Row creation timestamp |
| `updated_at` | DateTime | nullable | Last modification timestamp |

**Relationships:**

- `stories` -- one-to-many to `stories_raw`

---

### stories_raw

Ingested articles. This is the **single source of truth** for all raw content
entering the system. Every article that passes through the ingest stage gets
exactly one row here.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | Unique identifier |
| `source_id` | UUID | FK(`sources.id`), NOT NULL | Originating RSS source |
| `original_url` | Text | NOT NULL | Canonical article URL |
| `original_title` | Text | NOT NULL | Title as received from the feed |
| `original_description` | Text | nullable | Description/summary from the feed |
| `original_author` | String(255) | nullable | Byline if available |
| `raw_content_uri` | String(512) | nullable | S3 object key for full article body |
| `raw_content_hash` | String(64) | nullable | SHA-256 hex digest of the article body |
| `raw_content_type` | String(64) | nullable | MIME type, e.g. `"text/plain"` |
| `raw_content_encoding` | String(16) | nullable | Compression, e.g. `"gzip"` |
| `raw_content_size` | Integer | nullable | Original body size in bytes |
| `raw_content_available` | Boolean | NOT NULL, DEFAULT `True` | Whether the body is still accessible in storage |
| `raw_content_expired_at` | DateTime | nullable | When the stored body was purged |
| `url_hash` | String(64) | NOT NULL | SHA-256 of the URL; used for fast deduplication |
| `title_hash` | String(64) | NOT NULL | SHA-256 of the normalized title; used for fuzzy dedupe |
| `published_at` | DateTime | NOT NULL | Publication timestamp from the feed |
| `ingested_at` | DateTime | NOT NULL | When NTRL ingested the article |
| `section` | String(32) | nullable | **Legacy** `Section` enum value |
| `domain` | String(40) | nullable | Internal `Domain` enum value (one of 20) |
| `feed_category` | String(32) | nullable | User-facing `FeedCategory` enum value (one of 10) |
| `classification_tags` | JSONB | nullable | Structured tags: `{geography, actors, action_type, ...}` |
| `classification_confidence` | Float | nullable | Model confidence score, 0.0 -- 1.0 |
| `classification_model` | String(64) | nullable | Model used for classification, e.g. `"gpt-4o-mini"` |
| `classification_method` | String(20) | nullable | `"llm"` or `"keyword_fallback"` |
| `classified_at` | DateTime(tz) | nullable | Timestamp of classification |
| `is_duplicate` | Boolean | NOT NULL, DEFAULT `False` | Whether this story is a duplicate |
| `duplicate_of_id` | UUID | FK(`stories_raw.id`), nullable | Points to the canonical story this duplicates |
| `feed_entry_id` | String(512) | nullable | RSS `<guid>` or `<id>` element |

**Relationships:**

- `source` -- many-to-one to `sources`
- `neutralized` -- one-to-many to `stories_neutralized`, ordered descending by `version`
- `duplicate_of` -- self-referential many-to-one to `stories_raw`

**Indexes:**

| Index | Column(s) | Purpose |
|-------|-----------|---------|
| `ix_stories_raw_url_hash` | `url_hash` | Fast URL-based deduplication lookup |
| `ix_stories_raw_title_hash` | `title_hash` | Fast title-based deduplication lookup |
| `ix_stories_raw_published_at` | `published_at` | Time-range queries for brief assembly |
| `ix_stories_raw_section` | `section` | Legacy section filtering |
| `ix_stories_raw_ingested_at` | `ingested_at` | Pipeline monitoring, recent-first queries |
| `ix_stories_raw_content_available` | `raw_content_available` | Filter stories with/without body content |
| `ix_stories_raw_domain` | `domain` | Internal domain filtering |
| `ix_stories_raw_feed_category` | `feed_category` | User-facing category queries |
| `ix_stories_raw_classified_at` | `classified_at` | Find unclassified stories, time-range queries |
| `ix_stories_raw_classification_method` | `classification_method` | Analytics on classification method distribution |

---

### stories_neutralized

Neutralized article versions produced by the LLM pipeline. Each raw story can
have multiple versions; only the row with `is_current = True` is served to
clients.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | Unique identifier |
| `story_raw_id` | UUID | FK(`stories_raw.id`), NOT NULL | Parent raw story |
| `version` | Integer | NOT NULL, DEFAULT `1` | Monotonically increasing version number |
| `is_current` | Boolean | NOT NULL, DEFAULT `True` | Whether this is the active version |
| `feed_title` | Text | NOT NULL | Neutralized title for feed display (preferred: 6 words max, hard limit: 12 words) |
| `feed_summary` | Text | NOT NULL | Neutralized summary for feed display (1--2 sentences, max 3 lines) |
| `detail_title` | Text | nullable | Precise headline for the detail view |
| `detail_brief` | Text | nullable | 3--5 paragraph prose brief for the detail view |
| `detail_full` | Text | nullable | Full filtered article text |
| `disclosure` | String(255) | NOT NULL, DEFAULT `"Manipulative language removed."` | Reader-facing disclosure statement |
| `has_manipulative_content` | Boolean | NOT NULL, DEFAULT `False` | Whether the original contained manipulative language |
| `model_name` | String(128) | nullable | LLM model used for neutralization |
| `prompt_version` | String(64) | nullable | Version identifier for the prompt used |
| `neutralization_status` | String(50) | NOT NULL, DEFAULT `"success"` | `NeutralizationStatus` enum value |
| `failure_reason` | Text | nullable | Human-readable explanation if status is not `success` |
| `created_at` | DateTime | NOT NULL | Row creation timestamp |

**Constraints:**

- UNIQUE(`story_raw_id`, `version`) -- prevents duplicate version numbers per story

**Indexes:**

| Index | Column(s) | Purpose |
|-------|-----------|---------|
| `ix_stories_neutralized_is_current` | `is_current` | Fast lookup of active versions |
| `ix_stories_neutralized_status` | `neutralization_status` | Filter by processing outcome |

**Relationships:**

- `story_raw` -- many-to-one to `stories_raw`
- `spans` -- one-to-many to `transparency_spans`
- `manipulation_spans` -- one-to-many to `manipulation_spans`

---

### transparency_spans

Character-level highlights marking manipulative phrases that were modified during
neutralization. Used by the ntrl-view UI to render inline diff-style annotations.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | Unique identifier |
| `story_neutralized_id` | UUID | FK(`stories_neutralized.id`), NOT NULL | Parent neutralized story |
| `field` | String(32) | NOT NULL | Source field: `"title"`, `"description"`, or `"body"` |
| `start_char` | Integer | NOT NULL | Start character position in the original text |
| `end_char` | Integer | NOT NULL | End character position in the original text |
| `original_text` | Text | NOT NULL | Exact text that was flagged |
| `action` | String(16) | NOT NULL | `SpanAction` enum: `removed`, `replaced`, `softened` |
| `reason` | String(32) | NOT NULL | `SpanReason` enum value describing why the text was flagged |
| `replacement_text` | Text | nullable | The neutral replacement text (for `replaced` and `softened` actions) |

---

### manipulation_spans

Rich analysis spans produced by the NTRL-SCAN pipeline (v2). Provides deeper
taxonomy-based classification of manipulative techniques with confidence scoring
and severity weighting.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | Unique identifier |
| `story_neutralized_id` | UUID | FK(`stories_neutralized.id`), NOT NULL | Parent neutralized story |
| `type_id_primary` | String(10) | NOT NULL | Primary manipulation type from `taxonomy.py`, e.g. `"A.1.1"` |
| `type_ids_secondary` | ARRAY(String) | nullable | Additional applicable manipulation type IDs |
| `segment` | String(20) | NOT NULL | Article segment: `title`, `deck`, `lede`, `body`, or `caption` |
| `span_start` | Integer | NOT NULL | Character index in the segment where the span begins |
| `span_end` | Integer | NOT NULL | Exclusive character index where the span ends |
| `original_text` | Text | NOT NULL | Exact flagged text |
| `confidence` | Float | NOT NULL | Detection confidence, 0.0 -- 1.0 |
| `severity` | Integer | NOT NULL | Base severity rating, 1 -- 5 |
| `severity_weighted` | Float | NOT NULL | Severity after applying segment-based multiplier |
| `action` | String(20) | NOT NULL | Resolution action: `remove`, `replace`, `rewrite`, `annotate`, or `preserve` |
| `rewritten_text` | Text | nullable | Replacement text (when action is `replace` or `rewrite`) |
| `rationale` | Text | nullable | Explanation of why this span was flagged |
| `detector_source` | String(20) | NOT NULL | Detection method: `lexical`, `structural`, or `semantic` |
| `exemptions_applied` | ARRAY(String) | nullable | List of exemption rules that modified handling |
| `rewrite_template_id` | String(64) | nullable | Identifier for the rewrite template used |
| `created_at` | DateTime | NOT NULL | Row creation timestamp |

---

### daily_briefs

Assembled daily news briefs. Each brief covers a date range up to `cutoff_time`
and can be versioned. Only the row with `is_current = True` for a given date
is served.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | Unique identifier |
| `brief_date` | DateTime | NOT NULL | The date this brief covers |
| `version` | Integer | NOT NULL, DEFAULT `1` | Brief version number |
| `total_stories` | Integer | NOT NULL, DEFAULT `0` | Number of stories included |
| `cutoff_time` | DateTime | NOT NULL | Only stories published before this time are included |
| `is_current` | Boolean | NOT NULL, DEFAULT `True` | Whether this is the active version for the date |
| `is_empty` | Boolean | NOT NULL, DEFAULT `False` | Whether the brief has zero stories |
| `empty_reason` | String(255) | nullable | Explanation if `is_empty = True` (e.g. "No stories passed neutralization") |
| `assembled_at` | DateTime | NOT NULL | When the brief was assembled |
| `assembly_duration_ms` | Integer | nullable | Time taken to assemble, in milliseconds |

**Relationships:**

- `items` -- one-to-many to `daily_brief_items`

---

### daily_brief_items

Individual stories within a daily brief. Uses deterministic ordering by section
and position. Display fields are **denormalized** from the neutralized story,
source, and raw story to enable single-query brief reads with no joins.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | Unique identifier |
| `brief_id` | UUID | FK(`daily_briefs.id`), NOT NULL | Parent brief |
| `story_neutralized_id` | UUID | FK(`stories_neutralized.id`), NOT NULL | Neutralized story this item represents |
| `section` | String(32) | NOT NULL | Section or `FeedCategory` value |
| `section_order` | Integer | NOT NULL | Deterministic section ordering (0=world, 1=us, 2=local, ...) |
| `position` | Integer | NOT NULL | Position within the section (0-indexed) |
| `feed_title` | Text | NOT NULL | Denormalized from `stories_neutralized.feed_title` |
| `feed_summary` | Text | NOT NULL | Denormalized from `stories_neutralized.feed_summary` |
| `source_name` | String(255) | NOT NULL | Denormalized from `sources.name` |
| `original_url` | Text | NOT NULL | Denormalized from `stories_raw.original_url` |
| `published_at` | DateTime | NOT NULL | Denormalized from `stories_raw.published_at` |
| `has_manipulative_content` | Boolean | NOT NULL | Denormalized from `stories_neutralized.has_manipulative_content` |

**Ordering Logic:**

Items are sorted first by `section_order` (ascending), then by `position`
(ascending) within each section. This produces a deterministic, reproducible
brief layout matching the `FeedCategory` ordinal values:

```
section_order 0 = world
section_order 1 = us
section_order 2 = local
section_order 3 = business
section_order 4 = technology
section_order 5 = science
section_order 6 = health
section_order 7 = environment
section_order 8 = sports
section_order 9 = culture
```

---

### pipeline_logs

Audit trail for individual pipeline stage executions. Every stage invocation --
whether it succeeds, fails, or is skipped -- produces a log row.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | Unique identifier |
| `stage` | String(32) | NOT NULL | `PipelineStage` enum value |
| `status` | String(16) | NOT NULL | `PipelineStatus` enum value |
| `story_raw_id` | UUID | FK(`stories_raw.id`), nullable | Associated story, if applicable |
| `brief_id` | UUID | FK(`daily_briefs.id`), nullable | Associated brief, if applicable |
| `trace_id` | String(36) | NOT NULL | UUID correlating all stages within a single pipeline run |
| `entry_url` | String(2048) | nullable | URL of the entry being processed |
| `entry_url_hash` | String(64) | nullable | SHA-256 of the entry URL |
| `failure_reason` | String(64) | nullable | Short failure code or category |
| `retry_count` | Integer | NOT NULL, DEFAULT `0` | Number of retries attempted |
| `started_at` | DateTime | NOT NULL | When the stage started |
| `finished_at` | DateTime | nullable | When the stage finished |
| `duration_ms` | Integer | nullable | Elapsed time in milliseconds |
| `error_message` | Text | nullable | Full error message or stack trace |
| `log_metadata` | JSONB | nullable | Arbitrary structured metadata |

---

### pipeline_run_summaries

Aggregated summary of a complete pipeline run. One row per run, correlated with
`pipeline_logs` rows via `trace_id`.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | Unique identifier |
| `trace_id` | String(36) | UNIQUE, NOT NULL | Correlates to `pipeline_logs.trace_id` |
| `started_at` | DateTime | NOT NULL | Run start time |
| `finished_at` | DateTime | NOT NULL | Run end time |
| `duration_ms` | Integer | NOT NULL | Total run duration in milliseconds |
| **Ingest Counters** | | | |
| `ingest_total` | Integer | NOT NULL | Total entries seen during ingest |
| `ingest_success` | Integer | NOT NULL | Entries successfully ingested |
| `ingest_body_downloaded` | Integer | NOT NULL | Entries with body content downloaded |
| `ingest_body_failed` | Integer | NOT NULL | Entries where body download failed |
| `ingest_skipped_duplicate` | Integer | NOT NULL | Entries skipped as duplicates |
| **Classify Counters** | | | |
| `classify_total` | Integer | NOT NULL | Total stories sent to classification |
| `classify_success` | Integer | NOT NULL | Stories successfully classified |
| `classify_llm` | Integer | NOT NULL | Stories classified via LLM |
| `classify_keyword_fallback` | Integer | NOT NULL | Stories classified via keyword fallback |
| `classify_failed` | Integer | NOT NULL | Stories where classification failed |
| **Neutralize Counters** | | | |
| `neutralize_total` | Integer | NOT NULL | Total stories sent to neutralization |
| `neutralize_success` | Integer | NOT NULL | Stories successfully neutralized |
| `neutralize_skipped_no_body` | Integer | NOT NULL | Stories skipped due to missing body content |
| `neutralize_failed` | Integer | NOT NULL | Stories where neutralization failed |
| **Brief Counters** | | | |
| `brief_story_count` | Integer | NOT NULL | Number of stories in the assembled brief |
| `brief_section_count` | Integer | NOT NULL | Number of sections with at least one story |
| **Run Metadata** | | | |
| `status` | String(20) | NOT NULL | Overall outcome: `completed`, `partial`, or `failed` |
| `alerts` | JSONB | nullable | Array of alert codes triggered during the run |
| `trigger` | String(20) | NOT NULL | What initiated the run: `scheduled`, `manual`, or `api` |

---

### prompts

Hot-reloadable LLM prompt storage. The pipeline reads prompts from this table at
runtime, allowing prompt changes without code deploys.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PRIMARY KEY | Unique identifier |
| `name` | String(64) | NOT NULL | Prompt identifier, e.g. `"system_prompt"`, `"neutralize_v2"` |
| `model` | String(64) | nullable | Target model, e.g. `"gpt-4o-mini"`. NULL means model-agnostic. |
| `content` | Text | NOT NULL | Full prompt text |
| `version` | Integer | NOT NULL, DEFAULT `1` | Prompt version number |
| `is_active` | Boolean | NOT NULL, DEFAULT `True` | Whether this prompt is in use |
| `created_at` | DateTime | NOT NULL | Row creation timestamp |
| `updated_at` | DateTime | nullable | Last modification timestamp |

**Constraints:**

- UNIQUE(`name`, `model`) -- only one active prompt per name-model pair

---

## Indexes

Summary of all indexes across the schema.

### stories_raw

| Index | Column(s) | Notes |
|-------|-----------|-------|
| `ix_stories_raw_url_hash` | `url_hash` | Deduplication by URL |
| `ix_stories_raw_title_hash` | `title_hash` | Deduplication by title |
| `ix_stories_raw_published_at` | `published_at` | Time-range queries |
| `ix_stories_raw_section` | `section` | Legacy section filter |
| `ix_stories_raw_ingested_at` | `ingested_at` | Recency queries |
| `ix_stories_raw_content_available` | `raw_content_available` | Content availability filter |
| `ix_stories_raw_domain` | `domain` | Internal domain filter |
| `ix_stories_raw_feed_category` | `feed_category` | User-facing category filter |
| `ix_stories_raw_classified_at` | `classified_at` | Classification status queries |
| `ix_stories_raw_classification_method` | `classification_method` | Method distribution analytics |

### stories_neutralized

| Index | Column(s) | Notes |
|-------|-----------|-------|
| `uq_story_raw_id_version` | `story_raw_id`, `version` | Unique constraint index |
| `ix_stories_neutralized_is_current` | `is_current` | Active version lookup |
| `ix_stories_neutralized_status` | `neutralization_status` | Status filtering |

### prompts

| Index | Column(s) | Notes |
|-------|-----------|-------|
| `uq_prompts_name_model` | `name`, `model` | Unique constraint index |

### pipeline_run_summaries

| Index | Column(s) | Notes |
|-------|-----------|-------|
| `uq_pipeline_run_summaries_trace_id` | `trace_id` | Unique constraint index |

---

## Migration Chain

Migrations are managed by **Alembic** and must maintain a **single-head** linear
chain. Never create branching migrations.

```
4b0a5b86cbe8  (base)
      |
      v
    001  -->  002  -->  003  -->  004  -->  005  -->  006
                                                       |
                                                       v
                                                48b2882dfa37
                                                       |
                                                       v
                                                4eb5c6286d76
                                                       |
                                                       v
                                                53b582a6786a
                                                       |
                                                       v
                                                b29c9075587e
                                                       |
                                                       v
                                          007_add_classification
                                                       |
                                                       v
                                                c7f3a1b2d4e5  (head)
```

### Migration Procedures

**Before creating a new migration:**

1. Verify single head: `alembic heads` must return exactly one revision.
2. Generate the migration: `alembic revision --autogenerate -m "description"`.
3. Review the generated file -- autogenerate does not catch all changes
   (e.g., enum value additions, index renames, data migrations).
4. Test upgrade and downgrade: `alembic upgrade head && alembic downgrade -1`.

**If multiple heads are detected:**

This indicates a branching conflict. Resolve by creating a merge migration:
`alembic merge heads -m "merge_branches"`. This should be rare and indicates
a process failure in coordinating schema changes.

---

## Design Notes

### UUID Primary Keys

All tables use UUID v4 primary keys generated at the application layer. This
avoids sequential ID enumeration, supports distributed inserts, and simplifies
cross-environment data movement.

### Denormalization Strategy

`daily_brief_items` intentionally denormalizes fields from `stories_neutralized`,
`stories_raw`, and `sources`. This eliminates joins when rendering the brief feed,
which is the highest-traffic read path. The tradeoff is write-time complexity:
brief assembly must copy current values into each item row.

### Versioning Pattern

Both `stories_neutralized` and `daily_briefs` use a version + `is_current`
pattern. Previous versions are retained for audit and debugging. Only the
`is_current = True` row for a given parent is served to clients.

### Content Storage

Article bodies are stored in S3, referenced by `raw_content_uri` in
`stories_raw`. The database stores only metadata (hash, type, encoding, size)
and an availability flag. When content is purged, `raw_content_available` is set
to `False` and `raw_content_expired_at` is set.

### Classification Dual-Path

Classification can run via LLM (`classification_method = "llm"`) or fall back to
keyword matching (`classification_method = "keyword_fallback"`). The method,
model, and confidence are recorded on `stories_raw` for quality monitoring.

### Span Models (v1 vs v2)

Two span tables coexist:

- **transparency_spans** (v1): Simple action/reason pairs for the ntrl-view UI.
  These power the inline highlights showing what was changed and why.
- **manipulation_spans** (v2): Rich NTRL-SCAN analysis with taxonomy codes,
  confidence/severity scoring, detector source, and exemption tracking. This
  is the newer, more granular model.

Both relate to `stories_neutralized` and can coexist for the same story.
