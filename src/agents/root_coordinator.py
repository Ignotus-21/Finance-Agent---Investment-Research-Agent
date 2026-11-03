"""
Root Coordinator Agent for the REST Research Pipeline.
Dispatches concurrent SEC, Transcript, and Macro sub-agents via asyncio.gather
under per-agent deadlines, executes deterministic financial ratio verification
via FinancialCalculator, and compiles the schema-validated ResearchBriefResponse.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable
from typing import Any

from src.agents.macro_agent import MacroSubAgent
from src.agents.sec_agent import SECSubAgent
from src.agents.transcript_agent import TranscriptSubAgent
from src.config import Settings
from src.core.exceptions import UpstreamTimeoutException
from src.core.interfaces import BaseAgent
from src.engine.synthesis_engine import SynthesisEngine
from src.models.request import EquityResearchRequest
from src.models.response import ResearchBriefResponse
from src.tools.financial_calculator import FinancialCalculator

logger = logging.getLogger(__name__)


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

    async def _with_deadline(
        self,
        agent: str,
        coro: Awaitable[dict[str, Any]],
        fallback: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """
        Run a sub-agent task under the configured deadline.

        Optional evidence (transcript, macro) degrades to `fallback`; required
        evidence (SEC filings) raises UpstreamTimeoutException (HTTP 504).
        """
        timeout = self.settings.subagent_timeout_seconds
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError as exc:
            logger.warning(
                "Sub-agent exceeded deadline.",
                extra={"event": "subagent_timeout", "agent": agent, "timeout_seconds": timeout},
            )
            if fallback is None:
                raise UpstreamTimeoutException(agent=agent, timeout_seconds=timeout) from exc
            return {**fallback, "extraction_status": "TIMEOUT"}

    async def execute_research(self, request: EquityResearchRequest) -> ResearchBriefResponse:
        """Executes the end-to-end multi-agent equity research synthesis workflow."""
        start_time = time.monotonic()
        quarter = f"Q4_{request.fiscal_year}"

        # Step 1: Concurrent Multi-Agent Dispatch (asyncio.gather) under per-agent deadlines
        sec_task = self._with_deadline(
            "sec_filing_specialist",
            self.sec_agent.extract_filing_data(
                ticker=request.ticker,
                fiscal_year=request.fiscal_year,
                focus_areas=request.focus_areas,
            ),
            fallback=None,
        )
        transcript_task = self._with_deadline(
            "earnings_transcript_specialist",
            self.transcript_agent.extract_transcript_insights(
                ticker=request.ticker,
                quarter=quarter,
                focus_areas=request.focus_areas,
            ),
            fallback={
                "agent": "earnings_transcript_specialist",
                "ticker": request.ticker.upper(),
                "quarter": quarter,
                "cfo_guidance": [],
                "ceo_strategy": [],
                "analyst_qa": [],
                "all_remarks": [],
            },
        )

        if request.include_macro_context:
            macro_task = self._with_deadline(
                "macro_news_specialist",
                self.macro_agent.gather_macro_context(
                    ticker=request.ticker,
                    focus_areas=request.focus_areas,
                ),
                fallback={
                    "agent": "macro_news_specialist",
                    "grounded_news": [],
                    "interest_rate_backdrop": "N/A",
                },
            )
            sec_data, transcript_data, macro_data = await asyncio.gather(
                sec_task, transcript_task, macro_task
            )
        else:
            sec_data, transcript_data = await asyncio.gather(sec_task, transcript_task)
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
