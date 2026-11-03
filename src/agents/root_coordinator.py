"""
Root Coordinator Agent for the REST Research Pipeline.
Dispatches concurrent SEC, Transcript, and Macro sub-agents via asyncio.gather,
executes deterministic financial ratio verification via FinancialCalculator,
and compiles the schema-validated ResearchBriefResponse.
"""

import asyncio
import time
from typing import Any

from src.agents.macro_agent import MacroSubAgent
from src.agents.sec_agent import SECSubAgent
from src.agents.transcript_agent import TranscriptSubAgent
from src.config import Settings
from src.core.interfaces import BaseAgent
from src.engine.synthesis_engine import SynthesisEngine
from src.models.request import EquityResearchRequest
from src.models.response import ResearchBriefResponse
from src.tools.financial_calculator import FinancialCalculator


class RootCoordinatorAgent(BaseAgent):
    """
    Central orchestrator managing concurrent sub-agent delegation,
    deterministic ratio verification, and multi-source brief synthesis.
    """

    def __init__(
        self,
        sec_agent: SECSubAgent,
        transcript_agent: TranscriptSubAgent,
        macro_agent: MacroSubAgent,
        calculator: FinancialCalculator,
        synthesis_engine: SynthesisEngine,
        settings: Settings | None = None,
    ) -> None:
        self.sec_agent = sec_agent
        self.transcript_agent = transcript_agent
        self.macro_agent = macro_agent
        self.calculator = calculator
        self.synthesis_engine = synthesis_engine
        self.settings = settings or Settings()

    @property
    def agent_name(self) -> str:
        return "root_coordinator_agent"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        req = EquityResearchRequest(**context)
        response = await self.execute_research(req)
        return response.model_dump()

    async def execute_research(self, request: EquityResearchRequest) -> ResearchBriefResponse:
        """Executes the end-to-end multi-agent equity research synthesis workflow."""
        start_time = time.monotonic()

        # Step 1: Concurrent Multi-Agent Dispatch (asyncio.gather)
        sec_coro = self.sec_agent.extract_filing_data(
            ticker=request.ticker,
            fiscal_year=request.fiscal_year,
            focus_areas=request.focus_areas,
        )
        transcript_coro = self.transcript_agent.extract_transcript_insights(
            ticker=request.ticker,
            quarter=f"Q4_{request.fiscal_year}",
            focus_areas=request.focus_areas,
        )

        if request.include_macro_context:
            macro_coro = self.macro_agent.gather_macro_context(
                ticker=request.ticker,
                focus_areas=request.focus_areas,
            )
            sec_data, transcript_data, macro_data = await asyncio.gather(
                sec_coro, transcript_coro, macro_coro
            )
        else:
            sec_data, transcript_data = await asyncio.gather(sec_coro, transcript_coro)
            macro_data = {
                "agent": "macro_news_specialist",
                "grounded_news": [],
                "interest_rate_backdrop": "N/A",
            }

        # Step 2: Deterministic Financial Ratio Calculation
        verified_metrics = self.calculator.compute_all_metrics(sec_data)

        # Step 3: Multi-Source Synthesis and Provenance Verification
        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        brief = await self.synthesis_engine.synthesize_brief(
            request=request,
            sec_data=sec_data,
            transcript_data=transcript_data,
            macro_data=macro_data,
            verified_metrics=verified_metrics,
            latency_ms=elapsed_ms,
        )

        return brief
