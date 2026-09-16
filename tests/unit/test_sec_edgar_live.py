"""Tests for the live SEC EDGAR ingestion path.

Every test drives the real code through ``httpx.MockTransport``, so the full
request-construction path is exercised (URLs, headers, JSON shape) without
touching the network. Nothing here hits sec.gov.
"""

import json

import httpx
import pytest

from src.config import Settings
from src.core.exceptions import FilingNotFoundException
from src.tools.sec_edgar_http import SECEdgarHTTPClient
from src.tools.sec_edgar_mcp import SECFilingClient

VALID_UA = "IRA Capstone Research analyst@example.com"

TICKER_FILE = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
}

SUBMISSIONS = {
    "name": "Apple Inc.",
    "filings": {
        "recent": {
            "form": ["10-Q", "10-K", "10-K"],
            "reportDate": ["2024-06-29", "2024-09-28", "2023-09-30"],
            "filingDate": ["2024-08-02", "2024-11-01", "2023-11-03"],
            "accessionNumber": [
                "0000320193-24-000081",
                "0000320193-24-000123",
                "0000320193-23-000106",
            ],
            "primaryDocument": ["aapl-q3.htm", "aapl-20240928.htm", "aapl-20230930.htm"],
        }
    },
}

COMPANY_FACTS = {
    "facts": {
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        # Quarterly figure - must be ignored.
                        {"fy": 2024, "fp": "Q3", "form": "10-Q", "val": 85777000000},
                        # Annual figure from the 10-K - the one we want.
                        {"fy": 2024, "fp": "FY", "form": "10-K", "val": 391035000000},
                        {"fy": 2023, "fp": "FY", "form": "10-K", "val": 383285000000},
                    ]
                }
            },
            "OperatingIncomeLoss": {
                "units": {
                    "USD": [
                        {"fy": 2024, "fp": "FY", "form": "10-K", "val": 123216000000},
                        {"fy": 2023, "fp": "FY", "form": "10-K", "val": 114301000000},
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {"USD": [{"fy": 2024, "fp": "FY", "form": "10-K", "val": 93736000000}]}
            },
            "StockholdersEquity": {
                "units": {"USD": [{"fy": 2024, "fp": "FY", "form": "10-K", "val": 56950000000}]}
            },
        }
    }
}

FILING_HTML = """
<html><body>
<p>Table of Contents</p>
<p>Item 7. Management's Discussion and Analysis of Financial Condition</p>
<p>Item 7A. Quantitative and Qualitative Disclosures</p>
<hr/>
<p>Item 7. Management's Discussion and Analysis of Financial Condition</p>
<p>Total net sales increased 2% during 2024 compared to 2023.</p>
<p>Item 7A. Quantitative and Qualitative Disclosures About Market Risk</p>
</body></html>
"""


def _handler(request: httpx.Request) -> httpx.Response:
    """Route mock responses by URL path."""
    url = str(request.url)

    # Assert the SEC User-Agent policy is honoured on every single request,
    # not just the first. A missing header here is an eventual IP ban.
    assert request.headers.get("User-Agent") == VALID_UA

    if "company_tickers.json" in url:
        return httpx.Response(200, json=TICKER_FILE)
    if "/submissions/" in url:
        return httpx.Response(200, json=SUBMISSIONS)
    if "companyfacts" in url:
        return httpx.Response(200, json=COMPANY_FACTS)
    if "/Archives/" in url:
        return httpx.Response(200, text=FILING_HTML)
    return httpx.Response(404, json={"error": "not found"})


def _mock_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


# ---------------------------------------------------------------------------
# SECEdgarHTTPClient
# ---------------------------------------------------------------------------


def test_rejects_noncompliant_user_agent() -> None:
    """SEC bans callers who do not identify themselves, so refuse to start."""
    with pytest.raises(ValueError, match="User-Agent"):
        SECEdgarHTTPClient(user_agent="python-httpx/0.28")


def test_accepts_compliant_user_agent() -> None:
    client = SECEdgarHTTPClient(user_agent=VALID_UA)
    assert client.user_agent == VALID_UA


