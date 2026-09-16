"""
Integration tests for Structured Audit Logging and Pub/Sub Event Broadcasting.
"""

import pytest

from src.observability.audit_logger import AuditLogger
from src.observability.pubsub_broadcaster import PubSubBroadcaster


@pytest.mark.asyncio
async def test_audit_logger_creates_valid_record():
    """Verify structured audit log record creation."""
    logger = AuditLogger()
    record = await logger.log_research_execution(
        ticker="MSFT",
        fiscal_year=2024,
        prompt="Analyze Microsoft Cloud revenues",
        user_id="analyst-123",
        tools_called=["fetch_sec_filing_section", "financial_calculator"],
        latency_ms=25000,
        total_tokens=18000,
        cost_usd=0.142,
        guardrail_verdict="PASS",
        citations_count=6
    )

    assert record.ticker == "MSFT"
    assert record.user_id == "analyst-123"
    assert record.cost_usd == 0.142
    assert len(logger.audit_records) == 1
    assert logger.audit_records[0]["prompt_hash"] is not None


@pytest.mark.asyncio
async def test_pubsub_broadcaster_event_emission():
    """Verify asynchronous Pub/Sub event format."""
    broadcaster = PubSubBroadcaster()
    event = await broadcaster.broadcast_brief_completed(
        brief_id="brief-test-123",
        ticker="NVDA",
        fiscal_year=2024,
        metrics_count=5,
        citations_count=8,
        risk_categories=["Supply Chain", "Geopolitical"]
    )

    assert event["event_type"] == "research.brief.completed"
    assert event["payload"]["ticker"] == "NVDA"
    assert len(broadcaster.published_events) == 1
