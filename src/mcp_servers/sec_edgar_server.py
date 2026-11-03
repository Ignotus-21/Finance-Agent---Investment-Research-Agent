"""
SEC EDGAR Model Context Protocol (MCP) Server.
Exposes `fetch_sec_filing_section` and `extract_xbrl_financial_facts` over
JSON-RPC stdio transport (`python -m src.mcp_servers.sec_edgar_server`)
backed by `SECFilingClient` with token-bucket rate limiting and circuit breaking.
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.mcpserver import MCPServer

from src.config import Settings
from src.core.exceptions import FinancialAgentException
from src.tools.sec_edgar_mcp import SECFilingClient

server: MCPServer = MCPServer(
    name="sec-edgar",
    version="1.0.0",
    instructions=(
        "Primary-source SEC EDGAR retrieval. Every figure returned originates "
        "from a filed 10-K/10-Q and carries an accession number for citation. "
        "Check the data_source field before citing: only SEC_EDGAR_LIVE and "
        "OFFLINE_FIXTURE values are backed by real filings."
    ),
)

_settings = Settings()
_client = SECFilingClient(_settings)


@server.tool(
    name="fetch_sec_filing_section",
    description=(
        "Retrieve one section of an SEC filing. Sections: INCOME_STATEMENT, "
        "BALANCE_SHEET, CASH_FLOW, MDA_ITEM_7. Returns the section data plus "
        "accession number, filing date and a data_source provenance label."
    ),
)
async def fetch_sec_filing_section(
    ticker: str,
    form: str = "10-K",
    fiscal_year: int = 2024,
    section: str = "INCOME_STATEMENT",
) -> dict[str, Any]:
    """Fetch a filing section from SEC EDGAR."""
    try:
        return await _client.fetch_filing_section(
            ticker=ticker, form=form, fiscal_year=fiscal_year, section=section
        )
    except FinancialAgentException as exc:
        return {
            "error": exc.error_code,
            "message": exc.message,
            "ticker": ticker,
            "form": form,
            "fiscal_year": fiscal_year,
        }


@server.tool(
    name="extract_xbrl_financial_facts",
    description=(
        "Retrieve the income statement, balance sheet and cash flow statement "
        "for one fiscal year in a single call. Prefer this over three separate "
        "fetch_sec_filing_section calls - it is one round trip and the three "
        "statements are guaranteed to come from the same filing."
    ),
)
async def extract_xbrl_financial_facts(
    ticker: str,
    fiscal_year: int = 2024,
    form: str = "10-K",
) -> dict[str, Any]:
    """Fetch all three primary financial statements concurrently."""
    sections = ("INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW")

    results = await asyncio.gather(
        *(
            _client.fetch_filing_section(
                ticker=ticker, form=form, fiscal_year=fiscal_year, section=section
            )
            for section in sections
        ),
        return_exceptions=True,
    )

    statements: dict[str, Any] = {}
    provenance: dict[str, Any] = {}

    for section, result in zip(sections, results, strict=True):
        if isinstance(result, BaseException):
            statements[section] = {"error": str(result)}
            continue
        statements[section] = result["data"]
        provenance = {
            "accession_number": result["accession_number"],
            "filing_date": result["filing_date"],
            "company_name": result["company_name"],
            "data_source": result["data_source"],
        }

    return {
        "ticker": ticker.upper(),
        "fiscal_year": fiscal_year,
        "form": form.upper(),
        "statements": statements,
        **provenance,
    }


def main() -> None:
    """Serve the SEC EDGAR MCP server over stdio."""
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":
    main()
