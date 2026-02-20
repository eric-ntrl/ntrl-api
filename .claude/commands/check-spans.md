# /check-spans - Check Article Span Reasons

## Purpose
Quickly check span reason diversity for an article to verify fix deployment.

## Arguments
- `$ARGUMENTS` - Story ID (optional - defaults to first article from brief)

## Instructions

1. If no story_id provided, get first article from brief:
   ```bash
   STORY_ID=$(curl -s "https://api-staging-7b4d.up.railway.app/v1/brief" \
     -H "X-API-Key: $ADMIN_API_KEY" | jq -r '.sections[0].stories[0].id')
   ```

2. Fetch transparency data and analyze:
   ```bash
   curl -s "https://api-staging-7b4d.up.railway.app/v1/stories/$STORY_ID/transparency" \
     -H "X-API-Key: $ADMIN_API_KEY" | python3 -c "
   import sys, json
   d = json.load(sys.stdin)
   if 'spans' in d:
       reasons = [s['reason'] for s in d['spans']]
       print(f'Span count: {len(reasons)}')
       print(f'Unique reasons: {set(reasons)}')
       from collections import Counter
       for reason, count in Counter(reasons).most_common():
           print(f'  {reason}: {count}')
   "
   ```

3. Report cache status (check X-Cache header)

4. Flag if all reasons are same (potential bug indicator)
