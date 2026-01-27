# CLAUDE.md - Project Context for Claude Code

## Project Overview

NTRL API is a neutral news backend service that removes manipulative language from news articles and creates calm, deterministic news briefs.

## Core Architecture Principle

**The original article body is the single source of truth.**

```
INGEST:        RSS → Database (metadata) + S3 (body.txt)
CLASSIFY:      body.txt → domain (20) + feed_category (10) + tags
NEUTRALIZE:    body.txt → ALL outputs (title, summary, brief, full, spans)
BRIEF ASSEMBLE: Group by feed_category (10 categories) → DailyBrief
DISPLAY:       Neutralized content by default, originals only in "ntrl view"
```

- RSS title/description are stored for audit but NOT used for neutralization
- All user-facing content is derived from the scraped article body
- Transparency spans reference the original body for highlighting

See `docs/ARCHITECTURE.md` for full details.

## The 4-View Content Architecture

| View | UI Location | Content Source | Description |
|------|-------------|----------------|-------------|
| **Original** | ntrl-view (highlight OFF) | `original_body` | Original text from S3 (minus publisher cruft) |
| **ntrl-view** | ntrl-view (highlight ON) | `original_body` + `spans` | Same text with manipulative phrases highlighted |
| **Full** | Article Detail (Full tab) | `detail_full` | LLM-neutralized full article, grammar-corrected |
| **Brief** | Article Detail (Brief tab) | `detail_brief` | LLM-synthesized short summary |

**Key insight**: Spans ALWAYS reference positions in `original_body`, not in `detail_full`. This allows highlighting the original text to show what was changed.

## LLM Neutralization: Why Synthesis > In-Place Filtering

### The Problem with In-Place Filtering
Asking LLMs to surgically edit text while tracking character positions produces **garbled output**:
- LLMs are bad at counting characters
- Removing words breaks grammar ("She was to the event...")
- JSON position tracking adds cognitive load

### The Solution: Synthesis Fallback
When filtering fails, use synthesis mode:
1. Ask LLM to rewrite the full article neutrally (plain text, no JSON)
2. Detect spans separately using pattern matching on original body
3. Result: readable output + valid spans

### Current Implementation
- Primary: JSON-based filter prompt (tries to track spans)
- Fallback: Synthesis prompt (plain text) + pattern-based span detection
- See `_synthesize_detail_full_fallback()` in `neutralizer/__init__.py`

## Tech Stack

- **Framework**: FastAPI (Python 3.11) with Uvicorn
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Migrations**: Alembic
- **Storage**: S3 or local filesystem for raw articles
- **AI**: Pluggable neutralizers (mock, OpenAI, Anthropic, Gemini)
- **NLP**: spaCy (en_core_web_sm) for structural detection, lazy-loaded via `@lru_cache`
- **Config**: pydantic-settings (`app/config.py`) — validates all env vars on startup
- **Rate Limiting**: slowapi (100/min global, 10/min admin, 5/min pipeline triggers)
- **Caching**: cachetools TTLCache for brief (15min), stories (1hr), transparency (1hr)
- **Dependencies**: Pipenv (all versions pinned)

## Key Commands

```bash
# Run the server
pipenv run uvicorn app.main:app --reload --port 8000

# Run tests
pipenv run python -m pytest tests/

# Database migrations
pipenv run alembic upgrade head
pipenv run alembic revision --autogenerate -m "description"

# Install dependencies
pipenv install
```

## Development Mode Rules (IMPORTANT)

During development/testing, follow these resource-conservation rules:

### Limits
- **Ingestion**: Max 25 articles per run
- **Classification**: 200 articles per pipeline run (covers all ingested articles)
- **Neutralization**: Max 25 articles per run
- **Articles in UI**: Only show articles from last 24 hours

### Cleanup
- Articles older than 24 hours are automatically hidden (`is_active=False`)
- The `scheduled-run` endpoint handles this automatically
- Hidden articles remain in DB but don't appear in briefs

### Testing Workflow
1. Run ingestion (limit 25)
2. Run classification (auto-classifies pending articles)
3. Run neutralization (limit 25)
4. Rebuild brief
5. Test in UI
6. Old articles auto-hidden on next scheduled run

### Before Production
- [ ] Increase `max_items_per_source` in ScheduledRunRequest (50+)
- [ ] Increase `neutralize_limit` in ScheduledRunRequest (100+)
- [ ] Review ingestion timing (currently every 4 hours)
- [ ] Decide on article retention policy
- [ ] Review cleanup behavior

## Staging Environment

- **API URL**: `https://api-staging-7b4d.up.railway.app`
- **Admin API Key**: `staging-key-123` (use in `X-API-Key` header)

### Railway Cron Setup

The scheduled pipeline should run on Railway (NOT locally). Set up in Railway dashboard:

1. Go to Railway project → Settings → Cron
2. Add cron job:
   - **Schedule**: `0 */4 * * *` (every 4 hours)
   - **Endpoint**: `POST /v1/pipeline/scheduled-run`
   - **Headers**: `X-API-Key: staging-key-123`, `Content-Type: application/json`
   - **Body**: `{}` (uses defaults: classify_limit=200, cleanup enabled)

The `scheduled-run` endpoint automatically:
- Ingests up to 25 new articles
- Classifies up to 200 pending articles (LLM → domain + feed_category)
- Neutralizes up to 25 pending articles
- Rebuilds the brief (grouped by 10 feed categories)
- Hides articles older than 24 hours

