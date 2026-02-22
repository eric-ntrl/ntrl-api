# QC Gate — Full Reference

Runs between NEUTRALIZE and BRIEF ASSEMBLE. Articles must pass **all 21 checks** to appear in the brief. Failed articles are excluded with structured reason codes.

**Implementation**: `app/services/quality_gate.py`

## Checks by Category

| Category | Checks | What They Catch |
|----------|--------|-----------------|
| **Required Fields** (7) | `required_feed_title`, `required_feed_summary`, `required_source`, `required_published_at`, `required_original_url`, `required_feed_category`, `source_name_not_generic` | Missing metadata, generic API source names |
| **Content Quality** (9) | `original_body_complete`, `original_body_sufficient`, `min_body_length`, `feed_title_bounds`, `feed_summary_bounds`, `no_garbled_output`, `no_llm_refusal`, `content_coherence`, `content_is_news` | Truncated bodies, paywall snippets, LLM refusals/apologies, placeholder text, spam/SEO junk, ALL-CAPS titles, content spinning, weather forecasts, gambling promos |
| **Pipeline Integrity** (3) | `neutralization_success`, `not_duplicate`, `url_reachable` | Failed neutralization, duplicate articles, dead URLs (404/410/403) |
| **View Completeness** (2) | `views_renderable`, `brief_full_different` | Blank detail views, missing disclosure text, identical brief/full tabs |

## Source Filtering

- **`Source.is_blocked`**: Prevents articles from any source from appearing in the brief. Set via `POST /v1/admin/sources/{slug}/block`.
- **`BLOCKED_DOMAINS`**: In `app/constants.py` (`SourceFiltering` class). Checked at ingestion time to skip articles from blocked domains.
- **Source diversity cap**: Max 3 articles per source per category (`MAX_PER_SOURCE_PER_CATEGORY`). Enforced in brief assembly after sorting.
- **Artifact cleanup**: `clean_body_artifacts()` in `app/utils/content_sanitizer.py`. Strips web scraping artifacts at ingestion time.

## Key Design Decisions

- `min_body_length` uses **AND logic**: both `detail_brief` AND `detail_full` must meet minimums
- `no_llm_refusal` patterns are **anchored to start** of text to avoid false positives from articles quoting AI
- `original_body_sufficient` uses `raw_content_size` column as a proxy (no S3 download needed)
- `original_body_complete` checks the `body_is_truncated` flag set during ingestion

## Span Detection

14 manipulation categories and 8 SpanReason values (including `selective_quoting` for cherry-picked/scare quotes).

## Source Health Monitoring

`GET /v1/admin/sources/health` — per-source-type ingestion quality metrics.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `hours` | 24 | Time window to analyze (1-168) |
| `source_type` | all | Filter: `rss`, `perigon`, or `newsdata` |

Returns truncation rates, body sizes, QC pass rates, and auto-generated alerts per source type.

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/admin/sources/health?hours=12&source_type=perigon" \
  -H "X-API-Key: $ADMIN_API_KEY"
```

Alerts trigger when: truncation >20%, QC pass rate <80%, avg body size <1KB, or URL reachability <90%.
