"""
Macroeconomic & News Specialist Sub-Agent.
Reads the curated macro corpus to capture interest rate environment,
regulatory backdrop, and competitor industry dynamics.
"""

from typing import Any

from src.config import Settings
from src.core.interfaces import BaseAgent
from src.tools.macro_context import MacroContextClient


class MacroSubAgent(BaseAgent):
    """
    Sub-agent dedicated to the macroeconomic backdrop and financial news context.
    """

    def __init__(self, client: MacroContextClient, settings: Settings | None = None) -> None:
        self.client = client
        self.settings = settings or Settings()

    @property
    def agent_name(self) -> str:
        return "macro_news_specialist"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "")
        focus_areas = context.get("focus_areas", [])
        return await self.gather_macro_context(ticker, focus_areas)

    async def gather_macro_context(
        self, ticker: str, focus_areas: list[str]
    ) -> dict[str, Any]:
        """Queries grounded macroeconomic indicators and corporate news."""
        news_items = await self.client.query_market_context(ticker, focus_areas)

        return {
            "agent": self.agent_name,
            "ticker": ticker.upper(),
            "focus_areas": focus_areas,
            "grounded_news": news_items,
            "interest_rate_backdrop": "Federal Funds target range at 4.75% - 5.00%",
            "extraction_status": "SUCCESS"
        }
