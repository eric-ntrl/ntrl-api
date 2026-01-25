#!/bin/sh
# Cron script to trigger the scheduled pipeline
curl -X POST \
  "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run" \
  -H "X-API-Key: staging-key-123" \
  -H "Content-Type: application/json" \
  -d '{}' \
  --max-time 600
