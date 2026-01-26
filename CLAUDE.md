# CLAUDE.md - Project Context for Claude Code

## Project Overview

NTRL API is a neutral news backend service that removes manipulative language from news articles and creates calm, deterministic news briefs.

## Core Architecture Principle

**The original article body is the single source of truth.**

```
INGESTION:     RSS → Database (metadata) + S3 (body.txt)
NEUTRALIZATION: body.txt → ALL outputs (title, summary, brief, full, spans)
DISPLAY:        Neutralized content by default, originals only in "ntrl view"
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
- See `_synthesize_detail_full_fallback()` in `neutralizer.py`

## Tech Stack

- **Framework**: FastAPI (Python 3.11) with Uvicorn
- **Database**: PostgreSQL with SQLAlchemy ORM
- **Migrations**: Alembic
- **Storage**: S3 or local filesystem for raw articles
- **AI**: Pluggable neutralizers (mock, OpenAI, Anthropic, Gemini)
- **NLP**: spaCy (en_core_web_sm) for structural detection
- **Dependencies**: Pipenv

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
- **Neutralization**: Max 25 articles per run
- **Articles in UI**: Only show articles from last 24 hours

### Cleanup
- Articles older than 24 hours are automatically hidden (`is_active=False`)
- The `scheduled-run` endpoint handles this automatically
- Hidden articles remain in DB but don't appear in briefs

### Testing Workflow
1. Run ingestion (limit 25)
2. Run neutralization (limit 25)
3. Rebuild brief
4. Test in UI
5. Old articles auto-hidden on next scheduled run

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
   - **Body**: `{}` (uses defaults: limit 25, cleanup enabled)

The `scheduled-run` endpoint automatically:
- Ingests up to 25 new articles
- Neutralizes up to 25 pending articles
- Rebuilds the brief
- Hides articles older than 24 hours

### Common Operations

```bash
# Trigger RSS ingestion
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/ingest/run" \
  -H "X-API-Key: staging-key-123"

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
├── main.py              # FastAPI entry point
├── database.py          # DB configuration
├── models.py            # SQLAlchemy ORM models
├── taxonomy.py          # 115 manipulation types (v2)
├── routers/
│   ├── admin.py         # V1 admin endpoints
│   ├── brief.py         # V1 brief endpoints
│   ├── stories.py       # V1 story endpoints + debug endpoint
│   ├── sources.py       # V1 sources endpoints
│   └── pipeline.py      # V2 pipeline endpoints
├── schemas/             # Pydantic request/response schemas
├── services/
│   ├── ingestion.py     # RSS ingestion
│   ├── neutralizer.py   # V1 neutralizer with synthesis fallback
│   ├── brief_assembly.py
│   └── ...
├── storage/             # Object storage providers (S3, local)
└── jobs/                # Background jobs
```

## Text/UI Length Constraints

When UI text appears too long or gets truncated, the constraint is usually in the **backend LLM prompt**, not frontend CSS.

### Where to Look
- `app/services/neutralizer.py` - Contains all LLM prompts
- Search for `feed_summary`, `feed_title`, `detail_title`, `detail_brief`

### Workflow for Length Changes
1. Find constraint in `neutralizer.py` prompt
2. Reduce limit (add 15-20% buffer for LLM inaccuracy)
3. Deploy to Railway (push to main)
4. Re-neutralize: `POST /v1/neutralize/run` with `force: true`
5. Rebuild brief: `POST /v1/brief/run`
6. Verify in app

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

The frontend logs diagnostic info to console:
- `[ArticleDetail] Transparency data received:` - spans and originalBody info
- `[ArticleDetail] Detail content:` - brief/full lengths and previews
- `[ArticleDetail] Navigating to NtrlView:` - what's being passed
- `[NtrlView] Received data:` - what NtrlView received

Check these in Expo dev tools or browser console.

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
- `tests/test_highlight_accuracy.py` - Main accuracy tests
- `tests/fixtures/gold_standard/` - Gold standard span annotations (10 articles)
- `tests/fixtures/test_corpus/` - Test article corpus
- `scripts/verify_gold_positions.py` - Verify/fix gold standard positions
- `scripts/review_accuracy.py` - Human review CLI
- `scripts/test_span_detection.py` - Test span detection against staging API

### Running Tests
```bash
# Pattern-based tests (fast, no API key)
pipenv run pytest tests/test_highlight_accuracy.py -m "not llm" -v

