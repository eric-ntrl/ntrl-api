# /eval-quick - Quick Quality Evaluation

Run a simplified evaluation with human-readable output.

## Usage

```
/eval-quick [count]
```

- `count` (optional): Number of articles to evaluate (default: 5)

## What It Does

1. Selects random articles from recent pipeline runs
2. Runs teacher LLM evaluation on each
3. Computes quality metrics
4. Prints formatted summary

## Instructions

When user invokes `/eval-quick`, execute this workflow:

### Step 1: Get Recent Articles

```bash
curl -s "https://api-staging-7b4d.up.railway.app/v1/brief?hours=24" | python3 -c "
import json, sys, random
data = json.load(sys.stdin)
stories = []
for section in data.get('sections', []):
    stories.extend(section.get('stories', []))
sample = random.sample(stories, min(5, len(stories)))
for s in sample:
    print(s['id'])
"
```

### Step 2: Evaluate Each Article

For each article ID, call the debug/spans endpoint to get current span detection:

```bash
curl -s "https://api-staging-7b4d.up.railway.app/v1/stories/{id}/debug/spans" \
  -H "X-API-Key: staging-key-123"
```

### Step 3: Compute Metrics

From the debug output, compute:
- **Span Count**: `llm_phrases_count`
- **Position Match Rate**: `after_position_matching / llm_phrases_count`
- **Quote Filter Rate**: phrases filtered by quotes
- **FP Filter Rate**: phrases filtered as false positives

### Step 4: Print Summary

Format the output like this:

```
Quality Check (5 articles)
─────────────────────────────────────
Article 1: 12 phrases detected, 10 matched, 2 filtered
Article 2: 5 phrases detected, 5 matched, 0 filtered
Article 3: 8 phrases detected, 7 matched, 1 filtered
Article 4: 3 phrases detected, 3 matched, 0 filtered
Article 5: 15 phrases detected, 12 matched, 3 filtered
─────────────────────────────────────
Totals:
  Phrases Detected: 43
  Position Match:   37 (86%)
  Quote Filtered:   4 (9%)
  FP Filtered:      2 (5%)
─────────────────────────────────────
Status: ✓ All metrics within normal range
```

### Interpreting Results

| Metric | Normal Range | Concern If |
|--------|--------------|------------|
| Position Match | > 80% | < 70% |
| Quote Filtered | < 20% | > 30% |
| FP Filtered | < 10% | > 20% |

### If Metrics Are Concerning

Suggest:
1. Check specific articles with `/debug-spans {id}`
2. Review prompt for unclear instructions
3. Consider running full evaluation with `/evaluate`

## Example Session

```
User: /eval-quick 3

Claude: Running quick quality check on 3 articles...

Quality Check (3 articles)
─────────────────────────────────────
Article 1: "Senate passes major bill" - 8 phrases, 7 matched
Article 2: "Markets rally on news" - 3 phrases, 3 matched
Article 3: "Tech CEO announces plans" - 12 phrases, 10 matched
─────────────────────────────────────
Totals:
  Phrases Detected: 23
  Position Match:   20 (87%)
  Quote Filtered:   2 (9%)
  FP Filtered:      1 (4%)
─────────────────────────────────────
Status: ✓ All metrics within normal range
```
