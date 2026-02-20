# Async Pipeline Architecture

## Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `PipelineJob` | `app/models.py` | Job state persistence |
| `PipelineJobManager` | `app/services/pipeline_job_manager.py` | Job lifecycle |
| `AsyncPipelineOrchestrator` | `app/services/async_pipeline_orchestrator.py` | Stage execution |
| `CircuitBreaker` | `app/services/resilience.py` | Failure protection |
| `PipelineLogger` | `app/logging_config.py` | Structured JSON logging |

## Alerts

| Alert Code | Threshold | Trigger |
|------------|-----------|---------|
| `llm_latency_high` | >5s avg | LLM calls slow |
| `pipeline_duration_high` | >10 min | Pipeline too slow |
| `token_usage_high` | >500k tokens | Cost concern |

## Running Async Pipeline

```bash
# Start job (returns immediately with job_id)
curl -X POST "https://api-staging-7b4d.up.railway.app/v1/pipeline/scheduled-run-async" \
  -H "X-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"enable_evaluation": true}'

# Poll status
curl "https://api-staging-7b4d.up.railway.app/v1/pipeline/jobs/{job_id}" \
  -H "X-API-Key: $ADMIN_API_KEY"
```

## Key Benefits

- **No timeouts**: Returns 202 immediately, processes in background
- **Progress tracking**: Real-time stage progress via polling or SSE
- **Cancellation**: Can cancel running jobs gracefully
- **Parallel execution**: Stages run with internal parallelism for speed
- **Resilience**: Circuit breaker, retry with backoff, rate limiting

## Performance (Verified)

| Stage | Duration | Notes |
|-------|----------|-------|
| Ingest | ~20s | Parallel RSS fetches |
| Classify | ~2.5 min | LLM classification |
| Neutralize | ~5.5 min | LLM neutralization |
| QC Gate | <1s | 19 checks per article |
| Brief | ~125ms | Assembly |
| **Total** | **~8.5 min** | vs 9-14 min sequential |