# LLM-based tests (requires OPENAI_API_KEY in .env)
pipenv run pytest tests/test_highlight_accuracy.py -m llm -v -s

# Verify gold standard positions
python scripts/verify_gold_positions.py --all

# Human review with LLM
python scripts/review_accuracy.py --article 003 --provider openai
```

### Current Metrics (gpt-4o-mini, Jan 2026)
| Metric | Pattern-Based | LLM-Based | Target | Status |
|--------|---------------|-----------|--------|--------|
| Precision | 5.87% | **72.09%** | 75% | Close |
| Recall | 69.23% | **79.49%** | 75% | **Exceeded** |
| F1 Score | 10.82% | **75.61%** | 75% | **Exceeded** |

**Recent improvements:**
- Expanded gold standard based on LLM review (10 new spans added)
- Improved span matching to handle phrase containment
- Removed incorrectly flagged spans inside quotes

### LLM Span Detection Architecture

**How it works:**
1. LLM analyzes article and returns `{"phrases": [...]}` with manipulative phrases
2. `find_phrase_positions()` maps phrase text to character positions in original body
3. `filter_spans_in_quotes()` removes phrases inside quoted speech
4. `filter_false_positives()` removes known false positive phrases
5. Result: spans with accurate positions for highlighting in UI

**Key files:**
- `neutralizer.py`: `DEFAULT_SPAN_DETECTION_PROMPT` - Conservative prompt with "NEVER FLAG" guidance
- `neutralizer.py`: `detect_spans_via_llm_openai/gemini/anthropic()` - Provider-specific API calls
- `neutralizer.py`: `filter_false_positives()` - Removes known false positives like "bowel cancer"
- `neutralizer.py`: `detect_spans_debug_openai()` - Debug version returning pipeline trace

**Manipulation Taxonomy (12 categories in prompt):**

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
| 9 | **SPORTS/EVENT HYPE** | brilliant, blockbuster, massive, beautiful (events) |
| 10 | **LOADED PERSONAL DESCRIPTORS** | handsome, unfriendly face, menacing |
| 11 | **HYPERBOLIC ADJECTIVES** | punishing, soaked in blood, "of the year" |
| 12 | **LOADED IDIOMS** | came under fire, in the crosshairs, took aim at |

Categories 9-12 added Jan 2026 to catch sports/editorial manipulation.

**JSON format (required by OpenAI json_object mode):**
```json
{"phrases": [
  {"phrase": "SHOCKING", "reason": "emotional_trigger", "action": "remove", "replacement": null}
]}
```

**Fallback behavior:**
- LLM returns `[]` (empty array) = article is clean, trust it, show 0 spans
- LLM API call fails = returns `None`, falls back to pattern-based (but this is a failure mode)

**IMPORTANT: Pattern-based fallback is a failure mode, not a feature.** It generates ~70+ false positives per article (e.g., "European Commission", "Monday said"). If LLM detection fails, it's better to show nothing than show garbage. Consider treating fallback as an error condition.

### Known Issues & Next Steps
- Pattern-based fallback should probably just report an error instead of showing wrong data
- gpt-4o is conservative - may return empty for articles with subtle manipulation
- Article 010 has lower accuracy (38% F1) due to LLM flagging quoted speech
- Gold standard corpus version is now 1.1 (human reviewed)

## Related Project

The mobile app is at `../ntrl-app/` - see its CLAUDE.md for frontend details.