async def test_resolve_cik_zero_pads_to_ten_digits() -> None:
    """EDGAR paths require the 10-digit zero-padded form."""
    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with _mock_client() as client:
        assert await edgar.resolve_cik("AAPL", client) == "0000320193"
        # Case-insensitive lookup.
        assert await edgar.resolve_cik("msft", client) == "0000789019"


async def test_resolve_cik_unknown_ticker_raises() -> None:
    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with _mock_client() as client:
        with pytest.raises(FilingNotFoundException):
            await edgar.resolve_cik("NOTAREALTICKER", client)


async def test_ticker_map_is_fetched_once() -> None:
    """The mapping changes on the order of days; refetching it per query would
    triple our request count against a rate-limited endpoint."""
    calls: list[str] = []

    def counting_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _handler(request)

    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with httpx.AsyncClient(transport=httpx.MockTransport(counting_handler)) as client:
        await edgar.resolve_cik("AAPL", client)
        await edgar.resolve_cik("MSFT", client)

    assert sum("company_tickers" in c for c in calls) == 1


async def test_find_filing_matches_on_report_period_not_filing_date() -> None:
    """FY2024's 10-K was *filed* in Nov 2024 but FY2023's was filed in Nov 2023.

    Matching on filingDate would attribute the wrong document to the year.
    """
    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with _mock_client() as client:
        filing = await edgar.find_filing("0000320193", "10-K", 2024, client)

    assert filing["accession_number"] == "0000320193-24-000123"
    assert filing["report_date"] == "2024-09-28"
    assert filing["company_name"] == "Apple Inc."


async def test_find_filing_ignores_other_form_types() -> None:
    """The 10-Q in the fixture shares neither form nor period; it must not match."""
    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with _mock_client() as client:
        with pytest.raises(FilingNotFoundException):
            await edgar.find_filing("0000320193", "10-K", 2019, client)


async def test_xbrl_facts_select_annual_10k_values_only() -> None:
    """The Q3 datapoint must not leak into an annual comparison."""
    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with _mock_client() as client:
        facts = await edgar.fetch_xbrl_facts("0000320193", 2024, client)

    assert facts["revenue"] == 391035000000.0
    assert facts["operating_income"] == 123216000000.0
    assert facts["net_income"] == 93736000000.0
    # Never the 85.7bn quarterly value.
    assert facts["revenue"] != 85777000000.0


async def test_xbrl_facts_omit_untagged_concepts() -> None:
    """A concept the registrant did not tag is absent, not zero."""
    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with _mock_client() as client:
        facts = await edgar.fetch_xbrl_facts("0000320193", 2024, client)

    assert "cash_from_operations" not in facts
    assert "capital_expenditures" not in facts


async def test_mda_extraction_skips_table_of_contents() -> None:
    """The first Item 7 hit is the TOC entry; the real section is later."""
    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with _mock_client() as client:
        text = await edgar.fetch_mda_text(
            "0000320193", "0000320193-24-000123", "aapl-20240928.htm", client
        )

    assert "Total net sales increased 2%" in text
    assert "Quantitative" not in text


