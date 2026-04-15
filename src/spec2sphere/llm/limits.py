"""Token budget and rate limiting for LLM providers."""

from __future__ import annotations

import asyncio
import time
from typing import Optional


class TokenBudgetCircuitBreaker:
    """Tracks tokens spent in a rolling 1-hour window.

    Opens the circuit (blocks calls) when the accumulated token count
    reaches or exceeds the configured budget_per_hour.
    """

    _WINDOW_SECONDS = 3600  # 1 hour

    def __init__(self, budget_per_hour: Optional[int] = None) -> None:
        self._budget = budget_per_hour
        # List of (timestamp, tokens) tuples
        self._records: list[tuple[float, int]] = []

    def _evict_old_records(self) -> None:
        """Remove records older than the rolling window."""
        cutoff = time.monotonic() - self._WINDOW_SECONDS
        self._records = [(ts, tok) for ts, tok in self._records if ts >= cutoff]

    def record_tokens(self, tokens: int) -> None:
        """Record that ``tokens`` tokens were consumed right now."""
        self._evict_old_records()
        self._records.append((time.monotonic(), tokens))

    def is_open(self) -> bool:
        """Return True if the circuit is open (budget exceeded — block calls)."""
        if self._budget is None:
            return False
        self._evict_old_records()
        total = sum(tok for _, tok in self._records)
        return total >= self._budget


class ProviderRateLimiter:
    """Async semaphore wrapping provider calls to enforce max_concurrent."""

    def __init__(self, max_concurrent: int = 4) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def __aenter__(self) -> "ProviderRateLimiter":
        await self._semaphore.acquire()
        return self

    async def __aexit__(self, *_: object) -> None:
        self._semaphore.release()
