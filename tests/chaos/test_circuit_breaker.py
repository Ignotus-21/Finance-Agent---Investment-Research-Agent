"""
Chaos & Failure Injection Tests: Circuit Breaker Fallback and Graceful Degradation.
Asserts that when consecutive failures trip the breaker to OPEN,
the system gracefully serves cached historical filings without dropping queries.
"""

import pytest
from src.tools.sec_edgar_mcp import SECFilingClient, CircuitBreaker


def test_circuit_breaker_state_transitions():
    """Verify state transitions: CLOSED -> OPEN on 5 failures."""
    cb = CircuitBreaker(failure_threshold=5, recovery_timeout=0.1)
    assert cb.state == "CLOSED"
    assert cb.is_available() is True

    for _ in range(4):
        cb.record_failure()
        assert cb.state == "CLOSED"

    cb.record_failure()
    assert cb.state == "OPEN"
    assert cb.is_available() is False


@pytest.mark.asyncio
async def test_circuit_breaker_falls_back_to_cached_filing():
    """Verify SEC client falls back to cached snapshot when circuit breaker is open."""
    client = SECFilingClient()
    # Trip circuit breaker artificially
    for _ in range(5):
        client.circuit_breaker.record_failure()

    assert client.circuit_breaker.state == "OPEN"

    # Request should NOT fail; must return cached fallback
    res = await client.fetch_filing_section("AAPL", "10-K", 2024, "INCOME_STATEMENT")
    assert res["source_status"] == "CACHED_FALLBACK_CIRCUIT_BREAKER_ACTIVE"
    assert res["ticker"] == "AAPL"
    assert res["data"]["revenue_current"] == 391035000000.0
