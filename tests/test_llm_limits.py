"""Tests for token budget circuit breaker and rate limiter."""

from __future__ import annotations

import asyncio
import time

import pytest

from sap_doc_agent.llm.limits import ProviderRateLimiter, TokenBudgetCircuitBreaker


# ---------------------------------------------------------------------------
# TokenBudgetCircuitBreaker
# ---------------------------------------------------------------------------


def test_circuit_breaker_starts_closed():
    cb = TokenBudgetCircuitBreaker(budget_per_hour=1000)
    assert cb.is_open() is False


def test_circuit_breaker_no_budget_never_opens():
    cb = TokenBudgetCircuitBreaker(budget_per_hour=None)
    cb.record_tokens(999_999)
    assert cb.is_open() is False


def test_circuit_breaker_open():
    """Recording tokens over budget should open the circuit."""
    cb = TokenBudgetCircuitBreaker(budget_per_hour=100)
    cb.record_tokens(50)
    assert cb.is_open() is False
    cb.record_tokens(51)
    assert cb.is_open() is True


def test_circuit_breaker_exactly_at_budget():
    """Exactly at budget should also open (>=)."""
    cb = TokenBudgetCircuitBreaker(budget_per_hour=100)
    cb.record_tokens(100)
    assert cb.is_open() is True


def test_circuit_breaker_reset():
    """After 1 hour has passed, old records are evicted and circuit closes."""
    cb = TokenBudgetCircuitBreaker(budget_per_hour=100)

    # Record tokens at a fake "old" time (more than 3600s ago)
    old_time = time.monotonic() - 3601
    cb._records.append((old_time, 200))

    # Circuit should see 200 tokens recorded, but they're old → evicted on check
    assert cb.is_open() is False


def test_circuit_breaker_partial_window():
    """Only tokens within the rolling window count."""
    cb = TokenBudgetCircuitBreaker(budget_per_hour=100)

    # Old token — outside window
    cb._records.append((time.monotonic() - 3601, 80))
    # Recent token — inside window
    cb.record_tokens(30)

    # Only 30 in window, budget is 100 → closed
    assert cb.is_open() is False

    # Push over budget with another recent token
    cb.record_tokens(75)
    assert cb.is_open() is True


# ---------------------------------------------------------------------------
# ProviderRateLimiter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_allows_concurrent_up_to_limit():
    limiter = ProviderRateLimiter(max_concurrent=2)
    results: list[str] = []

    async def task(name: str) -> None:
        async with limiter:
            await asyncio.sleep(0.01)
            results.append(name)

    await asyncio.gather(task("a"), task("b"))
    assert sorted(results) == ["a", "b"]


@pytest.mark.asyncio
async def test_rate_limiter_semaphore():
    """max_concurrent=1 should block the second coroutine until the first releases."""
    limiter = ProviderRateLimiter(max_concurrent=1)
    order: list[int] = []

    async def task(n: int, delay: float) -> None:
        async with limiter:
            order.append(n)
            await asyncio.sleep(delay)

    # Run task 1 (slow) and task 2 (fast) concurrently with semaphore=1
    # Task 1 acquires first (started first), task 2 must wait
    await asyncio.gather(task(1, 0.05), task(2, 0.0))

    # Both must complete
    assert len(order) == 2
    # With max_concurrent=1, they run sequentially — verify that
    assert order == [1, 2]


@pytest.mark.asyncio
async def test_rate_limiter_releases_on_exception():
    """Semaphore should be released even if the body raises."""
    limiter = ProviderRateLimiter(max_concurrent=1)

    with pytest.raises(ValueError):
        async with limiter:
            raise ValueError("test error")

    # After exception, semaphore should be released — a second acquire must succeed
    acquired = False
    async with limiter:
        acquired = True
    assert acquired
