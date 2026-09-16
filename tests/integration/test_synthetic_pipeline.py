"""
Integration test for Synthetic Financial Data Pipeline.
Validates end-to-end multi-agent research generation on un-cached synthetic corporate entities.
"""

import pytest
from google.adk.tools.mcp_tool import McpToolset

from src.agents.adk_agent import create_financial_adk_agent
from src.core.container import ApplicationContainer
from src.guardrails.input_guardrail import InputGuardrail
from src.models.request import EquityResearchRequest


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

    # 5. Assert ADK agent tool wiring: three native tools plus SEC over MCP.
    # The SEC call itself is exercised across a real protocol round trip in
    # tests/integration/test_mcp_sec_edgar_server.py, so repeating it here
    # would only re-test retrieval logic that is already covered.
    adk_agent = create_financial_adk_agent()
    assert len(adk_agent.tools) == 4
    assert sum(isinstance(t, McpToolset) for t in adk_agent.tools) == 1
