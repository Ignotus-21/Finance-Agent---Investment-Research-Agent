"""Tests for the live SEC EDGAR ingestion path.

Every test drives the real code through ``httpx.MockTransport``, so the full
request-construction path is exercised (URLs, headers, JSON shape) without
touching the network. Nothing here hits sec.gov.
"""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from src.config import SAMPLE_SEC_USER_AGENT, Settings
from src.core.exceptions import (
    FilingNotFoundException,
    RegistrantMismatchException,
    UpstreamUnavailableException,
)
from src.tools.sec_edgar_http import TICKER_CIK_OVERRIDES, SECEdgarHTTPClient
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

# Mirrors the real companyfacts payload, including the detail that makes it
# treacherous: a FY2024 10-K restates FY2023 and FY2022 for comparison, and
# EDGAR tags all three rows `fy=2024, fp=FY, form=10-K`. Only the period dates
# distinguish them, so the fixture carries them exactly as EDGAR does.
COMPANY_FACTS = {
    "facts": {
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        # Quarterly figure - must be ignored.
                        {
                            "start": "2024-03-31",
                            "end": "2024-06-29",
                            "fy": 2024,
                            "fp": "Q3",
                            "form": "10-Q",
                            "val": 85777000000,
                        },
                        # Restated FY2022, reported by the FY2024 10-K. Listed
                        # first, as EDGAR does, so naive first-match selection
                        # picks it.
                        {
                            "start": "2021-09-26",
                            "end": "2022-09-24",
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "val": 394328000000,
                        },
                        {
                            "start": "2022-09-25",
                            "end": "2023-09-30",
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "val": 383285000000,
                        },
                        # Annual figure for the period we asked about.
                        {
                            "start": "2023-10-01",
                            "end": "2024-09-28",
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "val": 391035000000,
                        },
                    ]
                }
            },
            "OperatingIncomeLoss": {
                "units": {
                    "USD": [
                        {
                            "start": "2022-09-25",
                            "end": "2023-09-30",
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "val": 114301000000,
                        },
                        {
                            "start": "2023-10-01",
                            "end": "2024-09-28",
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "val": 123216000000,
                        },
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {
                    "USD": [
                        {
                            "start": "2023-10-01",
                            "end": "2024-09-28",
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "val": 93736000000,
                        }
                    ]
                }
            },
            # Balance-sheet item: an instant fact, so no `start`.
            "StockholdersEquity": {
                "units": {
                    "USD": [
                        {
                            "end": "2024-09-28",
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "val": 56950000000,
                        }
                    ]
                }
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


async def test_find_filing_searches_paginated_overflow_chunks() -> None:
    """Regression: `filings.recent` is capped, and for a prolific filer it fills
    with routine paperwork. JPMorgan's recent block holds 26,144 filings and
    exactly one 10-K; the FY2024 annual report sits in one of 70 overflow files.
    Reading only `recent` reported "no filing" for a document that plainly exists.

    The lookup must also stay cheap: chunks whose advertised date range cannot
    contain the filing are skipped rather than downloaded.
    """
    paginated = {
        "name": "JPMorgan Chase & Co",
        "filings": {
            "recent": {
                "form": ["8-K"],
                "reportDate": [""],
                "filingDate": ["2025-06-02"],
                "accessionNumber": ["0000019617-25-000999"],
                "primaryDocument": ["jpm-8k.htm"],
            },
            "files": [
                {"name": "old.json", "filingFrom": "1994-01-01", "filingTo": "1996-12-31"},
                {
                    "name": "recent-overflow.json",
                    "filingFrom": "2025-01-01",
                    "filingTo": "2025-03-31",
                },
            ],
        },
    }
    overflow = {
        "form": ["10-K"],
        "reportDate": ["2024-12-31"],
        "filingDate": ["2025-02-14"],
        "accessionNumber": ["0000019617-25-000270"],
        "primaryDocument": ["jpm-20241231.htm"],
    }
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        fetched.append(url)
        if url.endswith("recent-overflow.json"):
            return httpx.Response(200, json=overflow)
        if url.endswith("old.json"):
            return httpx.Response(200, json={})
        return httpx.Response(200, json=paginated)

    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        filing = await edgar.find_filing("0000019617", "10-K", 2024, client)

    assert filing["accession_number"] == "0000019617-25-000270"
    assert filing["company_name"] == "JPMorgan Chase & Co"
    assert not any("old.json" in url for url in fetched)


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


async def test_xbrl_facts_reject_prior_years_restated_by_the_same_filing() -> None:
    """Regression: a FY2024 10-K also reports FY2023 and FY2022, all tagged
    `fy=2024`. Selecting on that tag returned $394.3bn - Apple's FY2022 revenue -
    under a genuine FY2024 accession number. Only the period end disambiguates.
    """
    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with _mock_client() as client:
        facts = await edgar.fetch_xbrl_facts("0000320193", 2024, client, period_end="2024-09-28")

    assert facts["revenue"] == 391035000000.0
    assert facts["revenue"] != 394328000000.0  # FY2022, restated
    assert facts["revenue"] != 383285000000.0  # FY2023, restated


async def test_xbrl_facts_keep_instant_balance_sheet_items() -> None:
    """Balance-sheet facts carry no `start`, so the annual-duration filter that
    excludes quarterly figures must not discard them."""
    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with _mock_client() as client:
        facts = await edgar.fetch_xbrl_facts("0000320193", 2024, client)

    assert facts["shareholders_equity"] == 56950000000.0


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


async def test_live_mode_refuses_the_placeholder_contact() -> None:
    """Going live with the sample User-Agent must fail at construction.

    SEC blocks by source IP, and all egress from the deployed service leaves
    through one VPC connector, so the cost of this mistake is the whole
    service's access - collected later, as 403s that read like an outage.
    """
    with pytest.raises(ValidationError, match="SEC_EDGAR_USER_AGENT"):
        Settings(offline_mode=False)


async def test_live_mode_refuses_a_contact_without_an_address() -> None:
    with pytest.raises(ValidationError, match="SEC_EDGAR_USER_AGENT"):
        Settings(offline_mode=False, sec_edgar_user_agent="IRA Capstone Research")


async def test_offline_mode_tolerates_the_placeholder_contact() -> None:
    """The value is never sent in offline mode, so it must not block startup."""
    assert Settings(offline_mode=True).sec_edgar_user_agent == SAMPLE_SEC_USER_AGENT


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
    shaped = SECFilingClient._shape_statement("BALANCE_SHEET", {"shareholders_equity": 1.0}, {})
    assert shaped["shareholders_equity"] == 1.0
    assert "total_debt" not in shaped
    assert shaped["xbrl_source"] == "us-gaap"


def test_shape_statement_unknown_section_is_empty() -> None:
    assert SECFilingClient._shape_statement("NOT_A_STATEMENT", {"revenue": 1.0}, {}) == {}


def test_ticker_file_fixture_is_valid_json() -> None:
    """Guards the fixture itself against drift."""
    assert json.loads(json.dumps(TICKER_FILE))["0"]["ticker"] == "AAPL"


# ---------------------------------------------------------------------------
# Registrant resolution: ticker -> CIK is point-in-time, requests are historical
# ---------------------------------------------------------------------------

# A successor shell: it holds the ticker today and has filed nothing but the
# paperwork that created it. This is the shape of the XOM defect, reduced.
SUCCESSOR_TICKER_FILE = {
    "0": {"cik_str": 2115436, "ticker": "XOM", "title": "ExxonMobil Holdings Corp"},
}

SUCCESSOR_SUBMISSIONS = {
    "name": "ExxonMobil Holdings Corp",
    "filings": {
        "recent": {
            "form": ["8-K", "S-4"],
            "reportDate": ["2025-05-01", "2025-03-01"],
            "filingDate": ["2025-05-02", "2025-03-02"],
            "accessionNumber": ["0002115436-25-000002", "0002115436-25-000001"],
            "primaryDocument": ["xom-8k.htm", "xom-s4.htm"],
        }
    },
}


def _successor_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "company_tickers.json" in url:
        return httpx.Response(200, json=SUCCESSOR_TICKER_FILE)
    if "/submissions/" in url:
        return httpx.Response(200, json=SUCCESSOR_SUBMISSIONS)
    return httpx.Response(404, json={"error": "not found"})


async def test_override_wins_over_the_current_ticker_holder() -> None:
    """SEC's mapping is right about today and wrong about last year.

    `company_tickers.json` points XOM at the holding company inserted above the
    operating business in 2025. The FY2024 10-K was filed by the predecessor,
    whose `tickers` array is now empty - so following SEC's own mapping returns
    a company that never filed the report being asked for.
    """
    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_successor_handler)
    ) as client:
        assert await edgar.resolve_cik("XOM", client) == "0000034088"
        # Lower case too: callers pass whatever the user typed.
        assert await edgar.resolve_cik("xom", client) == "0000034088"


async def test_override_short_circuits_the_network() -> None:
    """An override is a decision, not a hint; it must not depend on SEC agreeing."""
    calls: list[str] = []

    def counting_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return _successor_handler(request)

    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(counting_handler)
    ) as client:
        await edgar.resolve_cik("XOM", client)

    assert calls == []


