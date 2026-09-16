"""Live SEC EDGAR HTTP client.

Talks to the real sec.gov endpoints. Everything here is public, unauthenticated
data, but SEC access is conditional on identifying yourself: requests without a
descriptive `User-Agent` are throttled and then blocked by IP. That header is
therefore non-negotiable and is asserted at construction time.

Endpoints used, and why each one:

  * ``https://www.sec.gov/files/company_tickers.json``
        The only public ticker -> CIK mapping. Fetched once and memoised for
        the process lifetime; it changes on the order of days, not seconds.

  * ``https://data.sec.gov/submissions/CIK##########.json``
        Filing history. Used to find the accession number for a given form and
        fiscal year.

  * ``https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json``
        Structured XBRL facts. This is deliberately preferred over scraping the
        filing HTML: the figures are the ones the registrant actually tagged,
        each carries its own accession number for provenance, and there is no
        parser to silently misread a table.

  * ``https://www.sec.gov/Archives/edgar/data/...``
        The primary document, used only for narrative sections such as Item 7
        MD&A, which have no XBRL representation.

This module has no fallback fixtures and no synthetic data. If SEC does not
have it, this raises. Fixture behaviour lives in SECFilingClient and is only
reachable in offline mode.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from src.core.exceptions import FilingNotFoundException

SEC_WWW = "https://www.sec.gov"
SEC_DATA = "https://data.sec.gov"

# US-GAAP XBRL tags, in preference order. Registrants tag the same economic
# concept differently - "Revenues" vs "RevenueFromContractWithCustomer..." - so
# each concept lists every tag we accept, most specific first.
XBRL_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "operating_income": ("OperatingIncomeLoss",),
    "net_income": ("NetIncomeLoss",),
    "cash_and_equivalents": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "total_debt": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "shareholders_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "cash_from_operations": ("NetCashProvidedByUsedInOperatingActivities",),
    "capital_expenditures": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
}


class SECEdgarHTTPClient:
    """Thin async client over the public SEC EDGAR REST surface."""

    def __init__(
        self,
        user_agent: str,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        # SEC blocks the default httpx User-Agent outright, and a placeholder
        # without a contact address gets the same treatment. Failing here beats
        # discovering it as an IP ban in production.
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "SEC requires a User-Agent of the form "
                "'Organization Name contact@example.com'. "
                f"Got: {user_agent!r}"
            )

        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._ticker_map: dict[str, str] | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept-Encoding": "gzip, deflate",
        }

    async def _get(self, url: str, client: httpx.AsyncClient) -> httpx.Response:
        """GET with exponential backoff on 429 and 5xx.

        429 is the case that matters: SEC applies it aggressively and expects
        callers to back off rather than retry immediately.
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = await client.get(url, headers=self._headers())
                if response.status_code in (429, 500, 502, 503, 504):
                    last_error = httpx.HTTPStatusError(
                        f"SEC returned {response.status_code} for {url}",
                        request=response.request,
                        response=response,
                    )
                    # 2s, 4s, 8s. Deterministic rather than jittered because the
                    # token bucket upstream already serialises our request rate.
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                await asyncio.sleep(2 ** (attempt + 1))

        raise RuntimeError(f"SEC EDGAR unreachable after {self.max_retries} attempts: {last_error}")

    async def resolve_cik(self, ticker: str, client: httpx.AsyncClient) -> str:
        """Map a ticker to its zero-padded 10-digit CIK."""
        if self._ticker_map is None:
            response = await self._get(f"{SEC_WWW}/files/company_tickers.json", client)
            payload = response.json()
            # The file is a dict keyed by row index, not a list.
            self._ticker_map = {
                str(row["ticker"]).upper(): str(row["cik_str"]).zfill(10)
                for row in payload.values()
            }

        cik = self._ticker_map.get(ticker.upper())
        if cik is None:
            raise FilingNotFoundException(ticker=ticker, form="ANY", fiscal_year=0)
        return cik

    async def find_filing(
        self,
        cik: str,
        form: str,
        fiscal_year: int,
        client: httpx.AsyncClient,
    ) -> dict[str, Any]:
        """Locate the filing of `form` whose report period falls in `fiscal_year`."""
        response = await self._get(f"{SEC_DATA}/submissions/CIK{cik}.json", client)
        payload = response.json()

        company_name = payload.get("name", "")
        recent = payload.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        report_dates = recent.get("reportDate", [])
        filing_dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        documents = recent.get("primaryDocument", [])

        for i, filed_form in enumerate(forms):
            if filed_form.upper() != form.upper():
                continue
            # reportDate is the period end, which is what "fiscal year" means to
            # an analyst. filingDate would misattribute a FY2023 10-K filed in
            # early 2024.
            report_date = report_dates[i] if i < len(report_dates) else ""
            if not report_date.startswith(str(fiscal_year)):
                continue

            return {
                "company_name": company_name,
                "accession_number": accessions[i],
                "filing_date": filing_dates[i],
                "report_date": report_date,
                "primary_document": documents[i] if i < len(documents) else "",
            }

        raise FilingNotFoundException(ticker=cik, form=form, fiscal_year=fiscal_year)

    async def fetch_xbrl_facts(
        self,
        cik: str,
        fiscal_year: int,
        client: httpx.AsyncClient,
    ) -> dict[str, float]:
        """Pull tagged financial facts for `fiscal_year` from the companyfacts API.

        Only annual (FY) figures from 10-K filings are accepted. Quarterly
        frames would otherwise be silently mixed into an annual comparison.
        """
        response = await self._get(f"{SEC_DATA}/api/xbrl/companyfacts/CIK{cik}.json", client)
        us_gaap = response.json().get("facts", {}).get("us-gaap", {})

        facts: dict[str, float] = {}
        for concept, candidate_tags in XBRL_CONCEPTS.items():
            for tag in candidate_tags:
                value = self._extract_annual_value(us_gaap.get(tag), fiscal_year)
                if value is not None:
                    facts[concept] = value
                    break

        return facts

    @staticmethod
    def _extract_annual_value(tag_data: dict[str, Any] | None, fiscal_year: int) -> float | None:
        """Return the USD annual value for `fiscal_year`, or None if not tagged."""
        if not tag_data:
            return None

        for unit_values in tag_data.get("units", {}).get("USD", []):
            if unit_values.get("fy") != fiscal_year:
                continue
            if unit_values.get("fp") != "FY":
                continue
            if unit_values.get("form") != "10-K":
                continue
            value = unit_values.get("val")
            if isinstance(value, int | float):
                return float(value)

        return None

    async def fetch_mda_text(
        self,
        cik: str,
        accession_number: str,
        primary_document: str,
        client: httpx.AsyncClient,
        max_chars: int = 20000,
    ) -> str:
        """Extract Item 7 (MD&A) narrative from the primary filing document.

        MD&A has no XBRL representation, so this is the one place we parse HTML.
        The extraction is intentionally conservative: if the Item 7 boundary
        cannot be located it returns an empty string rather than a best-effort
        guess, because a wrong excerpt attributed to a real filing is worse
        than no excerpt at all.
        """
        if not primary_document:
            return ""

        accession_plain = accession_number.replace("-", "")
        url = f"{SEC_WWW}/Archives/edgar/data/{int(cik)}/{accession_plain}/{primary_document}"

        response = await self._get(url, client)
        text = self._html_to_text(response.text)

        # Take the last match: earlier ones are almost always table-of-contents
        # entries rather than the section itself.
        starts = [
            m.end()
            for m in re.finditer(
                r"item\s*7[.\s\u2014-]*\s*management.{0,5}s\s+discussion",
                text,
                re.IGNORECASE,
            )
        ]
        if not starts:
            return ""

        start = starts[-1]
        end_match = re.search(
            r"item\s*7a[.\s\u2014-]*\s*quantitative",
            text[start:],
            re.IGNORECASE,
        )
        end = start + end_match.start() if end_match else start + max_chars

        return text[start:end].strip()[:max_chars]

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Strip tags and collapse whitespace.

        Uses the stdlib rather than adding BeautifulSoup: we only need a flat
        text stream to regex over, not a navigable DOM.
        """
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = re.sub(r"&#\d+;", " ", text)
        return re.sub(r"\s+", " ", text)

    def build_client(self) -> httpx.AsyncClient:
        """Construct the underlying transport.

        Separated so tests can inject an httpx.MockTransport without
        monkeypatching module-level state.
        """
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=True,
        )
