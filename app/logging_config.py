"""
Structured JSON logging for pipeline observability.

Provides structured logging with trace IDs for correlating logs across
pipeline stages, plus specialized context managers for LLM and S3 operations.
"""

import json
import logging
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# Context variables for trace correlation
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
stage_var: ContextVar[str | None] = ContextVar("stage", default=None)
component_var: ContextVar[str | None] = ContextVar("component", default=None)


# -----------------------------------------------------------------------------
# JSON Formatter
# -----------------------------------------------------------------------------


class JSONFormatter(logging.Formatter):
    """
    Format log records as single-line JSON for Railway.

    Output format:
    {"timestamp": "...", "level": "INFO", "message": "...", "trace_id": "...", ...}
    """

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add trace context if available
        trace_id = trace_id_var.get()
        if trace_id:
            log_data["trace_id"] = trace_id

        stage = stage_var.get()
        if stage:
            log_data["stage"] = stage

        component = component_var.get()
        if component:
            log_data["component"] = component

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields from record
        for key in [
            "event",
            "duration_ms",
            "items_processed",
            "items_failed",
            "model",
            "provider",
            "tokens_in",
            "tokens_out",
            "cost_usd",
            "operation",
            "key",
            "size_bytes",
            "job_id",
            "article_id",
        ]:
            if hasattr(record, key):
                log_data[key] = getattr(record, key)

        return json.dumps(log_data)