### Common Operations

```bash
# Trigger RSS ingestion
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/ingest/run" \
  -H "X-API-Key: staging-key-123"

# Classify pending articles (LLM-powered domain + feed category)
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/classify/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"limit": 25}'

# Reclassify all articles (e.g., after prompt changes)
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/classify/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"limit": 200, "force": true}'

# Neutralize pending articles (or force re-neutralize)
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"limit": 50, "force": true}'

# Rebuild the daily brief
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/brief/run" \
  -H "X-API-Key: staging-key-123"

# Check system status
curl "https://api-staging-7b4d.up.railway.app/v1/status"

# Debug a specific story (see content lengths, readability, span validity)
curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug" \
  -H "X-API-Key: staging-key-123"
```

### Debug Endpoint (`/v1/stories/{id}/debug`)
Returns diagnostic info for troubleshooting content display:
- `original_body`: First 500 chars from S3
- `original_body_length`: Total length
- `detail_full`: First 500 chars of neutralized text
- `detail_full_readable`: Boolean - passes grammar checks
- `issues`: Array of detected problems (garbled text, broken spans, etc.)
- `span_count`: Number of transparency spans
- `spans_sample`: First 3 spans for inspection

### Span Detection Debug Endpoint (`/v1/stories/{id}/debug/spans`)
Runs span detection fresh and returns full pipeline trace:
```bash
curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug/spans" \
  -H "X-API-Key: staging-key-123" | python3 -m json.tool
```

Returns:
- `llm_raw_response`: Raw JSON from LLM
- `llm_phrases_count`: Number of phrases LLM returned
- `llm_phrases`: All phrases with reason/action/replacement
- `pipeline_trace`:
  - `after_position_matching`: Count after finding positions in text
  - `after_quote_filter`: Count after removing quoted speech
  - `after_false_positive_filter`: Final count
  - `phrases_not_found_in_text`: LLM hallucinations
  - `phrases_filtered_by_quotes`: Removed by quote filter
  - `phrases_filtered_as_false_positives`: Removed by FP filter
- `final_spans`: Final spans with positions

Use this to debug why phrases aren't being detected or are being filtered out.

### Cost-Efficient Testing (IMPORTANT)
To minimize API costs during development:

1. **Use `story_ids` parameter** - Only re-neutralize specific articles:
```bash
curl -X POST ".../v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"story_ids": ["id1", "id2", "id3"], "force": true}'
```

2. **Test via debug endpoint first** - `/debug/spans` runs detection without saving to DB

3. **Pick 5-10 representative articles** per prompt change, not hundreds

4. **Target high-manipulation sources** - The Sun/Daily Mail have more manipulation than BBC/Reuters

5. **Use test script**:
```bash
python scripts/test_span_detection.py --article-id <uuid>  # Single article
python scripts/test_span_detection.py --limit 5           # Multiple from brief
```

## Project Structure

```
app/
├── main.py              # FastAPI entry point (CORS, rate limiting, exception handler)
├── config.py            # Pydantic-settings config validation (loads from env)
├── constants.py         # Centralized magic constants (TextLimits, PipelineDefaults, etc.)
├── database.py          # DB configuration
├── models.py            # SQLAlchemy ORM models (Domain, FeedCategory, Section enums)
├── taxonomy.py          # 115 manipulation types (v2)
├── routers/
│   ├── admin.py         # V1 admin endpoints (ingest, classify, neutralize, brief, pipeline)
│   ├── brief.py         # V1 brief endpoints (TTL-cached)
│   ├── stories.py       # V1 story endpoints + debug endpoint (TTL-cached)
│   ├── sources.py       # V1 sources endpoints
│   └── pipeline.py      # V2 pipeline endpoints
├── schemas/             # Pydantic request/response schemas
├── services/
│   ├── ingestion.py     # RSS ingestion (SSL verified)
│   ├── llm_classifier.py           # LLM article classification (gpt-4o-mini → gemini fallback)
│   ├── domain_mapper.py            # Domain + geography → feed_category mapping
│   ├── enhanced_keyword_classifier.py  # 20-domain keyword fallback classifier
│   ├── neutralizer/     # V1 neutralizer module (refactored from single file)
│   │   ├── __init__.py  # Main neutralizer service, synthesis fallback
│   │   ├── providers/   # LLM provider implementations (OpenAI, Gemini, Anthropic)
│   │   └── spans.py     # Span detection utilities (find_phrase_positions, etc.)
│   ├── brief_assembly.py # Groups by feed_category (10 categories)
│   ├── alerts.py        # Pipeline alerting (includes classify fallback rate)
│   └── ...
├── storage/             # Object storage providers (S3, local)
└── jobs/                # Background jobs
```

## Text/UI Length Constraints

When UI text appears too long or gets truncated, the constraint is usually in the **backend LLM prompt**, not frontend CSS.

### Where to Look
- `app/services/neutralizer/` - Contains all LLM prompts (refactored into module)
- Search for `feed_summary`, `feed_title`, `detail_title`, `detail_brief`

### Workflow for Length Changes
1. Find constraint in `neutralizer/__init__.py` prompt
2. Reduce limit (add 15-20% buffer for LLM inaccuracy)
3. Deploy to Railway (push to main)
4. Re-neutralize: `POST /v1/neutralize/run` with `force: true`
5. Rebuild brief: `POST /v1/brief/run`
6. Verify in app

## Article Classification Pipeline (Jan 2026)

