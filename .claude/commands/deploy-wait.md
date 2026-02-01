# /deploy-wait - Wait for Railway Deploy

Wait for the current Railway deployment to complete and verify the service is healthy.

## Usage

```
/deploy-wait
```

## What It Does

1. Waits for current Railway deployment to complete
2. Checks `/v1/status` for healthy state
3. Verifies brief has content
4. Reports summary

## Prerequisites

- Railway MCP server must be configured and running
- Or use fallback HTTP polling method

## Instructions

When user invokes `/deploy-wait`, execute this workflow:

### Option A: Using Railway MCP (Preferred)

If the `railway_deploy_verify` MCP tool is available:

```
Use the railway_deploy_verify tool with default settings.
```

This will:
1. Wait for deploy (up to 5 minutes)
2. Check /v1/status health
3. Check /v1/brief has sections
4. Return structured result

### Option B: HTTP Polling Fallback

If MCP is not available, use HTTP polling:

#### Step 1: Check Current Deploy Status

```bash
# Get current deploy status from Railway API or just wait and check the app
echo "Waiting for deploy to complete..."
```

#### Step 2: Poll Status Endpoint

```bash
# Poll every 10 seconds for up to 5 minutes
for i in {1..30}; do
  STATUS=$(curl -s "https://api-staging-7b4d.up.railway.app/v1/status" \
    -H "X-API-Key: staging-key-123" | python3 -c "
import json, sys
data = json.load(sys.stdin)
print(data.get('health', 'unknown'))
")

  if [ "$STATUS" = "healthy" ]; then
    echo "Deploy complete and healthy!"
    break
  fi

  echo "Waiting... (attempt $i/30)"
  sleep 10
done
```

#### Step 3: Verify Brief

```bash
curl -s "https://api-staging-7b4d.up.railway.app/v1/brief" | python3 -c "
import json, sys
data = json.load(sys.stdin)
sections = data.get('sections', [])
stories = sum(len(s.get('stories', [])) for s in sections)
print(f'Brief has {len(sections)} sections with {stories} stories')
"
```

### Output Format

```
Deploy Wait Results
───────────────────────────────
Deploy Status: ✓ Completed
Health Check:  ✓ Healthy
Brief Check:   ✓ 10 sections, 45 stories
Code Version:  2026.01.31.1
───────────────────────────────
Result: Deploy successful
```

Or if there's an issue:

```
Deploy Wait Results
───────────────────────────────
Deploy Status: ✓ Completed
Health Check:  ✗ Degraded (alerts present)
Brief Check:   ✓ 10 sections, 45 stories
───────────────────────────────
Result: Deploy completed with warnings

Alerts:
- CLASSIFY_FALLBACK_RATE_HIGH: 2.3% of articles used keyword fallback
```

## When to Use

- After pushing code changes
- After changing environment variables
- Before running quality checks
- As first step in deploy verification workflow

## Related Commands

- `/status` - Check API health without waiting
- `/eval-quick` - Quick quality check after deploy
- `/brief` - Check brief content directly
