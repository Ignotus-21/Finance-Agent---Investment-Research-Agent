"""Tests for per-sub-agent deadlines in the REST root coordinator."""

import asyncio

import pytest

from src.agents.root_coordinator import RootCoordinatorAgent
from src.config import Settings
from src.core.container import ApplicationContainer
from src.core.exceptions import UpstreamTimeoutException
from src.models.request import EquityResearchRequest


def _request() -> EquityResearchRequest:
    return EquityResearchRequest(
        ticker="AAPL", fiscal_year=2024, focus_areas=["Margins"], include_macro_context=True
    )


def _coordinator(settings: Settings) -> tuple[ApplicationContainer, RootCoordinatorAgent]:
    container = ApplicationContainer(settings=settings)
    coordinator = RootCoordinatorAgent(
        sec_agent=container.sec_agent,
        transcript_agent=container.transcript_agent,
        macro_agent=container.macro_agent,
        calculator=container.calculator,
        synthesis_engine=container.synthesis_engine,
        settings=settings,
    )
    return container, coordinator


@pytest.mark.asyncio
async def test_optional_sub_agents_degrade_gracefully_on_timeout() -> None:
    settings = Settings(subagent_timeout_seconds=0.05)
    container, coordinator = _coordinator(settings)

    async def slow_transcript(*_: object, **__: object) -> dict:
        await asyncio.sleep(1)
        return {}

    async def slow_macro(*_: object, **__: object) -> dict:
        await asyncio.sleep(1)
        return {}

    container.transcript_agent.extract_transcript_insights = slow_transcript  # type: ignore[method-assign]
    container.macro_agent.gather_macro_context = slow_macro  # type: ignore[method-assign]

    brief = await coordinator.execute_research(_request())

    assert brief.ticker == "AAPL"
    assert len(brief.key_financial_metrics) > 0
    assert "No earnings call transcript" in brief.qualitative_synthesis.executive_commentary_analysis
    assert all(c.source_type != "TRANSCRIPT_REMARKS" for c in brief.citations)


@pytest.mark.asyncio
async def test_required_sec_sub_agent_timeout_raises_504() -> None:
    settings = Settings(subagent_timeout_seconds=0.05)
    container, coordinator = _coordinator(settings)

    async def slow_sec(*_: object, **__: object) -> dict:
        await asyncio.sleep(1)
        return {}

    container.sec_agent.extract_filing_data = slow_sec  # type: ignore[method-assign]

    with pytest.raises(UpstreamTimeoutException) as excinfo:
        await coordinator.execute_research(_request())

    assert excinfo.value.status_code == 504
    assert excinfo.value.details["agent"] == "sec_filing_specialist"


@pytest.mark.asyncio
async def test_fast_sub_agents_are_unaffected_by_the_deadline() -> None:
    settings = Settings(subagent_timeout_seconds=10)
    _, coordinator = _coordinator(settings)

    brief = await coordinator.execute_research(_request())

    assert brief.key_financial_metrics
    assert any(c.source_type == "TRANSCRIPT_REMARKS" for c in brief.citations)