def configure_logging(json_format: bool = True, level: str = "INFO") -> None:
    """
    Configure logging for Railway or local development.

    Args:
        json_format: If True, use JSON format (for Railway). If False, use human-readable format.
        level: Log level (DEBUG, INFO, WARNING, ERROR)
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper()))

    if json_format:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

    root_logger.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)


# -----------------------------------------------------------------------------
# Pipeline Logger
# -----------------------------------------------------------------------------


class PipelineLogger:
    """
    Structured logger for pipeline operations.

    Provides methods for logging with consistent context and structure.
    """

    def __init__(self, name: str = "pipeline"):
        self._logger = logging.getLogger(name)

    def set_context(self, trace_id: str, stage: str | None = None, component: str | None = None) -> None:
        """Set logging context for the current execution."""
        trace_id_var.set(trace_id)
        if stage:
            stage_var.set(stage)
        if component:
            component_var.set(component)

    def clear_context(self) -> None:
        """Clear logging context."""
        trace_id_var.set(None)
        stage_var.set(None)
        component_var.set(None)

    def info(self, event: str, message: str, **kwargs: Any) -> None:
        """Log info message with event type."""
        self._log(logging.INFO, event, message, **kwargs)

    def warning(self, event: str, message: str, **kwargs: Any) -> None:
        """Log warning message with event type."""
        self._log(logging.WARNING, event, message, **kwargs)

    def error(self, event: str, message: str, **kwargs: Any) -> None:
        """Log error message with event type."""
        self._log(logging.ERROR, event, message, **kwargs)

    def debug(self, event: str, message: str, **kwargs: Any) -> None:
        """Log debug message with event type."""
        self._log(logging.DEBUG, event, message, **kwargs)

    def _log(self, level: int, event: str, message: str, **kwargs: Any) -> None:
        """Internal logging method that adds extra fields."""
        extra = {"event": event}
        extra.update(kwargs)
        self._logger.log(level, message, extra=extra)


# Global pipeline logger instance
pipeline_logger = PipelineLogger()


# -----------------------------------------------------------------------------
# Context Managers
# -----------------------------------------------------------------------------


@contextmanager
def log_stage(stage: str, trace_id: str | None = None):
    """
    Context manager for stage-level logging.

    Logs stage start and end with duration, automatically tracks timing.

    Usage:
        with log_stage("ingest", trace_id=job.trace_id):
            # ... stage logic ...
    """
    if trace_id:
        trace_id_var.set(trace_id)
    stage_var.set(stage)

    start_time = time.time()
    logger = logging.getLogger("pipeline")

    logger.info(f"Stage {stage} started", extra={"event": "stage_start", "stage": stage})

    try:
        yield
        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"Stage {stage} completed",
            extra={
                "event": "stage_complete",
                "stage": stage,
                "duration_ms": duration_ms,
            },
        )
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            f"Stage {stage} failed: {e}",
            extra={
                "event": "stage_failed",
                "stage": stage,
                "duration_ms": duration_ms,
            },
            exc_info=True,
        )
        raise
    finally:
        stage_var.set(None)


@contextmanager
def log_llm_call(provider: str, model: str, call_type: str):
    """
    Context manager for LLM call instrumentation.

    Logs call start and end with timing, tokens, and cost estimates.

    Usage:
        with log_llm_call("openai", "gpt-5-mini", "neutralize") as metrics:
            response = await client.chat(...)
            metrics["tokens_in"] = response.usage.prompt_tokens
            metrics["tokens_out"] = response.usage.completion_tokens
    """
    start_time = time.time()
    logger = logging.getLogger("pipeline.llm")
    metrics: dict = {"tokens_in": 0, "tokens_out": 0}

    logger.debug(
        f"LLM call started: {provider}/{model} for {call_type}",
        extra={
            "event": "llm_call_start",
            "provider": provider,
            "model": model,
            "call_type": call_type,
        },
    )

    try:
        yield metrics

        duration_ms = int((time.time() - start_time) * 1000)
        cost_usd = _estimate_llm_cost(provider, model, metrics["tokens_in"], metrics["tokens_out"])

        logger.info(
            f"LLM call completed: {provider}/{model} ({duration_ms}ms, ${cost_usd:.4f})",
            extra={
                "event": "llm_call_complete",
                "provider": provider,
                "model": model,
                "call_type": call_type,
                "duration_ms": duration_ms,
                "tokens_in": metrics["tokens_in"],
                "tokens_out": metrics["tokens_out"],
                "cost_usd": cost_usd,
            },
        )
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            f"LLM call failed: {provider}/{model} - {e}",
            extra={
                "event": "llm_call_failed",
                "provider": provider,
                "model": model,
                "call_type": call_type,
                "duration_ms": duration_ms,
            },
        )
        raise


@contextmanager
def log_s3_operation(operation: str, key: str):
    """
    Context manager for S3 operation instrumentation.

    Logs operation start and end with timing and size.

    Usage:
        with log_s3_operation("download", "raw/abc123.txt") as metrics:
            content = s3.download(key)
            metrics["size_bytes"] = len(content)
    """
    start_time = time.time()
    logger = logging.getLogger("pipeline.storage")
    metrics: dict = {"size_bytes": 0}

    try:
        yield metrics

        duration_ms = int((time.time() - start_time) * 1000)
        logger.debug(
            f"S3 {operation} completed: {key} ({metrics['size_bytes']} bytes, {duration_ms}ms)",
            extra={
                "event": f"s3_{operation}_complete",
                "operation": operation,
                "key": key,
                "duration_ms": duration_ms,
                "size_bytes": metrics["size_bytes"],
            },
        )
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(
            f"S3 {operation} failed: {key} - {e}",
            extra={
                "event": f"s3_{operation}_failed",
                "operation": operation,
                "key": key,
                "duration_ms": duration_ms,
            },
        )
        raise


# -----------------------------------------------------------------------------
# Progress Tracker
# -----------------------------------------------------------------------------


@dataclass
class ProgressTracker:
    """
    Track progress for batch operations with periodic logging.

    Usage:
        tracker = ProgressTracker(total=100, stage="neutralize", log_every=10)
        for item in items:
            process(item)
            tracker.increment()
        tracker.finish()
    """

    total: int
    stage: str
    log_every: int = 10

    processed: int = field(default=0, init=False)
    succeeded: int = field(default=0, init=False)
    failed: int = field(default=0, init=False)
    _start_time: float = field(default_factory=time.time, init=False)
    _logger: logging.Logger = field(init=False)

    def __post_init__(self):
        self._logger = logging.getLogger("pipeline.progress")

    def increment(self, success: bool = True) -> None:
        """Increment progress counter."""
        self.processed += 1
        if success:
            self.succeeded += 1
        else:
            self.failed += 1

        if self.processed % self.log_every == 0 or self.processed == self.total:
            self._log_progress()

    def _log_progress(self) -> None:
        """Log current progress."""
        elapsed = time.time() - self._start_time
        rate = self.processed / elapsed if elapsed > 0 else 0
        remaining = (self.total - self.processed) / rate if rate > 0 else 0

        self._logger.info(
            f"{self.stage}: {self.processed}/{self.total} "
            f"({self.succeeded} ok, {self.failed} failed) "
            f"[{rate:.1f}/s, ~{remaining:.0f}s remaining]",
            extra={
                "event": "progress_update",
                "stage": self.stage,
                "items_processed": self.processed,
                "items_total": self.total,
                "items_succeeded": self.succeeded,
                "items_failed": self.failed,
                "rate_per_second": round(rate, 2),
                "elapsed_seconds": round(elapsed, 1),
            },
        )

    def finish(self) -> dict:
        """Finalize progress tracking and return summary."""
        elapsed = time.time() - self._start_time
        rate = self.processed / elapsed if elapsed > 0 else 0

        self._logger.info(
            f"{self.stage}: Completed {self.processed}/{self.total} "
            f"({self.succeeded} ok, {self.failed} failed) in {elapsed:.1f}s",
            extra={
                "event": "progress_complete",
                "stage": self.stage,
                "items_processed": self.processed,
                "items_total": self.total,
                "items_succeeded": self.succeeded,
                "items_failed": self.failed,
                "duration_seconds": round(elapsed, 1),
                "rate_per_second": round(rate, 2),
            },
        )

        return {
            "processed": self.processed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "duration_seconds": round(elapsed, 1),
        }


# -----------------------------------------------------------------------------
# LLM Cost Estimation
# -----------------------------------------------------------------------------

# Approximate costs per 1M tokens (as of late 2025)
LLM_COSTS = {
    # OpenAI
    ("openai", "gpt-4o"): {"input": 2.50, "output": 10.00},
    ("openai", "gpt-4o-mini"): {"input": 0.15, "output": 0.60},
    ("openai", "gpt-5-nano"): {"input": 0.05, "output": 0.40},
    ("openai", "gpt-5-mini"): {"input": 0.25, "output": 2.00},
    ("openai", "gpt-5.1"): {"input": 1.25, "output": 10.00},
    # Anthropic
    ("anthropic", "claude-sonnet-4-6"): {"input": 3.00, "output": 15.00},
    ("anthropic", "claude-opus-4-6"): {"input": 5.00, "output": 25.00},
    ("anthropic", "claude-sonnet-4-5"): {"input": 3.00, "output": 15.00},
    ("anthropic", "claude-haiku-4-5"): {"input": 1.00, "output": 5.00},
    ("anthropic", "claude-opus-4-5"): {"input": 5.00, "output": 25.00},
    # Google
    ("google", "gemini-2.0-flash"): {"input": 0.075, "output": 0.30},
    ("google", "gemini-1.5-flash"): {"input": 0.075, "output": 0.30},
}


def _estimate_llm_cost(provider: str, model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate LLM cost based on token usage."""
    key = (provider.lower(), model.lower())

    # Try exact match first
    costs = LLM_COSTS.get(key)

    # Try partial match (for model name variations)
    if not costs:
        for (p, m), c in LLM_COSTS.items():
            if p == provider.lower() and m in model.lower():
                costs = c
                break

    if not costs:
        # Default to a reasonable estimate
        costs = {"input": 1.0, "output": 3.0}

    input_cost = (tokens_in / 1_000_000) * costs["input"]
    output_cost = (tokens_out / 1_000_000) * costs["output"]

    return round(input_cost + output_cost, 6)


