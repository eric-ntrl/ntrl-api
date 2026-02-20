# Operations Quick Reference

> Quick reference for staging/production operations. Full details in `../operations/monitoring-runbook.md`.

## Staging Environment

| Property | Value |
|----------|-------|
| URL | `https://api-staging-7b4d.up.railway.app` |
| Admin Key | `$ADMIN_API_KEY` (header: `X-API-Key`) |
| Deploy Trigger | Push to `main` branch |
| Deploy Time | ~2 minutes |

## Development Limits

| Operation | Limit |
|-----------|-------|
| Ingest | 25 articles max |
| Classify | 200 articles max |
| Neutralize | 25 articles max |
| Article Visibility | Hidden after 24 hours |

## Common Commands

### Check Status
```bash
curl "https://api-staging-7b4d.up.railway.app/v1/status" \
  -H "X-API-Key: $ADMIN_API_KEY" | python3 -m json.tool
```

### Quick Uptime Check (no auth)
```bash
curl -s -o /dev/null -w "%{http_code}" \
  "https://api-staging-7b4d.up.railway.app/v1/brief"
```

### Trigger Pipeline
```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -d '{}'
```

### Rebuild Brief
```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/brief/run" \
  -H "X-API-Key: $ADMIN_API_KEY"
```

### Re-neutralize Specific Articles
```bash
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -d '{"story_ids": ["uuid1", "uuid2"], "force": true}'
```

## Railway Operations

### View Logs
```bash
railway logs

# Filter by component
railway logs | grep "\[SPAN_DETECTION\]"
railway logs | grep "\[NEUTRALIZE\]"
railway logs | grep "\[CLASSIFY\]"
railway logs | grep "\[INGEST\]"
```

### Pipeline Schedule
- Cron: `0 */4 * * *` (every 4 hours)
- Manual trigger available via API

## Health Monitoring

### Key Metrics

| Metric | Target |
|--------|--------|
| Body download rate | >= 70% |
| Neutralization rate | >= 90% |
| Brief story count | >= 10 |
| Keyword fallback rate | < 1% |

### Health States

| State | Condition |
|-------|-----------|
| `healthy` | Pipeline completed, no alerts |
| `degraded` | Pipeline completed but has alerts |
| `unhealthy` | Pipeline failed |

## Alert Thresholds

| Alert | Threshold | Likely Cause |
|-------|-----------|--------------|
| Body download rate low | < 70% | Source RSS errors, paywalls |
| Neutralization rate low | < 90% | LLM API failures |
| Brief story count low | < 10 | Upstream pipeline failures |
| Classify fallback high | > 1% keyword | LLM classifier unavailable |

## Rate Limits

| Scope | Limit |
|-------|-------|
| Global | 100/min |
| Admin endpoints | 10/min |
| Pipeline triggers | 5/min |

## Post-Deploy Checklist

- [ ] `/v1/status` returns `health: "healthy"`
- [ ] `code_version` matches expected
- [ ] Brief has content
- [ ] No alerts in `latest_pipeline_run.alerts`

## See Also

- `../operations/monitoring-runbook.md` — Full monitoring procedures
- `../operations/deployment-runbook.md` — Deploy procedures
- `../operations/incident-response.md` — Incident handling
