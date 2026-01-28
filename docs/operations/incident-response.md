# NTRL Incident Response Procedures

> Last updated: January 2026
> Status: Active internal runbook. Communication sections marked [TBD] require decisions.

---

## 1. Severity Levels

| Level | Name | Definition | Examples | Response Time |
|-------|------|-----------|----------|---------------|
| **P0** | Critical | Service completely down — API unreachable, app non-functional | Railway deployment crashed, database unreachable, DNS failure | Immediate (within 30 minutes) |
| **P1** | Major | Pipeline not running — no new content being produced | Cron job stopped, all LLM providers failing, S3 unreachable | Within 2 hours |
| **P2** | Degraded | Service running but quality is significantly degraded | High classification fallback rate, low neutralization rate, multiple empty categories | Within 8 hours |
| **P3** | Minor | Individual article or feature issues | Single article not neutralized, one category low on content, UI glitch | Within 24 hours (next business day) |

---

## 2. P0 — API Down

The API is unreachable. Users see errors, blank screens, or cannot load any content.

### Diagnostic Steps

```
Step 1: Check Railway Dashboard
├── Is the deployment running?
│   ├── YES → Go to Step 2
│   └── NO → Check deployment logs for crash reason
│       ├── "Multiple heads detected" (Alembic) → See Recovery: Alembic Crash
│       ├── Out of memory → Scale up Railway instance
│       ├── Build failure → Check recent commit for syntax errors
│       └── Unknown → Rollback to previous deployment
│
Step 2: Check Railway Logs
├── Look for Python tracebacks or startup errors
├── Look for "Connection refused" (database)
├── Look for repeated 500 errors
│
Step 3: Check Database Connectivity
├── Can the API reach PostgreSQL?
│   ├── YES → Go to Step 4
│   └── NO → Check Railway PostgreSQL plugin status
│       ├── Database is down → Restart via Railway dashboard
│       └── Connection string changed → Update DATABASE_URL env var
│
Step 4: Check Rate Limits
├── Are responses returning 429 status codes?
│   ├── YES → OpenAI/Gemini rate limit hit
│   │   ├── Wait for rate limit to reset
│   │   └── Check if pipeline run is consuming all quota
│   └── NO → Investigate application-level error
│
Step 5: Rollback
├── If a recent deployment caused the issue:
│   └── Use Railway dashboard to redeploy the previous successful build
```

### Quick Actions

| Action | How |
|--------|-----|
| Check if API responds | `curl https://[API_URL]/v1/status` |
| View Railway logs | Railway Dashboard > Project > Service > Logs |
| Rollback deployment | Railway Dashboard > Project > Service > Deployments > Redeploy previous |
| Restart service | Railway Dashboard > Project > Service > Settings > Restart |

---

## 3. P1 — Pipeline Not Running

The API is up, but no new content is being ingested or processed. Users see stale articles.

### Diagnostic Steps

```
Step 1: Check Pipeline Schedule
├── Is the Railway cron job configured?
│   ├── Cron expression should be: 0 */4 * * * (every 4 hours)
│   ├── If missing → Reconfigure in Railway dashboard
│   └── If present → Go to Step 2
│
Step 2: Check Last Pipeline Run
├── GET /v1/status
│   ├── Check last_ingest_run timestamp
│   ├── Check last_classify_run timestamp
│   ├── Check last_neutralize_run timestamp
│   ├── Check last_brief_run timestamp
│   └── If all are >8 hours old → Pipeline is stuck
│
Step 3: Manual Pipeline Trigger
├── POST /v1/pipeline/scheduled-run
│   ├── Monitor Railway logs for progress
│   ├── If it runs successfully → Cron may need reconfiguration
│   └── If it fails → Check error in logs, go to Step 4
│
Step 4: Check LLM Provider Status
├── OpenAI API status: https://status.openai.com
│   ├── If OpenAI is down → Verify Gemini fallback is working
│   └── Gemini fallback: should activate automatically
├── Check API key validity
│   ├── OPENAI_API_KEY still valid? (not expired, not revoked)
│   └── GEMINI_API_KEY still valid?
│
Step 5: Check S3 Connectivity
├── Are body downloads failing?
│   ├── Check AWS S3 status
│   ├── Check AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
│   └── Check S3_BUCKET_NAME is correct
│
Step 6: Check RSS Sources
├── Are source feeds returning valid XML?
│   ├── Try fetching a source feed URL directly in browser
│   └── If feed is broken → Deactivate source, check other sources
```