async def test_overrides_agree_with_the_offline_corpus() -> None:
    """
    The two data paths must name the same registrant.

    They did not. `datasets/sec_fixtures_fy2024.json` carried XOM at the
    correct predecessor CIK, so offline mode served it, the golden dataset
    scored it, and the eval gate reported perfect faithfulness - while the live
    path 404'd on the same ticker. A divergence between these two is invisible
    in CI by construction, which is exactly why it needs an assertion.
    """
    corpus = json.loads(
        (Path(__file__).resolve().parents[2] / "datasets/sec_fixtures_fy2024.json")
        .read_text()
    )
    for ticker, cik in TICKER_CIK_OVERRIDES.items():
        assert ticker in corpus, f"{ticker} is overridden but absent from the corpus"
        assert corpus[ticker]["cik"] == cik, (
            f"{ticker}: live path resolves to {cik}, offline corpus says "
            f"{corpus[ticker]['cik']}"
        )


async def test_successor_shell_raises_registrant_mismatch_not_not_found() -> None:
    """
    "No FY2024 10-K" and "wrong company" need different answers.

    An entity with no 10-K anywhere in its history is not having a quiet year.
    Reporting that as a missing filing sends the reader hunting for a document
    that exists, under a CIK nobody mentioned.
    """
    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_successor_handler)
    ) as client:
        with pytest.raises(RegistrantMismatchException) as excinfo:
            await edgar.find_filing(
                "0002115436", "10-K", 2024, client, ticker="XOM"
            )

    exc = excinfo.value
    assert exc.error_code == "REGISTRANT_MISMATCH"
    assert exc.details["resolved_entity"] == "ExxonMobil Holdings Corp"
    assert exc.details["resolved_cik"] == "0002115436"
    # The ticker slot holds a ticker. It used to hold the CIK, which read as
    # though the caller had asked for something nonsensical.
    assert exc.details["ticker"] == "XOM"


