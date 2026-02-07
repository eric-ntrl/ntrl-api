"""
Unit tests for resilience patterns.

Tests circuit breaker, retry decorators, and rate limiter.
"""

import asyncio
import time

import pytest

from app.services.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    LLMRateLimitError,
    LLMTimeoutError,
    RateLimiter,
    with_retry,
    with_sync_retry,
    with_timeout,
)


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initial_state_closed(self):
        """Test that circuit starts in closed state."""
        breaker = CircuitBreaker(name="test", failure_threshold=3)
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_successful_call(self):
        """Test successful call passes through."""
        breaker = CircuitBreaker(name="test", failure_threshold=3)

        async def success():
            return "ok"

        result = await breaker.call(success)
        assert result == "ok"
        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failed_calls_open_circuit(self):
        """Test that consecutive failures open the circuit."""
        breaker = CircuitBreaker(name="test", failure_threshold=3)

        async def fail():
            raise ValueError("test error")

        # First two failures should not open circuit
        for i in range(2):
            with pytest.raises(ValueError):
                await breaker.call(fail)
            assert breaker.state == CircuitState.CLOSED

        # Third failure should open circuit
        with pytest.raises(ValueError):
            await breaker.call(fail)
        assert breaker._state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_circuit_blocks_calls(self):
        """Test that open circuit blocks calls."""
        breaker = CircuitBreaker(name="test", failure_threshold=1)

        async def fail():
            raise ValueError("test error")

        # Open the circuit
        with pytest.raises(ValueError):
            await breaker.call(fail)

        # Subsequent calls should be blocked
        with pytest.raises(CircuitOpenError):
            await breaker.call(fail)

    @pytest.mark.asyncio
    async def test_circuit_resets_on_success(self):
        """Test that successful call resets failure count."""
        breaker = CircuitBreaker(name="test", failure_threshold=3)

        async def fail():
            raise ValueError("test error")

        async def success():
            return "ok"

        # Add some failures
        with pytest.raises(ValueError):
            await breaker.call(fail)
        with pytest.raises(ValueError):
            await breaker.call(fail)

        # Successful call should reset
        await breaker.call(success)
        assert breaker._failure_count == 0

    @pytest.mark.asyncio
    async def test_half_open_state(self):
        """Test half-open state after timeout."""
        breaker = CircuitBreaker(
            name="test",
            failure_threshold=1,
            reset_timeout_seconds=0,  # Immediate timeout for testing
        )

        async def fail():
            raise ValueError("test error")

        # Open the circuit
        with pytest.raises(ValueError):
            await breaker.call(fail)

        # After timeout, should be half-open
        assert breaker.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_sync_function_call(self):
        """Test calling sync function through circuit breaker."""
        breaker = CircuitBreaker(name="test", failure_threshold=3)

        def sync_success():
            return "sync ok"

        result = await breaker.call(sync_success)
        assert result == "sync ok"

    def test_manual_reset(self):
        """Test manual reset of circuit breaker."""
        breaker = CircuitBreaker(name="test", failure_threshold=1)
        breaker._state = CircuitState.OPEN
        breaker._failure_count = 5

        breaker.reset()

        assert breaker._state == CircuitState.CLOSED
        assert breaker._failure_count == 0


class TestRetryDecorators:
    """Tests for retry decorators."""

    @pytest.mark.asyncio
    async def test_with_retry_success(self):
        """Test retry decorator with successful call."""

        @with_retry(max_attempts=3, min_wait=0.01, max_wait=0.02)
        async def success():
            return "ok"

        result = await success()
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_with_retry_eventual_success(self):
        """Test retry decorator with eventual success."""
        call_count = 0

        @with_retry(max_attempts=3, min_wait=0.01, max_wait=0.02, retry_exceptions=(ValueError,))
        async def eventual_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "ok"

        result = await eventual_success()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_with_retry_all_fail(self):
        """Test retry decorator when all attempts fail."""
        call_count = 0

        @with_retry(max_attempts=3, min_wait=0.01, max_wait=0.02, retry_exceptions=(ValueError,))
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("always fails")

        with pytest.raises(ValueError):
            await always_fail()

        assert call_count == 3

    @pytest.mark.asyncio
    async def test_with_retry_non_retryable_exception(self):
        """Test retry decorator doesn't retry non-retryable exceptions."""
        call_count = 0

        @with_retry(max_attempts=3, min_wait=0.01, max_wait=0.02, retry_exceptions=(ValueError,))
        async def wrong_exception():
            nonlocal call_count
            call_count += 1
            raise TypeError("not retryable")

        with pytest.raises(TypeError):
            await wrong_exception()

        assert call_count == 1  # Only one attempt

    def test_with_sync_retry_success(self):
        """Test sync retry decorator with successful call."""

        @with_sync_retry(max_attempts=3, min_wait=0.01, max_wait=0.02)
        def success():
            return "ok"

        result = success()
        assert result == "ok"

    def test_with_sync_retry_eventual_success(self):
        """Test sync retry decorator with eventual success."""
        call_count = 0

        @with_sync_retry(max_attempts=3, min_wait=0.01, max_wait=0.02, retry_exceptions=(ValueError,))
        def eventual_success():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("not yet")
            return "ok"

        result = eventual_success()
        assert result == "ok"
        assert call_count == 2


class TestRateLimiter:
    """Tests for RateLimiter class."""

    @pytest.mark.asyncio
    async def test_acquire_immediate(self):
        """Test acquiring tokens when available."""
        limiter = RateLimiter(tokens_per_second=10, max_tokens=10)

        start = time.time()
        await limiter.acquire(1)
        elapsed = time.time() - start

        # Should be nearly instant
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_acquire_multiple(self):
        """Test acquiring multiple tokens."""
        limiter = RateLimiter(tokens_per_second=100, max_tokens=10)

        # Acquire several tokens quickly
        for _ in range(5):
            await limiter.acquire(1)

        # Should still have tokens
        assert limiter._tokens > 0

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test using rate limiter as context manager."""
        limiter = RateLimiter(tokens_per_second=10, max_tokens=10)

        async with limiter:
            pass  # Token acquired

        # Should have fewer tokens after acquisition
        assert limiter._tokens < 10


class TestWithTimeout:
    """Tests for timeout helper."""

    @pytest.mark.asyncio
    async def test_timeout_success(self):
        """Test successful completion within timeout."""

        async def quick():
            return "quick"

        result = await with_timeout(quick(), timeout_seconds=1)
        assert result == "quick"

    @pytest.mark.asyncio
    async def test_timeout_exceeded(self):
        """Test timeout when operation takes too long."""

        async def slow():
            await asyncio.sleep(1)
            return "slow"

        with pytest.raises(LLMTimeoutError) as exc_info:
            await with_timeout(slow(), timeout_seconds=0.1)

        assert "timeout" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_timeout_custom_message(self):
        """Test timeout with custom error message."""

        async def slow():
            await asyncio.sleep(1)

        with pytest.raises(LLMTimeoutError) as exc_info:
            await with_timeout(slow(), timeout_seconds=0.1, error_message="Custom timeout")

        assert "Custom timeout" in str(exc_info.value)


class TestLLMExceptions:
    """Tests for LLM-specific exceptions."""

    def test_llm_rate_limit_error(self):
        """Test LLMRateLimitError exception."""
        error = LLMRateLimitError("Rate limit exceeded")
        assert str(error) == "Rate limit exceeded"

    def test_llm_timeout_error(self):
        """Test LLMTimeoutError exception."""
        error = LLMTimeoutError("Request timed out")
        assert str(error) == "Request timed out"
