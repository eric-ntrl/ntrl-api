# UI Text Length Adjustment

Adjust text length constraints for UI display (feed summaries, titles, etc.)

## When to Use
- User reports text is "too long" or shows "..."
- User wants to change number of lines displayed
- Text truncation issues in the app

## Process

### Step 1: Identify the Field
Common fields and their locations in `app/services/neutralizer.py`:
- `feed_title` - ~6 words, 12 max
- `feed_summary` - Target 85-100 chars for 3 lines
- `detail_title` - ~12 words max
- `detail_brief` - 3-5 paragraphs

### Step 2: Calculate Target Length
- Mobile displays ~38-42 chars per line
- For N lines: target = (N x 38) - 15% buffer
- 2 lines = 65 chars | 3 lines = 100 chars | 4 lines = 135 chars

### Step 3: Update the Prompt
In `neutralizer.py`, find and update ALL of these locations:
1. Task description (search for "Produce three distinct outputs")
2. Section header (search for "OUTPUT 2: feed_summary")
3. HARD CONSTRAINTS section
4. GOOD/BAD examples (CRITICAL - LLMs follow examples more than instructions)
5. JSON format description
6. Verification checklist

### Step 4: Make Examples Match Target
This is the most important step. LLMs produce output similar to examples.
- If target is 100 chars, examples should be 70-85 chars
- Provide 3-4 GOOD examples at target length
- Provide 1-2 BAD examples showing what's too long

Example pattern:
```
GOOD: "Short example here. Second sentence." (62 chars)
GOOD: "Another example sentence. Brief follow-up." (58 chars)
BAD: "This example is too long and demonstrates what not to do..." (TOO LONG)
```

### Step 5: Deploy and Regenerate
```bash
# 1. Commit and push
git add app/services/neutralizer.py
git commit -m "Adjust feed_summary to X chars for N-line display"
git push origin main

# 2. Wait for Railway deployment (90 seconds)
sleep 90

# 3. Re-neutralize articles with force flag
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -d '{"limit": 75, "force": true, "max_workers": 5}'

# 4. Rebuild brief
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/brief/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -d '{"cutoff_hours": 24, "force": true}'
```

### Step 6: Verify Pass Rate
```bash
curl -s "https://api-staging-7b4d.up.railway.app/v1/brief" | python3 -c "
import json, sys
data = json.load(sys.stdin)
target = 100  # Adjust to your target
total = passed = 0
for s in data['sections']:
  for story in s['stories']:
    total += 1
    if len(story['feed_summary']) <= target:
      passed += 1
    else:
      print(f'FAIL [{len(story[\"feed_summary\"])}]: {story[\"feed_summary\"][:60]}...')
print(f'\\nPASS RATE: {passed}/{total} ({100*passed/total:.1f}%)')
"
```

Target: 95%+ pass rate. If lower, reduce the stated limit further.

## Common Pitfalls
- Don't just change `numberOfLines` in React Native - that only truncates with "..."
- Don't trust the LLM to count accurately - always add 15-20% buffer
- Don't forget to update examples - they matter more than stated limits
- Don't skip re-neutralization - old content keeps old lengths
- Don't check results too quickly - wait for Railway deployment

## Iteration Pattern
If pass rate is low:
1. Check what lengths are being produced (use verify script)
2. Reduce stated limit by 10-15%
3. Make examples even shorter
4. Re-deploy and re-neutralize
5. Repeat until 95%+ pass rate
