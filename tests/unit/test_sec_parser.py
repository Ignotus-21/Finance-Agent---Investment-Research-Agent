"""
Unit tests for SEC EDGAR MCP Client and Statement Parsing.
"""

import pytest

from src.core.exceptions import FilingNotFoundException
from src.tools.sec_edgar_mcp import SECFilingClient


@pytest.mark.asyncio
async def test_sec_filing_client_income_statement():
    """Verify parsing of Consolidated Statements of Operations.

    The expected values come from Apple's FY2024 10-K as recorded by
    ``scripts/build_offline_fixtures.py``. They previously asserted accession
    ``0000320193-24-000106``, which is not the accession of that filing - the
    hand-written fixture these tests were pinned to had it wrong, so the test
    passed while describing a document that does not exist.
    """
    client = SECFilingClient()
    res = await client.fetch_filing_section("AAPL", "10-K", 2024, "INCOME_STATEMENT")
    assert res["ticker"] == "AAPL"
    assert res["form"] == "10-K"
    assert res["fiscal_year"] == 2024
    assert res["accession_number"] == "0000320193-24-000123"
    data = res["data"]
    assert data["revenue_current"] == 391035000000.0
    assert data["operating_income_current"] == 123216000000.0


@pytest.mark.asyncio
async def test_sec_filing_client_balance_sheet():
    """Verify parsing of Balance Sheets.

    `total_debt` carries the `LongTermDebtNoncurrent` tag - $85.75bn - not
    Apple's $106.6bn of total borrowings, which is why the metric built from
    it is labelled "Long-Term Debt-to-Equity". Equity is $56.95bn; the old
    fixture claimed $66.8bn.
    """
    client = SECFilingClient()
    res = await client.fetch_filing_section("AAPL", "10-K", 2024, "BALANCE_SHEET")
    data = res["data"]
    assert data["total_debt"] == 85750000000.0
    assert data["shareholders_equity"] == 56950000000.0


@pytest.mark.asyncio
async def test_sec_filing_client_invalid_ticker():
    """Verify error raised on invalid non-alphabetic ticker."""
    client = SECFilingClient()
    with pytest.raises(FilingNotFoundException):
        await client.fetch_filing_section("INVALID!@#", "10-K", 2024, "INCOME_STATEMENT")
