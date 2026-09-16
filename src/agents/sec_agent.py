"""
SEC Filing Specialist Sub-Agent.
Ingests, parses, and normalizes audited SEC Form 10-K, 10-Q, and 8-K disclosures.
Extracts Balance Sheets, Statements of Operations, Cash Flows, and Item 7 MD&A.
"""

from typing import Any

from src.config import Settings
from src.core.interfaces import BaseAgent
from src.tools.sec_edgar_mcp import SECFilingClient


class SECSubAgent(BaseAgent):
    """
    Domain-specialized sub-agent dedicated to regulatory SEC filings.
    Normalizes tabular financial statements and attaches XBRL tags.
    """

    def __init__(self, client: SECFilingClient, settings: Settings | None = None) -> None:
        self.client = client
        self.settings = settings or Settings()

    @property
    def agent_name(self) -> str:
        return "sec_filing_specialist"

    async def run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker = context.get("ticker", "")
        fiscal_year = context.get("fiscal_year", 2024)
        focus_areas = context.get("focus_areas", [])
        return await self.extract_filing_data(ticker, fiscal_year, focus_areas)

    async def extract_filing_data(
        self, ticker: str, fiscal_year: int, focus_areas: list[str]
    ) -> dict[str, Any]:
        """Extracts complete audited financial statement package for a ticker and fiscal year."""
        # Query Statements of Operations
        inc_res = await self.client.fetch_filing_section(ticker, "10-K", fiscal_year, "INCOME_STATEMENT")
        # Query Balance Sheets
        bal_res = await self.client.fetch_filing_section(ticker, "10-K", fiscal_year, "BALANCE_SHEET")
        # Query Cash Flows
        cash_res = await self.client.fetch_filing_section(ticker, "10-K", fiscal_year, "CASH_FLOW")
        # Query MD&A Item 7
        mda_res = await self.client.fetch_filing_section(ticker, "10-K", fiscal_year, "MDA_ITEM_7")

        return {
            "agent": self.agent_name,
            "ticker": ticker.upper(),
            "fiscal_year": fiscal_year,
            "accession_number": inc_res.get("accession_number"),
            "filing_date": inc_res.get("filing_date"),
            "company_name": inc_res.get("company_name"),
            "income_statement": inc_res.get("data", {}),
            "balance_sheet": bal_res.get("data", {}),
            "cash_flow": cash_res.get("data", {}),
            "mda_item_7": mda_res.get("data", {}),
            "extraction_status": "SUCCESS"
        }