### Quick Actions

| Action | How |
|--------|-----|
| Check pipeline status | `GET /v1/status` |
| Trigger pipeline manually | `POST /v1/pipeline/scheduled-run` |
| Check OpenAI status | https://status.openai.com |
| Verify API keys | Check Railway environment variables |

---

## 4. P2 — Degraded Quality

Service is running, but output quality is below acceptable thresholds.

### Alert Indicators

The `/v1/status` endpoint reports several quality indicators. Watch for:

| Indicator | Normal | Concerning | Critical |
|-----------|--------|-----------|----------|
| **neutralization_rate** | >95% | <90% | <80% |
| **body_download_rate** | >85% | <70% | <50% |
| **classify_fallback_rate** | <5% | >10% | >25% |
| **CLASSIFY_FALLBACK_RATE_HIGH** alert | Not present | Present | Present + rising |
| **Empty categories** | 0 | 1-2 | 3+ |

### Diagnostic Steps

```
Step 1: Check /v1/status
├── Look for active alerts
│   ├── CLASSIFY_FALLBACK_RATE_HIGH → OpenAI classification failing, falling back to keyword
│   ├── Low neutralization_rate → Neutralizer failing on many articles
│   └── Low body_download_rate → Source websites blocking scraping or timing out
│
Step 2: If CLASSIFY_FALLBACK_RATE_HIGH
├── OpenAI may be degraded (not down, but slow/erroring)
├── Check OpenAI status page
├── Check Railway logs for OpenAI API errors (timeout, 500, rate limit)
├── Gemini fallback should be catching some failures
├── If persistent: check prompt changes that may have introduced errors
│
Step 3: If Low Neutralization Rate
├── Check recent pipeline run logs for neutralization errors
├── Debug specific failing articles: GET /v1/stories/{id}/debug
├── Common causes:
│   ├── Prompt formatting error (recent change broke JSON output)
│   ├── Articles too long (>8000 chars, known limitation)
│   └── LLM returning unexpected format
│
Step 4: If Low Body Download Rate
├── Source websites may be rate-limiting or blocking
├── Check specific sources: which ones are failing?
├── S3 upload may be failing (check AWS credentials)
├── Timeout tuning: already adjusted (reduced retries + timeout in Jan 2026)
│
Step 5: If Categories Empty
├── Check which categories are empty
├── Check source feeds for those categories
├── Run targeted ingest for affected categories
├── May need to add new sources for underserved categories
```

### Quick Actions

| Action | How |
|--------|-----|
| Check quality metrics | `GET /v1/status` |
| Debug specific article | `GET /v1/stories/{id}/debug` |
| Debug span detection | `GET /v1/stories/{id}/debug/spans` |
| Force re-neutralize all | `POST /v1/neutralize/run` with `{ "force": true }` |
| Force re-neutralize specific | `POST /v1/neutralize/run` with `{ "story_ids": [1,2,3], "force": true }` |
| Rebuild briefs | `POST /v1/brief/run` |

---

## 5. P3 — Individual Article Issues

A specific article has problems — missing highlights, wrong classification, empty content, etc.

### Diagnostic Steps

