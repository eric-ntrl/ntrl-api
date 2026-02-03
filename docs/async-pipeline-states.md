# Async Pipeline Job State Machine

This document describes the state machine for async pipeline jobs, including all valid states, transitions, and stage execution flow.

## Job Status State Diagram

```mermaid
stateDiagram-v2
    [*] --> PENDING: create_job()

    PENDING --> RUNNING: execute_job() starts
    PENDING --> CANCELLED: cancel_job() before task starts

    RUNNING --> COMPLETED: All stages succeed
    RUNNING --> PARTIAL: Mixed success/failure across stages
    RUNNING --> FAILED: Stage fails or orchestrator exception
    RUNNING --> CANCELLED: cancel_job() + CancelledError caught

    COMPLETED --> [*]
    PARTIAL --> [*]
    FAILED --> [*]
    CANCELLED --> [*]
```

## State Descriptions

| Status | Description | Terminal? |
|--------|-------------|-----------|
| `PENDING` | Job created, waiting for background task to start | No |
| `RUNNING` | Background task executing, stages in progress | No |
| `COMPLETED` | All stages finished successfully | Yes |
| `PARTIAL` | Some stages succeeded, others failed | Yes |
| `FAILED` | First stage failed or orchestrator exception | Yes |
| `CANCELLED` | Job was cancelled via `cancel_job()` | Yes |

## Transition Triggers

| From | To | Trigger |
|------|-----|---------|
| `[*]` | `PENDING` | `PipelineJobManager.start_job()` creates job record |
| `PENDING` | `RUNNING` | `_execute_job()` background task starts, sets `started_at` |
| `PENDING` | `CANCELLED` | `cancel_job()` called before task begins (task.cancel() on pending task) |
| `RUNNING` | `COMPLETED` | `_determine_overall_status()` finds all stages "completed" |
| `RUNNING` | `PARTIAL` | Some stages "completed", others "failed" |
| `RUNNING` | `FAILED` | All stages "failed" or unhandled exception in orchestrator |
| `RUNNING` | `CANCELLED` | `asyncio.CancelledError` caught in `_execute_job()` |

## Stage Execution Flow

The orchestrator executes stages sequentially with cancellation checks between each:

```mermaid
flowchart TD
    START([Job Starts]) --> CHECK1{Cancelled?}

    CHECK1 -->|Yes| CANCEL_OUT([CANCELLED])
    CHECK1 -->|No| INGEST[INGEST Stage]

    INGEST --> CHECK2{Cancelled?}
    CHECK2 -->|Yes| CANCEL_OUT
    CHECK2 -->|No| CLASSIFY[CLASSIFY Stage]

    CLASSIFY --> CHECK3{Cancelled?}
    CHECK3 -->|Yes| CANCEL_OUT
    CHECK3 -->|No| NEUTRALIZE[NEUTRALIZE Stage]

    NEUTRALIZE --> CHECK4{Cancelled?}
    CHECK4 -->|Yes| CANCEL_OUT
    CHECK4 -->|No| BRIEF[BRIEF Assembly]

    BRIEF --> SUMMARY[Create Summary]
    SUMMARY --> EVAL_CHECK{enable_evaluation?}

    EVAL_CHECK -->|No| DETERMINE[Determine Status]
    EVAL_CHECK -->|Yes| CHECK5{Cancelled?}

    CHECK5 -->|Yes| CANCEL_OUT
    CHECK5 -->|No| EVAL[EVALUATION Stage]

    EVAL --> OPT_CHECK{enable_auto_optimize?}
    OPT_CHECK -->|No| DETERMINE
    OPT_CHECK -->|Yes| CHECK6{Cancelled?}

    CHECK6 -->|Yes| CANCEL_OUT
    CHECK6 -->|No| OPTIMIZE[OPTIMIZATION Stage]

    OPTIMIZE --> DETERMINE

    DETERMINE --> FINAL{All Completed?}
    FINAL -->|Yes| COMPLETED_OUT([COMPLETED])
    FINAL -->|Mixed| PARTIAL_OUT([PARTIAL])
    FINAL -->|All Failed| FAILED_OUT([FAILED])
```

## Stage-Level Status

Each stage produces its own status independent of the job status:

| Stage Status | Meaning |
|--------------|---------|
| `completed` | Stage finished without errors |
| `partial` | Stage finished with some errors (e.g., classify had failures) |
| `failed` | Stage threw exception |
| `skipped` | Stage was not run (e.g., optimization without evaluation) |

## Cancellation Handling

1. **User requests cancellation**: `cancel_job()` sets `cancel_requested=True` in DB and calls `task.cancel()`
2. **Orchestrator checks**: `_check_cancelled()` polls DB between stages
3. **Task receives signal**: `asyncio.CancelledError` raised
4. **Cleanup**: Job status set to `CANCELLED`, `finished_at` recorded

```python
# Cancellation check between stages
if await self._check_cancelled():
    return self._build_cancelled_result()
```

## Stale Job Cleanup

Jobs stuck in `PENDING` or `RUNNING` for >2 hours are marked `FAILED` by `cleanup_stale_jobs()`:

```mermaid
flowchart LR
    STALE[Stale Job<br/>age > 2h] --> FAILED_CLEANUP[Mark FAILED]
    FAILED_CLEANUP --> ERROR[Add error:<br/>'Job timed out<br/>or was orphaned']
```

## Key Files

| Component | Location |
|-----------|----------|
| `PipelineJobStatus` enum | `app/models.py:163` |
| `PipelineJobManager` | `app/services/pipeline_job_manager.py` |
| `AsyncPipelineOrchestrator` | `app/services/async_pipeline_orchestrator.py` |
| Job endpoints | `app/routers/admin.py` (search for `/pipeline/jobs`) |
