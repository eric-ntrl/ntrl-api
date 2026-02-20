# /classify - Run Classification Batch

## Purpose
Classify articles with the LLM classifier (domain + feed_category).

## Arguments
- `$ARGUMENTS` - Limit (default: 200), or include "force" to reclassify, or "all" to process all

Examples:
- `/classify` - Classify up to 200 pending articles
- `/classify 50` - Classify up to 50 pending articles
- `/classify force` - Reclassify 200 already-classified articles
- `/classify 100 force` - Reclassify up to 100 articles
- `/classify all` - Process ALL pending articles in batches of 200

## Instructions

### Standard Classification (pending articles)
```bash
curl -s -X POST "https://api-staging-7b4d.up.railway.app/v1/classify/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -d '{"limit": LIMIT}'
```

### Force Reclassification
```bash
curl -s -X POST "https://api-staging-7b4d.up.railway.app/v1/classify/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -d '{"limit": LIMIT, "force": true}'
```

### Process All (batch mode)
If "all" flag is provided:
1. First check how many articles need classification
2. Process in batches of 200 with 5-second pause between batches
3. Report progress after each batch
4. Stop when no more pending articles

## Output Format

Report after completion:

| Metric | Value |
|--------|-------|
| Articles Processed | X |
| LLM Success | X (Y%) |
| Keyword Fallback | X (Y%) |
| Failed | X |
| Duration | X.Xs |

If keyword fallback rate > 1%, flag as warning (indicates LLM issues).

### Feed Category Distribution
After classification, show the distribution:
```bash
# Get brief to see category counts
curl -s "https://api-staging-7b4d.up.railway.app/v1/brief" \
  -H "X-API-Key: $ADMIN_API_KEY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for s in d.get('sections', []):
    print(f\"{s['name']}: {len(s.get('stories', []))} stories\")
"
```

## Notes
- Classification uses gpt-4o-mini primary, gemini-2.0-flash fallback
- Enhanced keyword classifier is last resort (<1% of articles)
- Use `force` after prompt changes to reclassify with new prompts
- Run `/brief` after classification to see updated distribution
