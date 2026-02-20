# NTRL Monitoring Runbook

Last updated: January 2026

---

## 1. Overview

This runbook covers day-to-day operational monitoring of the NTRL backend. It describes health check endpoints, alert thresholds, structured logging, debug tools, and step-by-step procedures for common incident scenarios.

All examples use the staging environment. Replace the base URL and API key for production.

| Environment | Base URL | API Key Header |
|-------------|----------|----------------|
| Staging | `https://api-staging-7b4d.up.railway.app` | `X-API-Key: $ADMIN_API_KEY` |
| Production | *(TBD)* | `X-API-Key: <production-admin-key>` |

---

## 2. Health Check Endpoints

### 2.1 Primary Health Check -- /v1/status

This is the single most important endpoint for monitoring. It requires the `X-API-Key` header.

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/status" \
  -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool
```

**Response fields:**

| Field | Example | Description |
|-------|---------|-------------|
| `status` | `"ok"` or `"error"` | Top-level request status |
| `health` | `"healthy"`, `"degraded"`, or `"unhealthy"` | System health determination |
| `code_version` | `"2026.01.26.8"` | Deployed code version |
| `neutralizer_provider` | `"openai"` | Active LLM provider |
| `neutralizer_model` | `"gpt-4o-mini"` | Active LLM model |
| `has_google_api_key` | `true` / `false` | Google API key present |
| `has_openai_api_key` | `true` / `false` | OpenAI API key present |
| `has_anthropic_api_key` | `true` / `false` | Anthropic API key present |
| `has_aws_credentials` | `true` / `false` | AWS credentials present |
| `s3_bucket` | `"ntrl-raw-content"` | Configured S3 bucket |
| `total_articles_ingested` | `4521` | Total ingested article count |
| `total_articles_neutralized` | `3890` | Total neutralized article count |
| `total_sources` | `42` | Number of configured sources |
| `last_ingest` | `{stage, status, finished_at, duration_ms}` | Last ingest run info |
| `last_neutralize` | `{stage, status, finished_at, duration_ms}` | Last neutralize run info |
| `last_brief` | `{stage, status, finished_at, duration_ms}` | Last brief build info |
| `latest_pipeline_run` | *(see section 2.2)* | Health metrics from most recent PipelineRunSummary |

### 2.2 Latest Pipeline Run Object

The `latest_pipeline_run` field inside `/v1/status` contains the most recent `PipelineRunSummary`. This is the primary source of operational metrics.

| Field | Description | Target |
|-------|-------------|--------|
| `trace_id` | Unique identifier for the pipeline run | -- |
| `finished_at` | Timestamp when the run completed | -- |
| `status` | `"completed"`, `"partial"`, or `"failed"` | `"completed"` |
| `body_download_rate` | Percentage of articles with bodies downloaded | >= 70% |
| `neutralization_rate` | Percentage of articles successfully neutralized | >= 90% |
| `brief_story_count` | Number of stories in the generated brief | >= 10 |
| `alerts` | Array of alert objects (empty when healthy) | `[]` |

### 2.3 Quick Health Checks (No Auth Required)

These endpoints do not require authentication and are useful for simple uptime checks:

```bash
# Brief endpoint -- returns current brief content
curl "https://api-staging-7b4d.up.railway.app/v1/brief"

# Sources endpoint -- returns configured sources
curl "https://api-staging-7b4d.up.railway.app/v1/sources"
```

If either returns a non-200 response, the service is down.

---

## 3. Health Determination Logic

The `health` field in `/v1/status` is derived from the latest pipeline run:

| Health State | Condition |
|--------------|-----------|
| **healthy** | Latest pipeline run completed AND alerts array is empty |
| **degraded** | Latest pipeline run completed BUT alerts array is non-empty, OR the run status is `"partial"` |
| **unhealthy** | Latest pipeline run status is `"failed"` |

**Decision tree:**

```
latest_pipeline_run.status == "failed"?
  YES --> unhealthy
  NO  --> latest_pipeline_run.alerts is empty AND status == "completed"?
            YES --> healthy
            NO  --> degraded
