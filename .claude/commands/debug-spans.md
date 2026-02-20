# /debug-spans - Debug Span Detection Pipeline

## Purpose
Run fresh span detection and compare pipeline stages for debugging.

## Arguments
- `$ARGUMENTS` - Story ID (required)

## Instructions

1. Call debug endpoint:
   ```bash
   curl -s "https://api-staging-7b4d.up.railway.app/v1/debug/span-pipeline?story_id=$STORY_ID" \
     -H "X-API-Key: $ADMIN_API_KEY"
   ```

2. Analyze and report:
   - Detection mode (single vs multi_pass)
   - Test 1 (body-only) reasons
   - Test 2 (with title) reasons
   - Test 3 (production config) reasons
   - Any discrepancies between tests

3. Compare fresh detection to stored spans in DB