async def test_mda_returns_empty_when_boundary_missing() -> None:
    """A wrong excerpt attributed to a real filing is worse than no excerpt."""

    def no_item7(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>Nothing useful here.</body></html>")

    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with httpx.AsyncClient(transport=httpx.MockTransport(no_item7)) as client:
        text = await edgar.fetch_mda_text("0000320193", "0000320193-24-000123", "x.htm", client)

    assert text == ""


# ---------------------------------------------------------------------------
# SECFilingClient routing
# ---------------------------------------------------------------------------


async def test_offline_mode_is_the_default() -> None:
    """CI, tests and the eval gate must never depend on sec.gov being up."""
    assert Settings().offline_mode is True


async def test_offline_curated_fixture_is_labelled() -> None:
    client = SECFilingClient(Settings(offline_mode=True))
    result = await client.fetch_filing_section("AAPL", "10-K", 2024, "INCOME_STATEMENT")

    assert result["data_source"] == "OFFLINE_FIXTURE"
    assert result["provenance_signature"].startswith("FIXTURE:")


async def test_offline_unknown_ticker_is_flagged_as_synthetic() -> None:
    """Regression guard.

    This path previously returned invented $50bn financials for any ticker
    under a provenance signature that looked identical to a real SEC citation.
    The numbers are still generated, but they can no longer masquerade as
    filed data.
    """
    client = SECFilingClient(Settings(offline_mode=True))
    result = await client.fetch_filing_section("ZZZZ", "10-K", 2024, "INCOME_STATEMENT")

    assert result["data_source"] == "OFFLINE_SYNTHETIC_PLACEHOLDER"
    assert result["provenance_signature"].startswith("SYNTHETIC:")
    assert not result["provenance_signature"].startswith("SEC:")


async def test_live_mode_returns_real_xbrl_figures(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(offline_mode=False, sec_edgar_user_agent=VALID_UA)
    client = SECFilingClient(settings)
    monkeypatch.setattr(client.http, "build_client", _mock_client)

    result = await client.fetch_filing_section("AAPL", "10-K", 2024, "INCOME_STATEMENT")

    assert result["data_source"] == "SEC_EDGAR_LIVE"
    assert result["accession_number"] == "0000320193-24-000123"
    assert result["data"]["revenue_current"] == 391035000000.0
    assert result["data"]["revenue_prior"] == 383285000000.0
    assert result["provenance_signature"].startswith("SEC:AAPL:10-K:2024:")


async def test_live_mode_mda_section(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(offline_mode=False, sec_edgar_user_agent=VALID_UA)
    client = SECFilingClient(settings)
    monkeypatch.setattr(client.http, "build_client", _mock_client)

    result = await client.fetch_filing_section("AAPL", "10-K", 2024, "MDA_ITEM_7")

    assert result["data"]["extraction_status"] == "EXTRACTED"
    assert "Total net sales increased 2%" in result["data"]["text_summary"]


async def test_live_failure_falls_back_to_cache_and_trips_breaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An upstream outage degrades to labelled cached data, never to a 500."""

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("SEC unreachable", request=request)

    settings = Settings(offline_mode=False, sec_edgar_user_agent=VALID_UA)
    # One failure is enough to observe the fallback.
    settings.circuit_breaker_failure_threshold = 1
    client = SECFilingClient(settings)
    # Skip the real backoff sleeps.
    client.http.max_retries = 1
    monkeypatch.setattr(
        client.http,
        "build_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(broken)),
    )
    monkeypatch.setattr("asyncio.sleep", _noop_sleep)

    result = await client.fetch_filing_section("AAPL", "10-K", 2024, "INCOME_STATEMENT")

    assert result["source_status"] == "CACHED_FALLBACK_CIRCUIT_BREAKER_ACTIVE"
    assert client.circuit_breaker.state == "OPEN"


async def test_live_mode_unknown_ticker_raises_instead_of_inventing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In live mode there is no synthetic fallback. Missing means missing."""
    settings = Settings(offline_mode=False, sec_edgar_user_agent=VALID_UA)
    client = SECFilingClient(settings)
    monkeypatch.setattr(client.http, "build_client", _mock_client)

    with pytest.raises(FilingNotFoundException):
        await client.fetch_filing_section("ZZZZ", "10-K", 2024, "INCOME_STATEMENT")


async def _noop_sleep(_seconds: float) -> None:
    """Collapse backoff delays so the retry path is testable in milliseconds."""
    return None


def test_shape_statement_omits_missing_keys() -> None:
    shaped = SECFilingClient._shape_statement(
        "BALANCE_SHEET", {"shareholders_equity": 1.0}, {}
    )
    assert shaped["shareholders_equity"] == 1.0
    assert "total_debt" not in shaped
    assert shaped["xbrl_source"] == "us-gaap"


def test_shape_statement_unknown_section_is_empty() -> None:
    assert SECFilingClient._shape_statement("NOT_A_STATEMENT", {"revenue": 1.0}, {}) == {}


def test_ticker_file_fixture_is_valid_json() -> None:
    """Guards the fixture itself against drift."""
    assert json.loads(json.dumps(TICKER_FILE))["0"]["ticker"] == "AAPL"