```

---

## 4. Alert Thresholds

The pipeline automatically generates alerts when metrics fall outside acceptable ranges. These alerts appear in the `latest_pipeline_run.alerts` array.

| Alert Condition | Threshold | Severity | Likely Cause |
|-----------------|-----------|----------|--------------|
| Body download rate low | < 70% | Warning | Source RSS feeds returning errors, network issues, or paywall blocking |
| Neutralization rate low | < 90% | Warning | LLM API failures, invalid API key, rate limiting |
| Brief story count low | < 10 stories | Warning | Upstream pipeline stages failing, insufficient classified content |
| Classify fallback rate high | > 1% keyword fallback | Warning | LLM classifier unavailable, API rate limiting or outage |

The classify fallback alert uses the code `CLASSIFY_FALLBACK_RATE_HIGH` in structured logs and pipeline records.

---

## 5. Pipeline Monitoring

### 5.1 PipelineRunSummary

Every invocation of `/v1/pipeline/scheduled-run` creates a `PipelineRunSummary` record. This tracks per-stage metrics for the run.

**Ingestion metrics:**

| Field | Description |
|-------|-------------|
| `total` | Number of articles the pipeline attempted to ingest |
| `success` | Number successfully ingested |
| `body_downloaded` | Number where full body text was retrieved |
| `body_failed` | Number where body download failed |
| `skipped_duplicate` | Number skipped because they already exist in the database |

**Classification metrics:**

| Field | Description |
|-------|-------------|
| `total` | Number of articles classified |
| `success` | Number successfully classified |
| `llm` | Number classified by the LLM |
| `keyword_fallback` | Number that fell back to keyword-based classification |
| `failed` | Number where classification failed entirely |

**Neutralization metrics:**

| Field | Description |
|-------|-------------|
| `total` | Number of articles the neutralizer attempted to process |
| `success` | Number successfully neutralized |
| `skipped_no_body` | Number skipped because no body text was available |
| `failed` | Number where neutralization failed |

**Brief metrics:**

| Field | Description |
|-------|-------------|
| `story_count` | Number of stories in the generated brief |
| `section_count` | Number of sections (feed categories) in the brief |

**Overall:**

| Field | Description |
|-------|-------------|
| `status` | `"completed"`, `"partial"`, or `"failed"` |
| `alerts` | Array of alert objects |
| `trigger` | `"scheduled"`, `"manual"`, or `"api"` |

### 5.2 Checking the Latest Pipeline Run

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/status" \
  -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool
```

**What to look for in the response:**

1. `latest_pipeline_run.status` -- should be `"completed"`
2. `latest_pipeline_run.body_download_rate` -- should be >= 70%
3. `latest_pipeline_run.neutralization_rate` -- should be >= 90%
4. `latest_pipeline_run.brief_story_count` -- should be >= 10
5. `latest_pipeline_run.alerts` -- should be an empty array `[]`

### 5.3 Triggering a Manual Pipeline Run

```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -d '{}'
```

The pipeline runs on a cron schedule (`0 */4 * * *`, every 4 hours). Manual runs share the same rate limit (5/min for pipeline triggers).

---

## 6. Debug Endpoints

### 6.1 Story Debug -- /v1/stories/{id}/debug

Returns diagnostic information for a specific story. Useful for investigating why a particular article looks wrong or failed processing.

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug" \
  -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool
```

**Response fields:**

| Field | Description |
|-------|-------------|
| `original_body` | First 500 characters of the original body text from S3 |
| `original_body_length` | Total character count of the original body |
| `detail_full` | First 500 characters of the neutralized text |
| `detail_full_readable` | Boolean -- whether the neutralized text passes grammar checks |
| `issues` | Array of detected problems with the story |
| `span_count` | Number of transparency spans (highlighted changes) |
| `spans_sample` | Sample of transparency span data |

### 6.2 Span Debug -- /v1/stories/{id}/debug/spans

Runs the span detection pipeline from scratch (not from the database) and returns the full pipeline trace. This is the primary tool for debugging transparency highlighting issues.

```bash
curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug/spans" \
  -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool
