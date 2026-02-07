"""
Resilience patterns for pipeline execution.

Provides retry logic, circuit breaker, and rate limiting for LLM and external
service calls to handle transient failures gracefully.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# -----------------------------------------------------------------------------
# Circuit Breaker
# -----------------------------------------------------------------------------


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation, requests pass through
    OPEN = "open"  # Failing, requests are blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreaker:
    """
    Circuit breaker to prevent cascade failures.

    When a service fails repeatedly, the circuit opens and blocks further
    requests for a cooldown period. After the cooldown, it enters half-open
    state and allows a single request to test if the service recovered.

    Usage:
        breaker = CircuitBreaker(name="openai", failure_threshold=5)

        try:
            result = await breaker.call(call_openai, prompt)
        except CircuitOpenError:
            # Handle circuit open
            pass
    """

    name: str
    failure_threshold: int = 5
    reset_timeout_seconds: int = 60
    half_open_max_calls: int = 1

    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0, init=False)
    _half_open_calls: int = field(default=0, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for timeout."""
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time >= self.reset_timeout_seconds:
                return CircuitState.HALF_OPEN
        return self._state

    async def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """
        Execute function through the circuit breaker.

        Raises:
            CircuitOpenError: If circuit is open
            Exception: Any exception from the wrapped function
        """
        async with self._lock:
            current_state = self.state

            if current_state == CircuitState.OPEN:
                raise CircuitOpenError(
                    f"Circuit '{self.name}' is open. Will retry after {self.reset_timeout_seconds}s cooldown."
                )

            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self.half_open_max_calls:
                    raise CircuitOpenError(f"Circuit '{self.name}' is half-open with max test calls reached.")
                self._half_open_calls += 1

        try:
            # Execute the function (outside the lock)
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            # Success - reset the circuit
            async with self._lock:
                self._failure_count = 0
                self._half_open_calls = 0
                if self._state != CircuitState.CLOSED:
                    logger.info(f"Circuit '{self.name}' closed after successful call")
                self._state = CircuitState.CLOSED

            return result

        except Exception:
            async with self._lock:
                self._failure_count += 1
                self._last_failure_time = time.time()

                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        f"Circuit '{self.name}' opened after {self._failure_count} failures. "
                        f"Cooldown: {self.reset_timeout_seconds}s"
                    )
                elif self.state == CircuitState.HALF_OPEN:
                    # Failed during half-open test, reopen
                    self._state = CircuitState.OPEN
                    logger.warning(f"Circuit '{self.name}' reopened after half-open failure")

            raise

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0
        logger.info(f"Circuit '{self.name}' manually reset")


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""

    pass


# -----------------------------------------------------------------------------
# Retry Decorators
# -----------------------------------------------------------------------------


def with_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 30.0,
    retry_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Decorator for async functions with exponential backoff retry.

    Args:
        max_attempts: Maximum number of retry attempts
        min_wait: Minimum wait time between retries (seconds)
        max_wait: Maximum wait time between retries (seconds)
        retry_exceptions: Tuple of exception types to retry on

    Usage:
        @with_retry(max_attempts=3, retry_exceptions=(TimeoutError, RateLimitError))
        async def call_llm(prompt: str) -> str:
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except retry_exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise

                    wait_time = min(min_wait * (2 ** (attempt - 1)), max_wait)
                    logger.warning(f"{func.__name__} attempt {attempt} failed: {e}. Retrying in {wait_time:.1f}s...")
                    await asyncio.sleep(wait_time)

            # Should not reach here, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed without exception")

        return wrapper

    return decorator


def with_sync_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 30.0,
    retry_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Decorator for sync functions with exponential backoff retry.

    Args:
        max_attempts: Maximum number of retry attempts
        min_wait: Minimum wait time between retries (seconds)
        max_wait: Maximum wait time between retries (seconds)
        retry_exceptions: Tuple of exception types to retry on
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retry_exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise

                    wait_time = min(min_wait * (2 ** (attempt - 1)), max_wait)
                    logger.warning(f"{func.__name__} attempt {attempt} failed: {e}. Retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)

            if last_exception:
                raise last_exception
            raise RuntimeError(f"{func.__name__} failed without exception")

        return wrapper

    return decorator


# -----------------------------------------------------------------------------
# Rate Limiter
# -----------------------------------------------------------------------------


@dataclass
class RateLimiter:
    """
    Token bucket rate limiter for controlling request rates.

    Usage:
        limiter = RateLimiter(tokens_per_second=10, max_tokens=50)

        async with limiter:
            await call_api()
    """

    tokens_per_second: float
    max_tokens: int

    _tokens: float = field(init=False)
    _last_update: float = field(init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self):
        self._tokens = float(self.max_tokens)
        self._last_update = time.time()

    async def acquire(self, tokens: int = 1) -> None:
        """Acquire tokens, waiting if necessary."""
        async with self._lock:
            while True:
                now = time.time()
                elapsed = now - self._last_update
                self._tokens = min(self.max_tokens, self._tokens + elapsed * self.tokens_per_second)
                self._last_update = now

                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return

                # Calculate wait time
                needed = tokens - self._tokens
                wait_time = needed / self.tokens_per_second
                await asyncio.sleep(wait_time)

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


# -----------------------------------------------------------------------------
# LLM-Specific Errors
# -----------------------------------------------------------------------------


class LLMRateLimitError(Exception):
    """Raised when LLM API returns rate limit error."""

    pass


class LLMTimeoutError(Exception):
    """Raised when LLM API call times out."""

    pass


class LLMServiceError(Exception):
    """Raised when LLM API returns service error (5xx)."""

    pass


# Default retry configuration for LLM calls
LLM_RETRY_EXCEPTIONS = (LLMRateLimitError, LLMTimeoutError, LLMServiceError)


def llm_retry(func: Callable[..., T]) -> Callable[..., T]:
    """
    Decorator with LLM-optimized retry settings.

    Uses:
    - 3 attempts
    - Exponential backoff: 2s, 4s, 8s (capped at 30s)
    - Retries on rate limit, timeout, and service errors
    """
    return with_retry(
        max_attempts=3,
        min_wait=2.0,
        max_wait=30.0,
        retry_exceptions=LLM_RETRY_EXCEPTIONS,
    )(func)


# -----------------------------------------------------------------------------
# Timeout Helper
# -----------------------------------------------------------------------------


async def with_timeout(coro, timeout_seconds: float, error_message: str = "Operation timed out"):
    """
    Execute a coroutine with a timeout.

    Args:
        coro: The coroutine to execute
        timeout_seconds: Maximum time to wait
        error_message: Error message if timeout occurs

    Raises:
        LLMTimeoutError: If the operation times out
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except TimeoutError:
        raise LLMTimeoutError(f"{error_message} (timeout: {timeout_seconds}s)")
