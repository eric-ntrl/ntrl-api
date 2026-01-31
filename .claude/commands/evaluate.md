# /evaluate - Run Pipeline Evaluation

## Purpose
Run teacher LLM evaluation on recent pipeline output to assess classification accuracy, neutralization quality, and span detection performance.

## Arguments
- `$ARGUMENTS` - Sample size (default: 10), or include "auto-optimize" to enable prompt improvements

Examples:
- `/evaluate` - Run with 10 samples
- `/evaluate 20` - Run with 20 samples
- `/evaluate auto-optimize` - Run with 10 samples and auto-optimize prompts
- `/evaluate 15 auto-optimize` - Run with 15 samples and auto-optimize

## Instructions

1. Parse arguments for sample_size and auto-optimize flag

2. Run the evaluation:
   ```bash
   curl -s -X POST "https://api-staging-7b4d.up.railway.app/v1/admin/evaluation/run" \
     -H "Content-Type: application/json" \
     -H "X-API-Key: staging-key-123" \
     -d '{"sample_size": SAMPLE_SIZE, "enable_auto_optimize": AUTO_OPTIMIZE}'
   ```

3. Parse and display results in this format:

   **Evaluation Results** (sample_size articles)

   | Metric | Score | vs Previous |
   |--------|-------|-------------|
   | Classification Accuracy | X% | +/-Y% |
   | Neutralization Score | X.X/10 | +/-Y |
   | Span Precision | X% | +/-Y% |
   | Span Recall | X% | +/-Y% |
   | Overall Quality | X.X/10 | +/-Y |

4. If there are missed items, summarize:
   - Total missed manipulations
   - Top missed phrases by category
   - False positives count

5. If recommendations exist, list them with priority

6. If auto-optimize was enabled and prompts were updated, show:
   - Which prompts were changed
   - Version changes (old → new)
   - Change reason

7. Report cost: tokens used and estimated USD

## Error Handling

If evaluation fails, check:
- API health with `/status`
- Whether there are neutralized articles to evaluate
- Check for timeout (evaluation can take 30-60s for large samples)
