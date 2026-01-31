# /status - Check API Deployment Status

## Purpose
Verify API is healthy and check deployment version.

## Instructions

1. Call status endpoint:
   ```bash
   curl -s "https://api-staging-7b4d.up.railway.app/v1/status" \
     -H "X-API-Key: staging-key-123"
   ```

2. Report key metrics:
   - Health status (ok/degraded)
   - Code version
   - Neutralizer provider/model
   - Total articles ingested/neutralized
   - Last pipeline run status
   - Any alerts

3. Compare code_version to expected if doing deployment verification