```

**Response fields:**

| Field | Description |
|-------|-------------|
| `llm_raw_response` | Raw text returned by the LLM |
| `llm_phrases_count` | Number of bias phrases the LLM identified |
| `llm_phrases` | List of bias phrases from the LLM |
| `pipeline_trace` | Object showing spans at each pipeline stage |
| `pipeline_trace.after_position_matching` | Spans after matching phrases to text positions |
| `pipeline_trace.after_quote_filter` | Spans after filtering out quoted material |
| `pipeline_trace.after_false_positive_filter` | Spans after removing false positives |
| `phrases_not_found_in_text` | Phrases the LLM returned that do not appear in the text (hallucinations) |
| `phrases_filtered_by_quotes` | Phrases removed because they were inside quotations |
| `phrases_filtered_as_false_positives` | Phrases removed by the false positive filter |
| `final_spans` | The spans that will be shown to users |

---

## 7. Structured Logging

### 7.1 Log Prefixes

The backend uses structured log prefixes to make filtering easy:

| Prefix | Component | Example |
|--------|-----------|---------|
| `[SPAN_DETECTION]` | Span detection pipeline | LLM calls, phrase counts, pipeline stage transitions |
| `[PIPELINE]` | Pipeline orchestration | Stage start/finish, run summaries |
| `[INGEST]` | Article ingestion | Source polling, body downloads |
| `[CLASSIFY]` | Article classification | LLM classification, keyword fallback |
| `[NEUTRALIZE]` | Article neutralization | LLM rewriting, grammar checks |
| `[BRIEF]` | Brief generation | Story grouping, section building |

**Example span detection log sequence:**

```
[SPAN_DETECTION] Starting LLM call, model=gpt-4o-mini, body_length=4721
[SPAN_DETECTION] LLM responded, response_length=523
[SPAN_DETECTION] LLM returned 17 phrases
[SPAN_DETECTION] Pipeline: position_match=22 -> quote_filter=13 -> fp_filter=13
```

### 7.2 Pipeline Stage Logging

Each pipeline stage also writes to the `PipelineLog` table in the database, providing a persistent record of stage execution separate from ephemeral container logs.

### 7.3 Viewing Logs

**Railway dashboard (recommended for ad-hoc investigation):**

1. Open the Railway dashboard.
2. Navigate to the service.
3. Click Deployments, then select the active deployment.
4. Click Logs.

**Railway CLI:**

```bash
railway logs
```

**Filtering by prefix (CLI):**

```bash
railway logs | grep "\[SPAN_DETECTION\]"
railway logs | grep "\[NEUTRALIZE\]"
```

---

## 8. Key Metrics Reference

| Metric | Source | Target | Action if Breached |
|--------|--------|--------|--------------------|
| Body download rate | PipelineRunSummary | >= 70% | Check source feeds, network, paywalls (see 9.2) |
| Neutralization rate | PipelineRunSummary | >= 90% | Check LLM API keys and provider status (see 9.3) |
| Brief story count | PipelineRunSummary | >= 10 | Check upstream stages (see 9.1) |
| Keyword fallback rate | PipelineRunSummary | < 1% | Check LLM classifier availability (see 9.4) |
| API response time | Railway metrics | < 500ms | Check database performance, Railway resource limits |
| Error rate | Railway metrics | < 1% | Review error logs in Railway dashboard |
| Pipeline run duration | PipelineRunSummary | ~2-5 min | Check for LLM latency spikes, large backlogs |

---

## 9. Troubleshooting Procedures

### 9.1 Scenario: Empty Brief

**Symptoms:** The `/v1/brief` endpoint returns no stories, or the brief has fewer sections than expected.

**Procedure:**

1. **Check system health:**

   ```bash
   curl "https://api-staging-7b4d.up.railway.app/v1/status" \
     -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool
   ```

   Look at the `health` field and `latest_pipeline_run.status`.

2. **Check ingestion:** Look at `last_ingest` in the status response. If `status` is `"failed"` or `finished_at` is stale (more than 4 hours old), ingestion is not running.

   - Verify the cron job is active in the Railway dashboard.
   - Trigger a manual ingest:

     ```bash
     curl -X POST "https://api-staging-7b4d.up.railway.app/v1/ingest/run" \
       -H "X-API-Key: $ADMIN_API_KEY"
     ```

3. **Check classification:** Articles need a `feed_category` to appear in the brief. If articles are ingested but not classified, run classification manually:

   ```bash
   curl -X POST "https://api-staging-7b4d.up.railway.app/v1/classify/run" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: $ADMIN_API_KEY" \
     -d '{"limit": 200}'
   ```

4. **Check neutralization:** Look at `last_neutralize` in the status response. Articles must be neutralized to appear in the brief. Run neutralization manually if needed:

   ```bash
   curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: $ADMIN_API_KEY" \
     -d '{"limit": 50}'
   ```

5. **Rebuild the brief:**

   ```bash
   curl -X POST "https://api-staging-7b4d.up.railway.app/v1/brief/run" \
     -H "X-API-Key: $ADMIN_API_KEY"
   ```

6. **Verify the brief now has content:**

   ```bash
   curl "https://api-staging-7b4d.up.railway.app/v1/brief?hours=24"
   ```

### 9.2 Scenario: Low Body Download Rate (< 70%)

**Symptoms:** `latest_pipeline_run.body_download_rate` is below 70%. The body download rate alert fires.

**Procedure:**

1. **Check the pipeline summary** for `body_failed` count vs `body_downloaded`:

   ```bash
   curl "https://api-staging-7b4d.up.railway.app/v1/status" \
     -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool
   ```

2. **Review ingest logs** for error patterns:

   ```bash
   railway logs | grep "\[INGEST\]"
   ```

   Look for HTTP error codes (403, 429, 503) that indicate:
   - **403 Forbidden:** Paywalled content or bot blocking
   - **429 Too Many Requests:** Rate limiting by the source
   - **503 Service Unavailable:** Source server issues

3. **Check if the issue is isolated to specific sources.** If only certain sources are failing, the problem is likely source-specific (paywall, format change, or downtime).

4. **Check AWS S3 connectivity.** If body storage is failing:

   - Verify `has_aws_credentials` is `true` in `/v1/status`
   - Verify `s3_bucket` is correct
   - Check Railway environment variables for `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`

5. **If widespread:** Check general network connectivity from the Railway container. DNS issues or egress restrictions could block all downloads.

### 9.3 Scenario: Low Neutralization Rate (< 90%)

**Symptoms:** `latest_pipeline_run.neutralization_rate` is below 90%. The neutralization rate alert fires.

**Procedure:**

1. **Check LLM API key validity:**

   ```bash
   curl "https://api-staging-7b4d.up.railway.app/v1/status" \
     -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool
   ```

   Verify that `has_openai_api_key` (or whichever provider is configured via `neutralizer_provider`) is `true`.

2. **Debug a failing article.** Pick a story ID that failed neutralization and inspect it:

   ```bash
   curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug" \
     -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool
   ```

   Check the `issues` array for specific failure reasons.

3. **Look for failure patterns in logs:**

   ```bash
   railway logs | grep "\[NEUTRALIZE\]"
   ```

   Common patterns:
   - `failed_llm` -- The LLM returned an error or unusable output
   - `failed_garbled` -- The neutralized text failed grammar/readability checks

4. **Check LLM provider status.** Visit the status page for the active provider:
   - OpenAI: https://status.openai.com
   - Google/Gemini: https://status.cloud.google.com
   - Anthropic: https://status.anthropic.com

5. **If the provider is down:** Wait for recovery. The next scheduled pipeline run will retry failed articles.

6. **If the API key is expired or invalid:** Update the key in the Railway dashboard environment variables, then redeploy or restart the service.

### 9.4 Scenario: Keyword Fallback Rate High (> 1%)

**Symptoms:** The `CLASSIFY_FALLBACK_RATE_HIGH` alert appears in `latest_pipeline_run.alerts`.

**Procedure:**

1. **Understand the impact:** When the LLM classifier is unavailable, articles fall back to keyword-based classification. This is less accurate but keeps the pipeline running. A high fallback rate means the LLM classifier is consistently failing.

2. **Check API keys for both classification providers:**

   ```bash
   curl "https://api-staging-7b4d.up.railway.app/v1/status" \
     -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool
   ```

   Verify `has_openai_api_key` and `has_google_api_key` are both `true`. Classification may use either provider.

3. **Review classifier logs:**

   ```bash
   railway logs | grep "\[CLASSIFY\]"
   ```

   Look for error messages indicating:
   - Rate limiting (429 responses from the LLM API)
   - Authentication failures
   - Timeout errors

4. **Check LLM provider status pages** (see links in section 9.3 step 4).

5. **If rate limited:** The pipeline runs every 4 hours. If the rate limit resets before the next run, the issue may self-resolve. Consider reducing `classify_limit` temporarily:

   ```bash
   curl -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: $ADMIN_API_KEY" \
     -d '{"classify_limit": 50}'
   ```

### 9.5 Scenario: Missing Highlights in Long Articles

**Symptoms:** Users report that long articles appear to have no bias highlights (transparency spans), even though the article clearly contains biased language.

**Procedure:**

1. **This is a known limitation.** The LLM struggles to identify bias phrases in articles exceeding approximately 8,000 characters. The phrases it returns may not match exact positions in the text.

2. **Confirm the issue with the debug spans endpoint:**

   ```bash
   curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug/spans" \
     -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool
   ```

3. **Review the pipeline trace:**
   - Check `llm_phrases_count` -- does the LLM find phrases at all?
   - Check `phrases_not_found_in_text` -- these are LLM hallucinations (phrases the LLM claims exist but do not match the actual text)
   - Check `pipeline_trace.after_position_matching` -- how many phrases survived position matching?

4. **If `phrases_not_found_in_text` is high:** The LLM is hallucinating phrase locations. This is expected for very long articles and may require a future chunking implementation (currently deferred).

5. **No immediate fix is available.** Document the story ID for future analysis when chunking is implemented.

### 9.6 Scenario: Service Completely Down

**Symptoms:** All endpoints return errors or time out.

**Procedure:**

1. **Check Railway dashboard:** Look for deployment failures, crash loops, or resource exhaustion.

2. **Check quick health endpoints (no auth required):**

   ```bash
   curl -v "https://api-staging-7b4d.up.railway.app/v1/brief"
   curl -v "https://api-staging-7b4d.up.railway.app/v1/sources"
   ```

   If these also fail, the service container is not responding.

3. **Check Railway logs** for crash information:

   ```bash
   railway logs
   ```

4. **Common causes:**
   - **Database connection failure:** Check that Railway PostgreSQL is running. The `DATABASE_URL` is auto-set by Railway but can break if the database service is restarted.
   - **Out of memory:** Check Railway resource metrics for memory spikes.
   - **Bad deploy:** Roll back to the previous deployment via the Railway dashboard (Deployments > previous green deployment > Rollback).

5. **If the database is unreachable:** Restart the Railway PostgreSQL service from the dashboard.

6. **If the service is crash-looping:** Check the most recent logs for the error, then roll back:

   ```bash
   railway rollback
   ```

---

## 10. Rate Limits

Monitor for HTTP 429 responses, which indicate rate limits are being hit.

| Scope | Limit | Notes |
|-------|-------|-------|
| Global | 100/min | All endpoints combined |
| Admin endpoints | 10/min | Endpoints requiring `X-API-Key` |
| Pipeline triggers | 5/min | `/v1/pipeline/scheduled-run` and individual stage triggers |

If automated monitoring or external tools are hitting rate limits, reduce polling frequency or stagger requests.

---

## 11. Monitoring Checklist

### Daily (or per-pipeline-run)

- [ ] `/v1/status` returns `health: "healthy"`
- [ ] `latest_pipeline_run.alerts` is empty
- [ ] `body_download_rate` >= 70%
- [ ] `neutralization_rate` >= 90%
- [ ] `brief_story_count` >= 10
- [ ] `last_ingest.finished_at` is within the last 4 hours
- [ ] `last_neutralize.finished_at` is within the last 4 hours
- [ ] `last_brief.finished_at` is within the last 4 hours

### Weekly

- [ ] Review Railway resource metrics (CPU, memory, network)
- [ ] Check for increasing error rates in Railway dashboard
- [ ] Verify all API keys are still valid (`has_*_api_key` fields in `/v1/status`)
- [ ] Review pipeline run durations for unexpected increases
- [ ] Check `total_articles_ingested` and `total_articles_neutralized` are growing

### After Any Deploy

- [ ] `/v1/status` returns `status: "ok"` and `health: "healthy"`
- [ ] `code_version` matches expected version (note: not auto-bumped per deploy; check Railway dashboard for deploy confirmation)
- [ ] Trigger a test pipeline run and verify it completes without alerts
- [ ] Verify `/v1/brief` returns content

---

## 12. Quick Reference Commands

```bash
# Full system status
curl "https://api-staging-7b4d.up.railway.app/v1/status" \
  -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool

# Quick uptime check (no auth)
curl -s -o /dev/null -w "%{http_code}" \
  "https://api-staging-7b4d.up.railway.app/v1/brief"

# Trigger full pipeline run
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -d '{}'

# Debug a specific story
curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug" \
  -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool

# Debug span detection for a story
curl "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug/spans" \
  -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool

# Rebuild brief manually
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/brief/run" \
  -H "X-API-Key: $ADMIN_API_KEY"

# View Railway logs
railway logs

# Filter logs by component
railway logs | grep "\[SPAN_DETECTION\]"
railway logs | grep "\[NEUTRALIZE\]"
railway logs | grep "\[CLASSIFY\]"
railway logs | grep "\[INGEST\]"
```
