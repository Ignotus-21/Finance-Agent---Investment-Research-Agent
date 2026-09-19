"""
Root Coordinator Agent.

The central orchestrator of the deterministic research pipeline. Dispatches
the SEC, transcript and macro sub-agents concurrently, runs the deterministic
calculator over what they return, and drives brief synthesis.

No model is called anywhere on this path. That is deliberate - it is what
makes the REST endpoint reproducible, fast and free - but it does mean this
class is an orchestrator, not a reasoner. The agentic Plan-and-Execute loop
lives in :mod:`src.agents.adk_agent`, where a Gemini coordinator really does
plan and delegate.

This docstring used to claim "a Plan-and-Execute reasoning loop with explicit
thought budgeting". The corresponding code was a ``_formulate_execution_plan``
method that returned a hardcoded five-element list, whose result was assigned
to ``_`` and discarded, with a ``thought_budget_allocated`` field nothing read.
It has been removed rather than described more carefully.
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
    Central orchestrator.
    Manages concurrent delegation, state aggregation, and synthesis.
    """

    def __init__(
        self,
        sec_agent: SECSubAgent,
        transcript_agent: TranscriptSubAgent,
        macro_agent: MacroSubAgent,
        calculator: FinancialCalculator,
        synthesis_engine: SynthesisEngine,

        settings: Settings | None = None
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
        """
        Executes end-to-end research synthesis workflow in under 60 seconds.
        """
        start_time = time.monotonic()

        # Concurrent Multi-Agent Dispatch (asyncio.gather)
        #
        # There used to be a context-cache check here. It consulted an
        # in-process dict, reported a `cache_id` naming a Vertex resource that
        # was never created, and passed a `cache_hit` boolean into the synthesis
        # engine that selected between two hardcoded cost figures. None of the
        # three sub-agents below calls a model, so there was no context to
        # cache. Real caching lives in the ADK path, configured on the App.
        sec_coro = self.sec_agent.extract_filing_data(
            ticker=request.ticker,
            fiscal_year=request.fiscal_year,
            focus_areas=request.focus_areas
        )
        transcript_coro = self.transcript_agent.extract_transcript_insights(
            ticker=request.ticker,
            quarter=f"Q4_{request.fiscal_year}",
            focus_areas=request.focus_areas
        )

        if request.include_macro_context:
            macro_coro = self.macro_agent.gather_macro_context(
                ticker=request.ticker,
                focus_areas=request.focus_areas
            )
            sec_data, transcript_data, macro_data = await asyncio.gather(
                sec_coro, transcript_coro, macro_coro
            )
        else:
            sec_data, transcript_data = await asyncio.gather(sec_coro, transcript_coro)
            macro_data = {"agent": "macro_news_specialist", "grounded_news": [], "interest_rate_backdrop": "N/A"}

        # Step 4: Deterministic Financial Ratio Calculation (Zero arithmetic hallucination)
        verified_metrics = self.calculator.compute_all_metrics(sec_data)

        # Step 5: Multi-Source Synthesis and Provenance Cross-Verification
        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        brief = await self.synthesis_engine.synthesize_brief(
            request=request,
            sec_data=sec_data,
            transcript_data=transcript_data,
            macro_data=macro_data,
            verified_metrics=verified_metrics,
            latency_ms=elapsed_ms
        )

        return brief
