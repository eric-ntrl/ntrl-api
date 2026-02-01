# Testing Reference

> Quick reference for testing NTRL. Full details in `../team/development-workflow.md`.

## Running Tests

```bash
# Backend (ntrl-api)
cd /Users/ericrbrown/Documents/NTRL/code/ntrl-api
pipenv run pytest tests/

# Frontend (ntrl-app)
cd /Users/ericrbrown/Documents/NTRL/code/ntrl-app
npm test
```

## Backend Test Structure

```
tests/
├── test_pipeline.py      # Full pipeline tests
├── test_neutralizer.py   # Neutralization tests
├── test_classifier.py    # Classification tests
├── test_spans.py         # Span detection tests
└── conftest.py           # Fixtures
```

### Known Test Behaviors

- **6 expected failures**: MockNeutralizerProvider achieves ~5% precision (tests pipeline flow, not quality)
- MockNeutralizerProvider is test-only, never production fallback

## Cost-Efficient Testing

### Use `story_ids` for Targeted Work

```bash
# Re-neutralize specific articles only
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/neutralize/run" \
  -H "X-API-Key: staging-key-123" \
  -H "Content-Type: application/json" \
  -d '{"story_ids": ["id1", "id2"], "force": true}'
```

### Test via Debug Endpoints First

Before triggering full re-neutralization:

1. `GET /v1/stories/{id}/debug/spans` — see classification results
2. Review spans and categories
3. Only re-neutralize if classification looks correct

### Pick Representative Test Articles

Choose 5-10 articles covering:
- Different sources (AP wire vs. Daily Mail tabloid)
- Different manipulation levels (low, medium, high)
- Different lengths (short, medium, long)
- Different categories

Target high-manipulation sources: The Sun, Daily Mail

## Debug Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/stories/{id}/debug` | Full debug info |
| `GET /v1/stories/{id}/debug/spans` | Span detection trace |
| `GET /v1/status` | Pipeline status |

## Frontend Testing

### UI Visual Testing with Playwright

```bash
cd /Users/ericrbrown/Documents/NTRL/code/ntrl-app

# Run capture script
node e2e/capture-all-screens.cjs

# Run Playwright tests
npx playwright test e2e/claude-ui-check.spec.ts
```

Screenshots saved to `/Users/ericrbrown/Documents/NTRL/screen shots/`

### Test IDs Available

- `testID="ntrl-view-screen"` — Ntrl content container
- `testID="ntrl-view-text"` — Article text in ntrl view
- `testID="highlight-span-{index}"` — Individual highlighted spans

## Validation Checklist

### After Prompt Changes
1. Re-neutralize 5-10 test articles
2. Check span detection quality
3. Rebuild brief
4. Run evaluation

### After UI Changes
1. Capture screenshots (Playwright)
2. Verify dark mode support
3. Check all screen states

### After Deploy
1. `GET /v1/status` returns healthy
2. `code_version` matches expected
3. Brief has content
4. Test article appears correctly in app
