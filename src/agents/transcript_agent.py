"""
Earnings Call Transcript Specialist Sub-Agent.
Extracts and segments executive prepared remarks and analyst Q&A.
Isolates CFO forward margin guidance, CEO strategy, and pushback topics.
"""

from typing import Any

from src.config import Settings
from src.core.interfaces import BaseAgent
from src.tools.transcript_parser import TranscriptClient


class TranscriptSubAgent(BaseAgent):
    """
    Sub-agent dedicated to parsing and evaluating quarterly earnings transcripts.
    Attributes quotes to specific corporate roles (CEO, CFO) and analysts.
    """

    def __init__(self, client: TranscriptClient, settings: Settings | None = None) -> None:
        self.client = client
        self.settings = settings or Settings()

    @property
    def agent_name(self) -> str:
        return "earnings_transcript_specialist"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "")
        quarter = context.get("quarter", "Q4_2024")
        focus_areas = context.get("focus_areas", [])
        return await self.extract_transcript_insights(ticker, quarter, focus_areas)

    async def extract_transcript_insights(
        self, ticker: str, quarter: str, focus_areas: list[str]
    ) -> dict[str, Any]:
        """Extracts executive guidance and analyst Q&A from transcript repository."""
        transcript_payload = await self.client.get_transcript(ticker, quarter)

        # Filter guidance quotes from CFO/CEO
        cfo_quotes = [
            r for r in transcript_payload.get("prepared_remarks", [])
            if "Financial" in r.get("speaker_role", "") or "CFO" in r.get("speaker_role", "")
        ]

        ceo_quotes = [
            r for r in transcript_payload.get("prepared_remarks", [])
            if "Executive" in r.get("speaker_role", "") or "CEO" in r.get("speaker_role", "")
        ]

        return {
            "agent": self.agent_name,
            "ticker": ticker.upper(),
            "quarter": quarter.upper(),
            "event_date": transcript_payload.get("date"),
            "cfo_guidance": cfo_quotes,
            "ceo_strategy": ceo_quotes,
            "analyst_qa": transcript_payload.get("analyst_qa", []),
            "all_remarks": transcript_payload.get("prepared_remarks", []),
            "extraction_status": "SUCCESS"
        }
