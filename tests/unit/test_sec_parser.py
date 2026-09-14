"""
Unit tests for SEC EDGAR MCP Client and Statement Parsing.
"""

import pytest
from src.tools.sec_edgar_mcp import SECFilingClient
from src.core.exceptions import FilingNotFoundException


@pytest.mark.asyncio
async def test_sec_filing_client_income_statement():
    """Verify parsing of Consolidated Statements of Operations."""
    client = SECFilingClient()
    res = await client.fetch_filing_section("AAPL", "10-K", 2024, "INCOME_STATEMENT")
    assert res["ticker"] == "AAPL"
    assert res["form"] == "10-K"
    assert res["fiscal_year"] == 2024
    assert res["accession_number"] == "0000320193-24-000106"
    data = res["data"]
    assert data["revenue_current"] == 391035000000.0
    assert data["operating_income_current"] == 123216000000.0


@pytest.mark.asyncio
async def test_sec_filing_client_balance_sheet():
    """Verify parsing of Balance Sheets."""
    client = SECFilingClient()
    res = await client.fetch_filing_section("AAPL", "10-K", 2024, "BALANCE_SHEET")
    data = res["data"]
    assert data["total_debt"] == 106629000000.0
    assert data["shareholders_equity"] == 66802000000.0


@pytest.mark.asyncio
async def test_sec_filing_client_invalid_ticker():
    """Verify error raised on invalid non-alphabetic ticker."""
    client = SECFilingClient()
    with pytest.raises(FilingNotFoundException):
        await client.fetch_filing_section("INVALID!@#", "10-K", 2024, "INCOME_STATEMENT")
