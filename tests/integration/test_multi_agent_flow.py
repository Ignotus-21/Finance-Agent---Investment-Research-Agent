"""
Integration tests for End-to-End Multi-Agent Orchestration Flow.
Asserts Root Coordinator planning, concurrent sub-agent dispatch, deterministic calculation,
and synthesis with 100% line-item citation provenance.
"""

import pytest
from src.core.container import ApplicationContainer
from src.models.request import EquityResearchRequest


@pytest.mark.asyncio
async def test_end_to_end_research_synthesis():
    """Verify full multi-agent pipeline for Apple (AAPL FY2024)."""
    container = ApplicationContainer()
    coordinator = container.root_coordinator

    request = EquityResearchRequest(
        ticker="AAPL",
        fiscal_year=2024,
        focus_areas=["Services_Margin", "China_Headwinds"]
    )

    brief = await coordinator.execute_research(request)

    # 1. Assert Structured Output conformance
    assert brief.ticker == "AAPL"
    assert brief.fiscal_year == 2024
    assert len(brief.executive_summary) > 50
    assert len(brief.key_financial_metrics) >= 4

    # 2. Assert Line-Item Citation Provenance
    assert len(brief.citations) >= 4
    for cite in brief.citations:
        assert cite.confidence_score == 1.0
        assert cite.source_type in [
            "SEC_FORM_10K", "TRANSCRIPT_REMARKS", "TRANSCRIPT_QA", "MACRO_NEWS"
        ]

    # 3. Assert Deterministic Financial Verification
    growth = next(m for m in brief.key_financial_metrics if "growth" in m.name)
    assert growth.value == 2.02
    assert growth.provenance_verified is True

    # 4. Assert Operational Metadata & Gemini Context Caching
    assert brief.metadata.latency_ms > 0

    # Execute subsequent query for same ticker to assert Gemini Context Caching hit & <= $0.25 SLA
    brief_cached = await coordinator.execute_research(request)
    assert brief_cached.metadata.context_cache_hit is True
    assert brief_cached.metadata.estimated_cost_usd <= 0.25