### Overview

Articles are classified into 20 internal **domains** (editorial taxonomy) and mapped to 10 user-facing **feed categories**. Classification runs as a separate pipeline stage between INGEST and NEUTRALIZE.

### Pipeline Stage: CLASSIFY

```
StoryRaw (from INGEST) → fetch body from S3 (first 2000 chars)
  → LLM classify (gpt-4o-mini primary, gemini-2.0-flash fallback)
  → Enhanced keyword classifier (last resort, <1% of articles)
  → domain_mapper: domain + geography → feed_category
  → Update StoryRaw with: domain, feed_category, classification_tags, confidence, model, method
```

**Reliability chain (4 attempts):**
1. gpt-4o-mini with full prompt (JSON mode)
2. gpt-4o-mini with simplified prompt
3. gemini-2.0-flash with full prompt
4. Enhanced keyword classifier (flagged as `classification_method="keyword_fallback"`)

### Enums (in `app/models.py`)

**Domain** (20 internal values): `global_affairs`, `governance_politics`, `law_justice`, `security_defense`, `crime_public_safety`, `economy_macroeconomics`, `finance_markets`, `business_industry`, `labor_demographics`, `infrastructure_systems`, `energy`, `environment_climate`, `science_research`, `health_medicine`, `technology`, `media_information`, `sports_competition`, `society_culture`, `lifestyle_personal`, `incidents_disasters`

**FeedCategory** (10 user-facing): `world`, `us`, `local`, `business`, `technology`, `science`, `health`, `environment`, `sports`, `culture`

### Domain → Feed Category Mapping (`domain_mapper.py`)

15 domains map directly regardless of geography. 5 domains (`governance_politics`, `law_justice`, `security_defense`, `crime_public_safety`, `incidents_disasters`) are geography-dependent — they map to `us`/`local`/`world` based on the LLM's geography tag.

### StoryRaw Classification Columns

| Column | Type | Description |
|--------|------|-------------|
| `domain` | String(40) | Internal domain (20 values) |
| `feed_category` | String(32) | User-facing category (10 values) |
| `classification_tags` | JSONB | `{geography, geography_detail, actors, action_type, topic_keywords}` |
| `classification_confidence` | Float | 0.0-1.0 (LLM self-reported, 0.0 for keyword fallback) |
| `classification_model` | String(64) | e.g. "gpt-4o-mini", "gemini-2.0-flash" |
| `classification_method` | String(20) | "llm" or "keyword_fallback" |
| `classified_at` | DateTime | When classification was performed |

### Brief Assembly