# -----------------------------------------------------------------------------
# Metrics Collector
# -----------------------------------------------------------------------------


@dataclass
class MetricsCollector:
    """
    Collect metrics for a pipeline job.

    Aggregates timing, token usage, and cost across all operations.
    """

    job_id: str

    # Timing
    stage_timings: dict = field(default_factory=dict)
    llm_latencies: list = field(default_factory=list)
    s3_latencies: list = field(default_factory=list)

    # Tokens
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    # Cost
    total_cost_usd: float = 0.0

    def record_stage_timing(self, stage: str, duration_ms: int) -> None:
        """Record stage timing."""
        self.stage_timings[stage] = duration_ms

    def record_llm_call(self, duration_ms: int, tokens_in: int, tokens_out: int, cost_usd: float) -> None:
        """Record LLM call metrics."""
        self.llm_latencies.append(duration_ms)
        self.total_input_tokens += tokens_in
        self.total_output_tokens += tokens_out
        self.total_cost_usd += cost_usd

    def record_s3_operation(self, duration_ms: int) -> None:
        """Record S3 operation timing."""
        self.s3_latencies.append(duration_ms)

    def get_summary(self) -> dict:
        """Get metrics summary."""
        return {
            "stage_timings": self.stage_timings,
            "avg_llm_latency_ms": int(sum(self.llm_latencies) / len(self.llm_latencies)) if self.llm_latencies else 0,
            "max_llm_latency_ms": max(self.llm_latencies) if self.llm_latencies else 0,
            "avg_s3_latency_ms": int(sum(self.s3_latencies) / len(self.s3_latencies)) if self.s3_latencies else 0,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost_usd": round(self.total_cost_usd, 4),
        }
