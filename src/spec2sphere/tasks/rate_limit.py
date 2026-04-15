import time
import os

SAP_RATE_LIMIT_RPS = int(os.environ.get("SAP_RATE_LIMIT_RPS", "10"))


class SAPRateLimiter:
    """Redis-backed sliding window rate limiter per system_name."""

    PREFIX = "sapdoc:ratelimit:"

    def __init__(self, redis_client, rps: int = SAP_RATE_LIMIT_RPS):
        self._r = redis_client
        self._rps = rps

    def acquire(self, system_name: str) -> bool:
        """Returns True if request is allowed. Call before each SAP API request."""
        key = f"{self.PREFIX}{system_name}"
        now = time.time()
        window_start = now - 1.0  # 1-second window

        pipe = self._r.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zcard(key)
        pipe.zadd(key, {str(now): now})
        pipe.expire(key, 10)
        results = pipe.execute()

        count_before_add = results[1]
        return count_before_add < self._rps
