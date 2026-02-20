# /pipeline - Run Full Pipeline

## Purpose
Run the complete scheduled pipeline (ingest → classify → neutralize → brief).

## Arguments
- `$ARGUMENTS` - Custom limits or "evaluate" flag

Examples:
- `/pipeline` - Run with defaults (ingest: 25, classify: 200, neutralize: 25)
- `/pipeline evaluate` - Run pipeline + evaluation after
- `/pipeline ingest:50 classify:100 neutralize:30` - Custom limits
- `/pipeline evaluate auto-optimize` - Run with evaluation and prompt optimization

## Default Limits
- Ingest: 25 articles
- Classify: 200 articles
- Neutralize: 25 articles
- Cleanup: enabled (hides articles >24h old)

## Instructions

### Parse Arguments
Extract custom limits from format `stage:limit` and flags like `evaluate`, `auto-optimize`

### Run Pipeline
```bash
curl -s -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -d '{
    "max_items_per_source": INGEST_LIMIT,
    "classify_limit": CLASSIFY_LIMIT,
    "neutralize_limit": NEUTRALIZE_LIMIT,
    "cleanup_enabled": true,
    "enable_evaluation": ENABLE_EVAL,
    "eval_sample_size": 10,
    "enable_auto_optimize": AUTO_OPTIMIZE
  }'
```

Note: This endpoint can take 60-120 seconds. Use a longer timeout.

### Display Results

**Pipeline Run Complete**

| Stage | Result |
|-------|--------|
| Ingest | X new articles from Y sources |
| Classify | X classified (Y% LLM, Z% fallback) |
| Neutralize | X processed, Y skipped, Z failed |
| Brief | X stories across Y sections |
| Cleanup | X articles hidden |

**Duration**: X.Xs

### If Evaluation Enabled
Also display:
- Classification accuracy
- Neutralization score
- Span precision/recall
- Any prompt updates made

### Alerts
Display any alerts from the response:
- `KEYWORD_FALLBACK_HIGH` - LLM classification falling back too often
- `NEUTRALIZATION_FAILURE_HIGH` - Too many neutralization failures
- `EMPTY_SECTIONS` - Brief sections with no stories

## Notes
- This is equivalent to what Railway cron runs every 4 hours
- For testing, use smaller limits to save API costs
- Pipeline stages run sequentially: ingest → classify → neutralize → brief → cleanup
- Add `evaluate` to run teacher LLM evaluation after pipeline
