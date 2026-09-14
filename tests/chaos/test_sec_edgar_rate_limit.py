"""
Chaos & Failure Injection Tests: Upstream SEC EDGAR 429 Rate Limiting.
Simulates rapid bursts of queries and asserts token bucket rate limiting enforces the <= 8 req/s ceiling.
"""

import pytest
import time
import asyncio
from src.tools.sec_edgar_mcp import TokenBucketRateLimiter


@pytest.mark.asyncio
async def test_token_bucket_enforces_rate_limit():
    """Verify that rapid concurrent requests are smoothed and rate limited."""
    # Configure 4 req/sec limiter
    limiter = TokenBucketRateLimiter(rate=4.0, capacity=4.0)

    start = time.monotonic()
    # Execute 8 rapid acquisitions with capacity 4 (requires at least 4 token refills at 0.25s = 1.0s nominal)
    for _ in range(8):
        await limiter.acquire()
    elapsed = time.monotonic() - start

    assert elapsed >= 0.45
