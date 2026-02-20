#!/bin/sh
# Cron script to trigger the scheduled pipeline
curl -X POST \
  "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run" \
  -H "X-API-Key: ${ADMIN_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"enable_evaluation": true, "enable_auto_optimize": true}' \
  --max-time 600