```
Step 1: Get Article Debug Info
├── GET /v1/stories/{id}/debug
│   ├── Check: Was the body downloaded? (body_downloaded: true/false)
│   ├── Check: Was it classified? (classification_status)
│   ├── Check: Was it neutralized? (neutralization_status)
│   ├── Check: Article length (may be >8000 chars)
│   └── Check: Source feed and original URL
│
Step 2: Check Span Detection
├── GET /v1/stories/{id}/debug/spans
│   ├── Shows every span the classifier detected
│   ├── Shows which manipulation category was assigned
│   ├── Shows confidence scores
│   └── Look for: missed spans, wrong categories, false positives
│
Step 3: Re-process if Needed
├── Re-neutralize single article:
│   POST /v1/neutralize/run
│   Body: { "story_ids": [<id>], "force": true }
├── Then rebuild brief:
│   POST /v1/brief/run
│
Step 4: Known Limitations
├── Long articles (>8000 chars) → May have missing highlights at end
├── Non-English content in English feeds → May not neutralize correctly
├── Paywalled article bodies → Body download may fail
├── Heavily formatted content (tables, lists) → May lose formatting
```

---

## 6. Recovery Procedures

### Alembic Crash (Multiple Heads)

**Symptom:** Railway deployment crashes on startup with "Multiple heads detected" or similar Alembic error.

**Cause:** Two or more migration branches exist without a merge point.

**Fix:**
```bash
# 1. Check current heads
pipenv run alembic heads
# Will show 2+ revision IDs

# 2. Merge heads
pipenv run alembic merge heads -m "merge migration branches"

# 3. Verify single head
pipenv run alembic heads
# Must show exactly 1 revision ID

# 4. Apply
pipenv run alembic upgrade head

# 5. Commit and deploy
git add alembic/versions/
git commit -m "Merge Alembic heads to restore single migration chain"
git push
```

**Prevention:** Always run `pipenv run alembic heads` before committing any migration. Ensure only one head exists.

**History:** This caused a production crash in January 2026 and was resolved. The fix is documented in the codebase audit.

---

### S3 Timeout / Body Download Failures

**Symptom:** `body_download_rate` drops below 70%. Articles show no body content.

**Cause:** Source websites slow to respond, S3 upload timing out, or AWS credentials expired.

**Fix:**
1. Check AWS credentials in Railway environment variables.
2. Check S3 bucket accessibility.
3. Retry settings have already been tuned (reduced retries + timeout, January 2026) to prevent cascading failures.
4. If a specific source is consistently failing, temporarily deactivate it and investigate.

---

### LLM Provider Failure

**Symptom:** Classification or neutralization failures spiking. `CLASSIFY_FALLBACK_RATE_HIGH` alert.

**Cause:** OpenAI API degraded or down. Rate limits exceeded.

**Automatic mitigation:** The pipeline has a fallback chain:
```
OpenAI (gpt-4o-mini) → Google Gemini → Keyword-based fallback
```

**Manual fix:**
1. Check https://status.openai.com for outages.
2. If OpenAI is down, Gemini fallback should be handling requests.
3. If both are down, keyword fallback provides basic classification (lower quality).
4. Once providers recover, re-neutralize articles that fell through to keyword fallback:
   ```
   POST /v1/neutralize/run
   Body: { "force": true }
   ```

---

### Brief Empty / Missing Categories

**Symptom:** One or more of the 10 feed categories shows no content in the brief.

**Cause:** No articles classified into that category, or brief assembly did not run after neutralization.

**Fix:**
1. Check if articles exist for the category: review recent pipeline run.
2. If articles exist but brief is empty, rebuild:
   ```
   POST /v1/brief/run
   ```
3. If no articles exist for the category, check source feeds that map to that category.
4. Full recovery sequence if pipeline is stuck:
   ```
   1. POST /v1/pipeline/scheduled-run   (runs full INGEST → CLASSIFY → NEUTRALIZE → BRIEF)
   ```
   Or run stages individually:
   ```
   1. POST /v1/ingest/run
   2. POST /v1/classify/run
   3. POST /v1/neutralize/run
   4. POST /v1/brief/run
   ```

---

## 7. Communication

### Notification Channels

[TBD — set up before public launch]

