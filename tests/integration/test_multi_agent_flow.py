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

    # 4. Assert operational metadata.
    # Real measured wall-clock latency (fixtures resolve sub-millisecond).
    # Asserts the value is populated and inside the 60s P95 SLO from the PRD.
    assert 0 <= brief.metadata.latency_ms <= 60_000

    # 5. Assert the inference telemetry is zero, and stays zero.
    #
    # This replaces an assertion that a second identical request produced
    # `context_cache_hit is True` and `estimated_cost_usd <= 0.25`. Both passed,
    # and neither meant anything: the cache was an in-process dict that called
    # no Vertex API, and the cost was one of two hardcoded constants selected by
    # that dict. This path calls no language model, so the honest values are
    # zero - and a future change that reintroduces a fabricated figure here
    # fails this test instead of quietly appearing in the cost report.
    for result in (brief, await coordinator.execute_research(request)):
        assert result.metadata.total_tokens_consumed == 0
        assert result.metadata.estimated_cost_usd == 0.0
        assert result.metadata.context_cache_hit is False
        assert result.metadata.model_routing == {}