async def test_a_real_filer_missing_one_year_is_still_not_found() -> None:
    """The mismatch check must not swallow the ordinary case.

    Apple files 10-Ks; it just has none for FY2019 in the fixture. That is a
    missing filing, not a wrong company.
    """
    edgar = SECEdgarHTTPClient(user_agent=VALID_UA)
    async with _mock_client() as client:
        with pytest.raises(FilingNotFoundException):
            await edgar.find_filing("0000320193", "10-K", 2019, client, ticker="AAPL")


# ---------------------------------------------------------------------------
# Degraded-mode provenance.
#
# The circuit-breaker fallback used to omit ``data_source`` entirely, which
# crashed the MCP tool with KeyError at exactly the moment the agent most
# needed an answer, and - worse - served invented figures for any ticker
# without a curated fixture.
# ---------------------------------------------------------------------------


async def test_breaker_open_fallback_still_stamps_provenance() -> None:
    """Every response carries data_source, including the degraded ones.

    The MCP tool contract instructs the model to check this field before
    citing anything. An absent key makes that instruction unfollowable.
    """
    settings = Settings(offline_mode=True)
    client = SECFilingClient(settings)
    for _ in range(settings.circuit_breaker_failure_threshold):
        client.circuit_breaker.record_failure()
    assert not client.circuit_breaker.is_available()

    result = await client.fetch_filing_section("AAPL", "10-K", 2024, "INCOME_STATEMENT")

    assert result["data_source"] == "OFFLINE_FIXTURE"
    assert result["source_status"] == "CACHED_FALLBACK_CIRCUIT_BREAKER_ACTIVE"


async def test_breaker_open_fallback_labels_generated_data_as_synthetic() -> None:
    """A ticker with no curated fixture is labelled a placeholder, not a filing."""
    settings = Settings(offline_mode=True)
    client = SECFilingClient(settings)
    for _ in range(settings.circuit_breaker_failure_threshold):
        client.circuit_breaker.record_failure()

    result = await client.fetch_filing_section("ZZZZ", "10-K", 2024, "INCOME_STATEMENT")

    assert result["data_source"] == "OFFLINE_SYNTHETIC_PLACEHOLDER"


async def test_live_breaker_open_without_a_fixture_raises_503() -> None:
    """Live mode refuses to invent numbers when the upstream is down.

    Returning a generated income statement here would have produced a brief
    full of confident, fabricated figures during an EDGAR outage. An analyst
    can act on a 503; they cannot detect a plausible lie.
    """
    settings = Settings(offline_mode=False, sec_edgar_user_agent=VALID_UA)
    client = SECFilingClient(settings)
    for _ in range(settings.circuit_breaker_failure_threshold):
        client.circuit_breaker.record_failure()

    with pytest.raises(UpstreamUnavailableException) as excinfo:
        await client.fetch_filing_section("ZZZZ", "10-K", 2024, "INCOME_STATEMENT")

    assert excinfo.value.status_code == 503
    assert excinfo.value.error_code == "UPSTREAM_UNAVAILABLE"


async def test_live_breaker_open_with_a_fixture_serves_it_labelled() -> None:
    """A recorded filing for the exact request is real data, so serve it."""
    settings = Settings(offline_mode=False, sec_edgar_user_agent=VALID_UA)
    client = SECFilingClient(settings)
    for _ in range(settings.circuit_breaker_failure_threshold):
        client.circuit_breaker.record_failure()

    result = await client.fetch_filing_section("AAPL", "10-K", 2024, "INCOME_STATEMENT")

    assert result["data_source"] == "OFFLINE_FIXTURE"
    assert result["source_status"] == "CACHED_FALLBACK_CIRCUIT_BREAKER_ACTIVE"