| Channel | Purpose | Status |
|---------|---------|--------|
| **Email alerts** | P0/P1 incidents | [TBD — service: PagerDuty, OpsGenie, or simple email] |
| **Status page** | Public-facing service status | [TBD — service: Statuspage, Instatus, or custom] |
| **Slack/Discord** | Internal team communication during incidents | [TBD] |
| **App banner** | In-app notification to users during extended outages | [TBD — not yet implemented] |

### Communication Templates

#### P0/P1 — Internal Alert
```
NTRL INCIDENT — [P0/P1]
Time: [timestamp]
Issue: [brief description]
Impact: [what users experience]
Status: [investigating / identified / fixing / resolved]
Owner: [name]
```

#### P0/P1 — User-Facing (if extended outage)
```
We are experiencing a service disruption that is affecting [content loading / article availability].
Our team is actively working on a fix. We expect to restore normal service by [ETA or "as soon as possible"].
Thank you for your patience.
```

#### P2 — Internal Note
```
NTRL QUALITY ALERT — P2
Time: [timestamp]
Indicator: [which metric is degraded]
Value: [current value vs. normal]
Action: [what is being done]
```

---

## 8. Post-Incident Review Template

After every P0 or P1 incident (and optionally P2), complete a post-incident review within 48 hours.

```markdown
# Post-Incident Review

## Incident Summary
- **Date/Time:** [start and end]
- **Duration:** [total downtime or degradation]
- **Severity:** [P0/P1/P2]
- **Impact:** [what users experienced, estimated affected users]

## Timeline
- [HH:MM] Issue first detected (how: monitoring, user report, manual check)
- [HH:MM] Investigation started
- [HH:MM] Root cause identified
- [HH:MM] Fix deployed
- [HH:MM] Service restored
- [HH:MM] Verified stable

## Root Cause
[Detailed technical explanation of what went wrong and why]

## What Went Well
- [Things that worked during the response]

## What Could Be Improved
- [Things that slowed down detection or resolution]

## Action Items
- [ ] [Specific preventive action] — Owner: [name] — Due: [date]
- [ ] [Specific preventive action] — Owner: [name] — Due: [date]
- [ ] [Monitoring improvement] — Owner: [name] — Due: [date]

## Lessons Learned
[Key takeaway for future reference]
```

---

## 9. Monitoring Checklist

Daily checks to perform (manual until automated monitoring is set up):

| Check | How | Healthy |
|-------|-----|---------|
| API responding | `curl /v1/status` | 200 response |
| Pipeline ran recently | Check `last_*_run` timestamps in /v1/status | All within last 8 hours |
| Neutralization rate | Check `neutralization_rate` in /v1/status | >90% |
| Body download rate | Check `body_download_rate` in /v1/status | >70% |
| No active alerts | Check `alerts` array in /v1/status | Empty array |
| All 10 categories populated | Check brief output | All categories have articles |
| Railway service healthy | Railway dashboard | Green status |

### Automated Monitoring (Planned)

[TBD — implement before public launch]

- [ ] Uptime monitor (UptimeRobot, Pingdom, or similar) polling /v1/status every 5 minutes
- [ ] Alert on 5xx error rate exceeding threshold
- [ ] Alert on pipeline not running for >8 hours
- [ ] Alert on neutralization_rate dropping below 90%
- [ ] Alert on any P0 condition (API unreachable)
- [ ] Daily summary email with key metrics

---

## 10. Runbook Quick Reference

| Situation | First Action |
|-----------|-------------|
| App shows blank / errors | Check `GET /v1/status` — is API up? |
| Articles are stale (old dates) | Check pipeline last run times in /v1/status |
| "Multiple heads" crash on deploy | Run `alembic merge heads`, verify single head, redeploy |
| OpenAI rate limited | Verify Gemini fallback is active, wait for rate limit reset |
| Single article broken | `GET /v1/stories/{id}/debug` then re-neutralize with `story_ids` |
| Category empty | Check source feeds, run `POST /v1/brief/run` |
| Everything broken | Rollback to last known good deploy via Railway dashboard |
