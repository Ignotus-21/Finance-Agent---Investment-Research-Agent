"""
Chaos & Failure Injection Tests: Vertex AI 503 Transient Failure Simulation.
Tests retry policies and exponential backoff resilience.
"""

import asyncio

import pytest


class TransientFailureService:
    def __init__(self, failure_count_before_success: int = 2):
        self.attempts = 0
        self.failure_threshold = failure_count_before_success

    async def call_with_retry(self) -> str:
        max_retries = 4
        backoff = 0.05

        for _attempt in range(max_retries):
            self.attempts += 1
            if self.attempts <= self.failure_threshold:
                await asyncio.sleep(backoff)
                backoff *= 2
                continue  # Transient 503 error
            return "SUCCESS_AFTER_RETRY"

        raise RuntimeError("Service unavailable after retries")


@pytest.mark.asyncio
async def test_transient_error_recovers_with_backoff():
    """Verify service recovers gracefully from simulated 503 transient errors."""
    service = TransientFailureService(failure_count_before_success=2)
    result = await service.call_with_retry()
    assert result == "SUCCESS_AFTER_RETRY"
    assert service.attempts == 3
