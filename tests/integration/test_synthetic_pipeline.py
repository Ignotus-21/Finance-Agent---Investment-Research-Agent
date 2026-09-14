"""
Integration test for Synthetic Financial Data Pipeline.
Validates end-to-end multi-agent research generation on un-cached synthetic corporate entities.
"""

import pytest
from src.core.container import ApplicationContainer
from src.models.request import EquityResearchRequest
from src.guardrails.input_guardrail import InputGuardrail
from src.agents.adk_agent import create_financial_adk_agent, fetch_sec_filing_section, compute_financial_ratios


@pytest.mark.asyncio
async def test_synthetic_equity_research_pipeline():
    """Verify end-to-end multi-agent pipeline on synthetic entity 'SYNTH'."""
    # 1. Input Guardrail & DLP sanitization
    guardrail = InputGuardrail()
    sanitized = guardrail.inspect_and_sanitize("Perform equity research for SYNTH FY2024. Contact: test@hedgefund.com")
    assert "[REDACTED_EMAIL]" in sanitized

    # 2. Pipeline Execution
    container = ApplicationContainer()
    coordinator = container.root_coordinator

    req = EquityResearchRequest(
        ticker="SYNTH",
        fiscal_year=2024,
        focus_areas=["Margin_Expansion", "Supply_Chain"]
    )

    brief = await coordinator.execute_research(req)

    # 3. Assert Output Conformance
    assert brief.ticker == "SYNTH"
    assert brief.fiscal_year == 2024
    assert len(brief.executive_summary) > 50
    assert len(brief.key_financial_metrics) >= 4
    assert len(brief.citations) >= 4
    assert all(c.confidence_score == 1.0 for c in brief.citations)

    # 4. Assert Deterministic Financial Verification
    growth = next(m for m in brief.key_financial_metrics if "growth" in m.name)
    assert growth.provenance_verified is True
    assert growth.value == 11.11

    # 5. Assert ADK Agent tools
    adk_agent = create_financial_adk_agent()
    assert len(adk_agent.tools) == 5
    sec_data = fetch_sec_filing_section(ticker="SYNTH", fiscal_year=2024, section="Item 7")
    assert "SYNTH" in sec_data
