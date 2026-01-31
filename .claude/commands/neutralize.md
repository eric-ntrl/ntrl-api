# /neutralize - Re-neutralize Articles

## Purpose
Re-run neutralization pipeline on pending or existing articles.

## Arguments
- `$ARGUMENTS` - Number of articles to process (default: 10)
- Include "force" to re-process already-neutralized articles

## Instructions

1. Parse arguments for limit and force flag

2. Run neutralization:
   ```bash
   curl -s -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: staging-key-123" \
     -d '{"limit": LIMIT, "force": FORCE}'
   ```

3. Report results: processed, skipped, failed counts

4. Offer to rebuild brief if articles were processed