Brief groups stories by `feed_category` (10 categories) in fixed order: World, U.S., Local, Business, Technology, Science, Health, Environment, Sports, Culture. Articles without `feed_category` are **skipped** (they'll appear after the next classify run). The legacy `section` fallback was removed in Jan 2026 because the `SectionClassifier` only knew 5 sections and defaulted unknown articles to "world", causing sports/culture articles to be misclassified.

### Monitoring

Pipeline alerts fire if keyword fallback rate exceeds 1% (`CLASSIFY_FALLBACK_RATE_HIGH`).

### Classify Endpoint

```bash
POST /v1/classify/run
Body: {"limit": 25, "force": false, "story_ids": null}
```

- `limit`: Max articles to classify (default 25)
- `force`: Reclassify already-classified articles
- `story_ids`: Classify specific articles by ID

## UI Verification Workflow

### Step 1: Deploy Backend Changes
```bash
cd /Users/ericrbrown/Documents/NTRL/code/ntrl-api
git add -A && git commit -m "description" && git push origin main
# Wait ~30s for Railway deploy
curl "https://api-staging-7b4d.up.railway.app/v1/status"
```

### Step 2: Re-neutralize Test Articles
```bash
# Re-neutralize with new code
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"limit": 5, "force": true}'

# Rebuild brief to include new content
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/brief/run" \
  -H "X-API-Key: staging-key-123"
```

### Step 3: Check Debug Endpoint
```bash
# Get a story ID from the brief
curl -s "https://api-staging-7b4d.up.railway.app/v1/brief?hours=24" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(d['sections'][0]['stories'][0]['id'])"

# Check debug info
curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug" \
  -H "X-API-Key: staging-key-123" | python3 -m json.tool
```

### Step 4: Test in App (Playwright - RECOMMENDED)
```bash
cd /Users/ericrbrown/Documents/NTRL/code/ntrl-app

# Ensure Expo is running
npm start -- --web &

# Create and run capture script
cat > capture-screens.cjs << 'EOF'
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await page.goto('http://localhost:8081');
  await page.waitForTimeout(4000);
  await page.screenshot({ path: '/tmp/web-feed.png' });

  // Click article, capture Brief/Full/ntrl views
  await page.click('text=<article-title>');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: '/tmp/web-brief.png' });

  await page.click('text=Full');
  await page.waitForTimeout(1000);
  await page.screenshot({ path: '/tmp/web-full.png' });

  await page.click('text=ntrl view');
  await page.waitForTimeout(2000);
  await page.screenshot({ path: '/tmp/web-ntrl.png' });

  await browser.close();
})();
EOF
node capture-screens.cjs

# View screenshots
# Use Read tool on /tmp/web-feed.png, /tmp/web-brief.png, etc.
```

### Alternative: iOS Simulator (if Playwright unavailable)
```bash
# Boot simulator
xcrun simctl boot "iPhone 17 Pro"
open -a Simulator

# Open app via Expo
xcrun simctl openurl booted "exp://127.0.0.1:8081"
sleep 10

# Capture screenshot
xcrun simctl io booted screenshot /tmp/sim-screenshot.png
```

**Note**: Maestro often has driver timeout issues. Playwright is more reliable for automated UI capture.

## Console Logging (Frontend Debug)

The frontend logs diagnostic info to console, **guarded by `__DEV__`** so they are stripped in production builds:
- `[ArticleDetail] Transparency data received:` - spans and originalBody info
- `[ArticleDetail] Detail content:` - brief/full lengths and previews
- `[ArticleDetail] Navigating to NtrlView:` - what's being passed
- `[NtrlView] Received data:` - what NtrlView received

Check these in Expo dev tools or browser console. In production, these are no-ops.

## Prompt Optimization Tips

### For detail_full (neutralized full article)
- Use synthesis mode (plain text output) for reliability
- Don't ask LLM to track character positions
- Focus prompt on: grammar preservation, fact preservation, manipulation removal
- Validate output isn't garbled before saving

### For detail_brief (summary)
- This works well - synthesis is natural for LLMs
- Keep 3-5 paragraphs, no headers/bullets
- Emphasize: only use info from source, no added context

### For feed_title/feed_summary
- Strict character limits (LLMs overcount, so ask for 10-15% less)
- Examples > instructions for length compliance

## Highlight Accuracy Testing

### Test Framework
- `tests/test_highlight_accuracy.py` - Main accuracy tests against gold standard corpus
- `tests/test_span_accuracy_e2e.py` - E2E tests for specific phrase detection (must-flag/must-not-flag)
- `tests/fixtures/gold_standard/` - Gold standard span annotations (10 articles)
- `tests/fixtures/test_corpus/` - Test article corpus
- `scripts/verify_gold_positions.py` - Verify/fix gold standard positions
- `scripts/review_accuracy.py` - Human review CLI
- `scripts/test_span_detection.py` - Test span detection against staging API

### Running Tests
```bash
# Pattern-based tests (fast, no API key)
pipenv run pytest tests/test_highlight_accuracy.py -m "not llm" -v

# LLM-based accuracy tests (requires OPENAI_API_KEY in .env)
pipenv run pytest tests/test_highlight_accuracy.py -m llm -v -s

# E2E span accuracy validation (tests specific phrases)
pipenv run pytest tests/test_span_accuracy_e2e.py -m llm -v -s

# Verify gold standard positions
python scripts/verify_gold_positions.py --all

# Human review with LLM
python scripts/review_accuracy.py --article 003 --provider openai
```

### E2E Accuracy Tests (`test_span_accuracy_e2e.py`)
Tests specific phrase detection scenarios:
- **must_flag**: Phrases that MUST be detected (ecstatic, furious, A-list celebs, whopping)
- **must_not_flag**: Phrases that must NOT be detected (crisis management, literal "car slammed into wall")
- **Quoted speech**: Verifies content inside quotes is excluded
- **Professional terms**: Verifies legitimate professions aren't flagged

### Current Metrics (gpt-4o-mini, Jan 2026)
| Metric | Pattern-Based | LLM-Based | Target | Status |
|--------|---------------|-----------|--------|--------|
| Precision | 5.87% | **96.43%** | 80% | **Exceeded** |
| Recall | 69.23% | **77.14%** | 85% | Close |
| F1 Score | 10.82% | **85.71%** | 75% | **Exceeded** |

**Recent improvements:**
- Fixed curly quote filtering bug (see "Curly Quote Bug" section below)
- Added emotional state words: ecstatic, outraged, furious, seething, gutted
- Added tabloid vocabulary: A-list, celeb, haunts, mogul, sound the alarm
- Added emphasis superlatives: whopping, staggering, eye-watering
- Added professional terms to false positive filter: crisis management, public relations
- Expanded gold standard based on LLM review (10 new spans added)
- Improved span matching to handle phrase containment

### LLM Span Detection Architecture

**How it works:**
1. LLM analyzes article and returns `{"phrases": [...]}` with manipulative phrases
2. `find_phrase_positions()` maps phrase text to character positions in original body
3. `filter_spans_in_quotes()` removes phrases inside quoted speech
4. `filter_false_positives()` removes known false positive phrases
5. Result: spans with accurate positions for highlighting in UI

**Key files:**
- `neutralizer/__init__.py`: `DEFAULT_SPAN_DETECTION_PROMPT` - Conservative prompt with "NEVER FLAG" guidance
- `neutralizer/__init__.py`: `detect_spans_via_llm_openai/gemini/anthropic()` - Provider-specific API calls
- `neutralizer/spans.py`: `find_phrase_positions()`, `filter_spans_in_quotes()`, span utilities
- `neutralizer/__init__.py`: `filter_false_positives()` - Removes known false positives like "bowel cancer"
- `neutralizer/__init__.py`: `detect_spans_debug_openai()` - Debug version returning pipeline trace
- `neutralizer/__init__.py`: `QUOTE_PAIRS` - Quote character mapping (uses Unicode escapes)
- `neutralizer/__init__.py`: `FALSE_POSITIVE_PHRASES` - Professional terms and medical terminology

**Logging format** (`[SPAN_DETECTION]` prefix):
```
[SPAN_DETECTION] Starting LLM call, model=gpt-4o-mini, body_length=4721
[SPAN_DETECTION] LLM responded, response_length=523
[SPAN_DETECTION] LLM returned 17 phrases
[SPAN_DETECTION] Pipeline: position_match=22 → quote_filter=13 → fp_filter=13
[SPAN_DETECTION] False positive filter removed 2: ['crisis management', 'public relations']
```

**Manipulation Taxonomy (14 categories in prompt):**

| # | Category | Examples |
|---|----------|----------|
| 1 | URGENCY INFLATION | BREAKING, JUST IN, scrambling |
| 2 | EMOTIONAL TRIGGERS | shocking, devastating, slams |
| 3 | CLICKBAIT | You won't believe, Here's what happened |
| 4 | SELLING/HYPE | revolutionary, game-changer |
| 5 | AGENDA SIGNALING | radical left, extremist |
| 6 | LOADED VERBS | slammed, blasted, admits, claims |
| 7 | URGENCY INFLATION (subtle) | Act now, Before it's too late |
| 8 | AGENDA FRAMING | "the crisis at the border" |
| 9 | SPORTS/EVENT HYPE | brilliant, blockbuster, massive, beautiful (events) |
| 10 | LOADED PERSONAL DESCRIPTORS | handsome, unfriendly face, menacing |
| 11 | HYPERBOLIC ADJECTIVES | punishing, soaked in blood, "of the year" |
| 12 | LOADED IDIOMS | came under fire, in the crosshairs, took aim at |
| 13 | ENTERTAINMENT/CELEBRITY HYPE | romantic escape, whirlwind romance, A-list pair |
| 14 | **EDITORIAL VOICE** | we're glad, as it should, Border Czar, lunatic |

Categories 9-12 added Jan 2026. Categories 13-14 added Jan 2026 for tabloid/editorial detection.

**SpanReason enum values** (in `models.py`):
- `clickbait`, `urgency_inflation`, `emotional_trigger`, `selling`
- `agenda_signaling`, `rhetorical_framing`, `editorial_voice`

**JSON format (required by OpenAI json_object mode):**
```json
{"phrases": [
  {"phrase": "SHOCKING", "reason": "emotional_trigger", "action": "remove", "replacement": null}
]}
```

**Fallback behavior (updated Jan 2026):**
- LLM returns `[]` (empty array) = article is clean, trust it, show 0 spans
- LLM API call fails = returns `DetailFullResult` with `status="failed_llm"`, article saved as failed
- LLM produces garbled output = returns `DetailFullResult` with `status="failed_garbled"`
- **No fallback to MockNeutralizerProvider** - failed articles are tracked, not shown to users

**IMPORTANT:** MockNeutralizerProvider is for testing only, never used as production fallback. It has ~5% precision and produces garbled output by removing words without grammar repair.

### Model Consistency: Production vs Debug (FIXED Jan 2026)

**Both production and debug now use `gpt-4o-mini`** (via `OPENAI_MODEL` env var, default `gpt-4o-mini`).

Previously, debug endpoint used `gpt-4o` while production used `gpt-4o-mini`, causing confusing discrepancies.

### Prompt Restructuring (Jan 2026)

The span detection prompt was restructured to improve `gpt-4o-mini` performance on tabloid content:

1. **WHAT TO FLAG now comes BEFORE exclusions** - leads with detection, not restrictions
2. **Softened conservative language** - "Balance precision with recall" instead of "BE CONSERVATIVE"
3. **Added tabloid source awareness** - prompt notes that tabloid sources have more manipulation
4. **Added tabloid examples** - Katie Price-style examples with emotional amplification
5. **Added editorial voice category** - detects "we're glad", "as it should", "Border Czar", etc.

### Editorial Content Detection (Jan 2026)

**ContentTypeClassifier** (`classifier.py`) detects editorial content using regex patterns:
- `we('re| are| believe| hope)`, `as it should`, `of course`, `Border Czar`, etc.
- Returns `ContentType.EDITORIAL` if 3+ signals found (or 2+ in short text)

**Editorial synthesis fallback** (`detail_full_gen.py`):
- When content is editorial OR has >15 spans, uses full synthesis instead of span-guided rewriting
- `EDITORIAL_SYNTHESIS_PROMPT` rewrites entire article neutrally
- Result: Full view removes editorial voice entirely (like Brief does)

### Known Issues & Next Steps
- Pattern-based fallback should probably just report an error instead of showing wrong data
- Article 010 has lower accuracy (38% F1) due to LLM flagging quoted speech
- Gold standard corpus version is now 1.1 (human reviewed)

### Neutralization Status Tracking (Jan 2026)

The neutralization pipeline now tracks success/failure status for each article:

**Database fields** (`StoryNeutralized` model):
- `neutralization_status`: "success", "failed_llm", "failed_garbled", "failed_audit", "skipped"
- `failure_reason`: Detailed error message for debugging

**Architecture principles:**
1. **Never use MockNeutralizerProvider as fallback** - it produces garbage output
2. **Only show successfully neutralized articles** - failed articles filtered from brief/stories
3. **Track failures in database** - for debugging and monitoring
4. **Return failure status instead of fallback** - `DetailFullResult.status` field

**Key code locations:**
- `app/models.py`: `NeutralizationStatus` enum, new fields on `StoryNeutralized`
- `app/services/neutralizer/__init__.py`: `DetailFullResult` dataclass with `status` and `failure_reason`
- `app/services/brief_assembly.py`: Filters by `neutralization_status == "success"`
- `app/routers/stories.py`: Filters neutralized stories by status

### Quote Filtering with Contraction Detection

The quote filter now handles apostrophes in contractions correctly:

**Problem solved:** Text like "They won't believe it's 'shocking'" was breaking quote detection because apostrophes in contractions (won't, it's) were treated as quote boundaries.

**Solution:** `is_contraction_apostrophe()` function detects contractions (letters on both sides of apostrophe) and skips them during quote boundary detection.

**Key file:** `app/services/neutralizer/__init__.py` - `is_contraction_apostrophe()` and `filter_spans_in_quotes()`

### Curly Quote Bug (CRITICAL - Fixed Jan 2026)

**Problem:** The quote filter wasn't filtering content inside curly quotes (`"` `"` `'` `'`). Many news articles use curly/smart quotes, not straight quotes.

**Root cause:** The `QUOTE_PAIRS` dictionary was supposed to contain curly quote Unicode characters, but they were rendered as straight quotes when the file was saved/edited. The code only matched ord 34/39 (straight), not ord 8220/8221/8216/8217 (curly).

**Fix:** Use Unicode escape sequences instead of literal characters:
```python
# WRONG - curly quotes may be converted to straight quotes by editors
QUOTE_PAIRS = {
    '"': '"',   # This comment says "curly" but chars are straight!
    '"': '"',
}

# CORRECT - Unicode escapes are unambiguous
QUOTE_PAIRS = {
    '"': '"',           # Straight double quote (U+0022)
    '\u201c': '\u201d', # Curly double quotes (U+201C -> U+201D)
    "'": "'",           # Straight single quote (U+0027)
    '\u2018': '\u2019', # Curly single quotes (U+2018 -> U+2019)
}
```

**Best practice:** When defining Unicode characters in Python source files, **always use escape sequences** (`\u201c`) rather than literal characters. Editors, copy/paste, and file encoding can silently convert special characters.

**How to verify quote filter is working:**
```bash
# Check QUOTE_PAIRS has correct Unicode code points
pipenv run python3 -c "
from app.services.neutralizer import QUOTE_PAIRS  # module re-exports
for k, v in QUOTE_PAIRS.items():
    print(f'Key: ord={ord(k)}, Val: ord={ord(v)}')
"
# Should show: 34, 34, 8220, 8221, 39, 39, 8216, 8217
```

**Impact:** Before fix, quoted speech like `"That's shocking," he said` was being highlighted. After fix, content inside both straight AND curly quotes is correctly excluded.

### Known Test Failures (Expected)

6 tests fail in `test_neutralizer.py` and `test_article_neutralization.py` - **these are expected**:

| Test | Why It Fails |
|------|--------------|
| `test_preserves_factual_content` | MockNeutralizerProvider produces garbled output |
| `test_neutralize_clean_content` | Mock finds false positives in clean content |
| `test_neutralize_emotional_triggers` | Mock doesn't detect emotional triggers |
| `test_neutralize_detail_full_*` | Mock pattern-matching produces garbled grammar |

These failures confirm why we removed MockNeutralizerProvider as a fallback - it has ~5% precision and produces unreadable output. The real LLM providers (OpenAI, Gemini, Anthropic) work correctly.

**Options to fix:**
1. Mark tests as `xfail` (expected failure)
2. Update tests to reflect mock's known limitations
3. Remove mock-specific tests

### Completed Fixes (Jan 2026)

1. ✅ Quote filtering for single/curly quotes (`filter_spans_in_quotes()`)
2. ✅ Brief validation with retry (`_neutralize_detail_brief()` in all providers)
3. ✅ Feed summary validation with retry (`_neutralize_feed_outputs()` in all providers)
4. ✅ Character limit tightening (feed_summary: 100-120 chars, hard max 130)
5. ✅ **Architecture fix**: Removed MockNeutralizerProvider fallbacks, added failure tracking
6. ✅ **Contraction detection**: Apostrophes in won't/it's no longer break quote filtering
7. ✅ **Curly quote fix**: QUOTE_PAIRS now uses Unicode escapes to ensure curly quotes work
8. ✅ **Expanded prompt**: Added emotional state words, tabloid vocabulary, emphasis superlatives
9. ✅ **Professional terms**: crisis management, public relations added to false positive filter
10. ✅ **Structured logging**: `[SPAN_DETECTION]` prefix for pipeline instrumentation
11. ✅ **Debug model fix**: Debug endpoint now uses same model as production (gpt-4o-mini)
12. ✅ **Prompt restructuring**: WHAT TO FLAG before EXCLUSIONS, softened conservative language
13. ✅ **Editorial voice category**: Category 14 detects "we're glad", "Border Czar", "lunatic", etc.
14. ✅ **ContentTypeClassifier**: Detects editorial content for synthesis fallback
15. ✅ **Editorial synthesis**: Uses full rewrite for editorial content or >15 spans
16. ✅ **Tabloid examples**: Added Katie Price-style examples to prompt
17. ✅ **Category-specific highlights**: Frontend uses different colors per manipulation type
18. ✅ **editorial_voice mapping fix**: `_parse_span_reason()` now maps `"editorial_voice"` → `SpanReason.EDITORIAL_VOICE` (was falling back to `RHETORICAL_FRAMING`)
19. ✅ **Paragraph deduplication**: `_deduplicate_paragraphs()` in `ingestion.py` removes duplicate paragraphs from extracted article bodies (fixes duplicate highlights from captions/pull quotes)
20. ✅ **Article classification pipeline**: LLM-powered CLASSIFY stage (gpt-4o-mini → gemini fallback → keyword fallback) classifies articles into 20 domains → 10 feed categories
21. ✅ **10-category brief assembly**: Brief groups by `feed_category` (10 categories) instead of `section` (5). Fixed order: World, U.S., Local, Business, Technology, Science, Health, Environment, Sports, Culture
22. ✅ **Classification pipeline monitoring**: `CLASSIFY_FALLBACK_RATE_HIGH` alert fires if keyword fallback exceeds 1%
23. ✅ **Codebase audit remediation** (Jan 2026): 25-item audit across backend + frontend
    - **Security (P0)**: Auth hardened (timing-safe `secrets.compare_digest`, fail-closed), CORS restricted to configured origins, SSL verification re-enabled in ingestion
    - **Hardening (P1)**: Rate limiting (slowapi), response caching (TTLCache), error response sanitization, dependency pinning, `neutralizer.py` refactored into module directory
    - **Quality (P2)**: Centralized config (`app/config.py`), constants (`app/constants.py`), DB indexes migration, lazy-loaded spaCy models, parallel S3 downloads in classification, frontend error boundaries, `__DEV__` debug log guards, model docstrings, `StoryRow` NamedTuple
    - **Documentation (P3)**: Backend API docstrings, backend test coverage (brief_assembly, domain_mapper, enhanced_keyword_classifier), frontend test coverage (api, storageService, secureStorage), frontend JSDoc, consolidated date formatting utils
24. ✅ **Alembic multiple heads fix** (Jan 2026): Linearized migration chain — `add_neutralization_status_index` (`c7f3a1b2d4e5`) now descends from `007_add_classification` instead of `b29c9075587e`, which had two children causing `alembic upgrade head` to fail with "Multiple head revisions" and crash-looping the API container
25. ✅ **S3 download timeout** (Jan 2026): `_get_body_from_storage()` in `stories.py` uses `ThreadPoolExecutor` with 8s timeout to prevent transparency endpoint from hanging on slow S3 reads
26. ✅ **S3 client tuning** (Jan 2026): Reduced boto3 retries 3→2, `read_timeout` 30→15s in `s3_provider.py`
27. ✅ **requirements.txt** (Jan 2026): Generated from `Pipfile.lock` as Docker build safety net
28. ✅ **Frontend transparency resilience** (Jan 2026): `api.ts` reduces transparency retries 3→1, adds 10s body parse timeout via `Promise.race`
29. ✅ **Classify limit fix** (Jan 2026): Pipeline endpoints (`/pipeline/run`, `/pipeline/scheduled-run`) now use configurable `classify_limit` (default 200) instead of hardcoded 25. Prevents sports/culture articles from being misclassified as "world" due to unclassified articles falling back to legacy `SectionClassifier`. Brief assembly skips unclassified articles instead of misrouting them.

### Current State (Jan 27 2026)

**All fixes deployed and verified on Railway staging:**
- Railway auto-deploys from `main` on push (build ~1m30s, deploy ~20s)
- Note: `code_version` in `/v1/status` is not auto-bumped per deploy; check Railway dashboard for deploy status
- All 4 highlight colors verified in UI (emotional=blue, urgency=rose, editorial=lavender, default=gold)
- Full 4-stage pipeline running: INGEST → CLASSIFY → NEUTRALIZE → BRIEF ASSEMBLE
- API healthy after Alembic multiple-heads fix (was crash-looping)

**Classification results (Jan 27 2026):**
- ✅ 200+ articles classified via LLM, 0 keyword fallbacks, 0 failures (100% LLM success rate)
- ✅ Brief rebuilt with 9 populated categories (Environment empty — awaits relevant RSS content)
- ✅ Full pipeline run verified: 42 ingested → 200 classify_limit → 95 neutralized → 250 stories in brief
- ✅ Classification adds ~53s for 25 articles to pipeline run (classify_limit now 200, covers all ingested)

**Verification results:**
- ✅ Local E2E tests pass (27 passed, 2 xfailed)
- ✅ `editorial_voice` spans stored correctly (e.g., "Border Czar", "Make no mistake")
- ✅ Lavender highlight color renders in UI for editorial_voice spans
- ✅ Highlight legend shows all 4 categories, collapses/expands correctly
- ✅ Badge hides when highlight toggle is off
- ✅ Paragraph deduplication deployed (takes effect on next ingestion run)
- ✅ 10-category feed verified in ntrl-app (section headers render correctly)
- ✅ Topic selection filtering verified (deselect → sections disappear, re-enable → sections return)
- ✅ Alembic migration chain linearized, API container no longer crash-loops
- ✅ Transparency endpoint resilient to slow S3 (8s timeout + reduced retries)
- ✅ Frontend ntrl-view won't hang indefinitely (1 retry + 10s body parse timeout)
- ✅ Classify limit raised to 200 in pipeline endpoints (was hardcoded 25)
- ✅ Legacy section fallback removed from brief assembly
- ✅ Sports section populated (Travis Kelce, Vanderbilt QB, etc.)
- ✅ Culture section populated (King Charles, American Idol, etc.)
- ✅ 23/23 brief assembly unit tests passing

### Remaining Issues

1. **Missing highlights in long articles** - LLM misses phrases in 8000+ char articles
   - May need chunking implementation (deferred)

2. ~~**Duplicate content in articles**~~ **FIXED** - `_deduplicate_paragraphs()` added to ingestion
   - Removes exact-duplicate paragraphs (>50 chars) caused by image captions, pull quotes, sidebar summaries
   - Existing articles in S3 are NOT retroactively fixed; only new ingestions benefit
   - To fix existing articles, re-ingest them

3. ~~**Alembic multiple heads crash**~~ **FIXED** - Two migrations (`007_add_classification`, `c7f3a1b2d4e5`) both descended from `b29c9075587e`. Fixed by linearizing: `b29c9075587e → 007_add_classification → c7f3a1b2d4e5`

### Migration Chain (Alembic)

Linear chain (must remain single-head):
```
4b0a5b86cbe8 → 001 → 002 → 003 → 004 → 005 → 006
→ 48b2882dfa37 → 4eb5c6286d76 → 53b582a6786a → b29c9075587e
→ 007_add_classification → c7f3a1b2d4e5
```

**When adding new migrations:** Always set `down_revision` to the current single head. Run `alembic heads` to verify only one head exists before committing.

### Important: Database Spans vs Fresh Detection

**Spans in the database are from OLD pipeline runs.** When you change span detection code:

1. Existing spans in DB won't change automatically
2. Use `/debug/spans` endpoint to see what FRESH detection would return
3. Re-neutralize articles with `force: true` to update spans in DB

```bash
# Compare old spans (in DB) vs new detection (fresh)
# 1. Check what's in DB
curl ".../v1/stories/{id}/transparency" -H "X-API-Key: ..."

# 2. Check what fresh detection returns
curl ".../v1/stories/{id}/debug/spans" -H "X-API-Key: ..."

# 3. If different, re-neutralize to update DB
curl -X POST ".../v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ..." \
  -d '{"story_ids": ["{id}"], "force": true}'
```

**Test commands:**
```bash
# Re-neutralize test article
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: staging-key-123" \
  -d '{"story_ids": ["4365e5df-ffd1-42cd-96a9-5bf4201bdaae"], "force": true}'

# Check debug info
curl -s "https://api-staging-7b4d.up.railway.app/v1/stories/4365e5df-ffd1-42cd-96a9-5bf4201bdaae/debug" \
  -H "X-API-Key: staging-key-123" | python3 -m json.tool
```

## Related Project

The mobile app is at `../ntrl-app/` - see its CLAUDE.md for frontend details.

### UI Highlight Validation Tests

The ntrl-app has E2E tests for highlight validation:
- `e2e/test_highlight_validation.spec.ts` - Verifies WHAT is highlighted, not just IF something is
- `e2e/ntrl-view-visual.spec.ts` - Visual regression tests for highlight styling

Run with:
```bash
cd ../ntrl-app
npx playwright test e2e/test_highlight_validation.spec.ts
```

These tests:
1. Check that articles with manipulative content have highlights
2. Verify common false positives (crisis management, etc.) are NOT highlighted
3. Test highlight toggle behavior
4. Capture screenshots for visual review

**Note:** Tests look for `[data-testid="article-item"]` which doesn't exist - they need text-based navigation instead.

### Span Detection Validation Checklist

When making changes to span detection (prompt, filtering, quote handling), follow this workflow:

**Step 1: Identify Test Articles**
```bash
# Find articles with known manipulative content
curl -s "https://api-staging-7b4d.up.railway.app/v1/stories?limit=30" \
  -H "X-API-Key: staging-key-123" | jq '.stories[] | select(.has_manipulative_content == true) | {id, original_title, source_name}'
```

Good test candidates:
- Dave Roberts (NY Post) - has quotes that should be filtered
- Katie Price (Daily Mail) - tabloid content
- Harry Styles (Daily Mail) - emotional triggers

**Step 2: Check Current Spans (Before)**
```bash
# See what's currently in the database
curl -s ".../v1/stories/{id}/transparency" -H "X-API-Key: ..." | jq '{span_count: .spans | length, spans}'
```

**Step 3: Run Fresh Detection (Debug)**
```bash
# See what NEW detection would return (uses gpt-4o, not production model!)
curl -s ".../v1/stories/{id}/debug/spans" -H "X-API-Key: ..." | jq '{
  model_used,
  llm_phrases_count,
  pipeline_trace,
  final_span_count
}'
```

**Step 4: Re-Neutralize Test Articles**
```bash
curl -X POST ".../v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ..." \
  -d '{"story_ids": ["id1", "id2"], "force": true}'
```

**Step 5: Verify in UI**
```bash
cd ../ntrl-app
# Create Playwright script to capture screenshots
cat > capture.cjs << 'EOF'
const { chromium } = require('@playwright/test');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto('http://localhost:8081');
  await page.waitForTimeout(4000);

  // Click article by text
  await page.getByText('Article Title', { exact: false }).first().click();
  await page.waitForTimeout(2000);

  // Go to ntrl view
  await page.getByText('ntrl view').click();
  await page.waitForTimeout(3000);
  await page.screenshot({ path: '/tmp/ntrl-view.png' });

  // Check highlights
  const count = await page.locator('[data-testid^="highlight-span-"]').count();
  console.log('Highlights found:', count);

  await browser.close();
})();
EOF
node capture.cjs
```

**Expected Validation Results:**

| Check | How to Verify |
|-------|---------------|
| Quote filtering | Text inside `"quotes"` should NOT be highlighted |
| Emotional triggers | Words like "slammed", "outraged" SHOULD be highlighted |
| Span count matches | API transparency count = UI "X phrases flagged" |
| Toggle works | Highlights appear/disappear with toggle |
