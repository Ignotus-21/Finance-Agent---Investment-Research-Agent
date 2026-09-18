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
from datetime import date as _date
from typing import Any

import httpx

from src.core.exceptions import FilingNotFoundException, RegistrantMismatchException

SEC_WWW = "https://www.sec.gov"
SEC_DATA = "https://data.sec.gov"

# Tickers whose current registrant of record did not file the historical report.
#
# `company_tickers.json` answers "who holds this ticker today". A request for
# FY2024 asks "who filed a year ago". Those are the same entity right up until
# a reorganisation, and then they are not.
#
# XOM is the live example. SEC maps the ticker to ExxonMobil Holdings Corp
# (CIK 2115436), a holding company inserted above the operating business, which
# has filed no 10-K at all. The FY2024 10-K (0000034088-25-000010) belongs to
# EXXON MOBIL CORP, CIK 34088 - an entity whose `tickers` array is now empty.
#
# There is no public reverse index from a ticker to its former registrant, so
# this cannot be resolved automatically. What *can* be automated is noticing:
# see RegistrantMismatchException, raised when the resolved entity has never
# filed the requested form, which is the signature of a successor shell.
TICKER_CIK_OVERRIDES: dict[str, str] = {
    "XOM": "0000034088",  # EXXON MOBIL CORP, not ExxonMobil Holdings Corp
}

# US-GAAP XBRL tags, in preference order. Registrants tag the same economic
# concept differently - "Revenues" vs "RevenueFromContractWithCustomer..." - so
# each concept lists every tag we accept, most specific first.
XBRL_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        # Banks and brokers report a top line net of interest expense and tag
        # it exclusively. Without this, WFC, GS and MS have no revenue at all,
        # and it is ordered ahead of "Revenues" because for an asset manager
        # like BLK "Revenues" is only a component ($12.8bn of a $20.4bn total).
        "RevenuesNetOfInterestExpense",
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
        """Map a ticker to its zero-padded 10-digit CIK.

        Overrides are consulted first, because SEC's own mapping is correct
        about the present and wrong about the past - see TICKER_CIK_OVERRIDES.
        """
        override = TICKER_CIK_OVERRIDES.get(ticker.upper())
        if override is not None:
            return override

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
        ticker: str | None = None,
    ) -> dict[str, Any]:
        """Locate the filing of `form` whose report period falls in `fiscal_year`.

        Searches ``filings.recent`` first, then the paginated overflow chunks.
        The overflow pass is not optional: ``recent`` is capped, and for a
        prolific filer it overflows with routine paperwork. JPMorgan's recent
        block holds 26,144 filings and contains exactly one 10-K - everything
        older has rolled into 70 overflow files. Searching only ``recent``
        therefore reports "no FY2024 10-K" for most large banks, for a filing
        that plainly exists.
        """
        response = await self._get(f"{SEC_DATA}/submissions/CIK{cik}.json", client)
        payload = response.json()

        company_name = payload.get("name", "")

        match = self._scan_filings(payload.get("filings", {}).get("recent", {}), form, fiscal_year)
        if match:
            return {"company_name": company_name, **match}

        for chunk in self._relevant_chunks(payload.get("filings", {}).get("files", []), fiscal_year):
            chunk_response = await self._get(f"{SEC_DATA}/submissions/{chunk}", client)
            match = self._scan_filings(chunk_response.json(), form, fiscal_year)
            if match:
                return {"company_name": company_name, **match}

        # Nothing matched. Before reporting a missing fiscal year, establish
        # whether this entity files this form at all.
        #
        # An entity with no 10-K in its entire history is not a company having
        # a quiet year - it is almost always a successor shell that has
        # inherited the ticker, and the report being asked for was filed by its
        # predecessor. Reporting that as "no FY2024 filing" sends the reader
        # looking for a document that exists, under a CIK they were never told
        # about. The previous message additionally printed the CIK in the
        # ticker slot, which made it look like the caller had asked for
        # something nonsensical.
        if not self._files_form_at_all(payload, form):
            raise RegistrantMismatchException(
                ticker=ticker or cik,
                cik=cik,
                entity_name=company_name or "unknown entity",
                form=form,
                fiscal_year=fiscal_year,
            )

        raise FilingNotFoundException(
            ticker=ticker or cik, form=form, fiscal_year=fiscal_year
        )

    @staticmethod
    def _files_form_at_all(payload: dict[str, Any], form: str) -> bool:
        """Has this registrant ever filed `form`, in any period?

        Only the `recent` block is inspected. The overflow chunks hold older
        filings, so an entity that files this form at all will show it here for
        any realistic query - and the point of the check is to separate "never"
        from "not that year", which does not need exhaustive history.
        """
        recent = payload.get("filings", {}).get("recent", {})
        return any(f.upper() == form.upper() for f in recent.get("form", []))

    @staticmethod
    def _relevant_chunks(files: list[dict[str, Any]], fiscal_year: int) -> list[str]:
        """Overflow chunks that could plausibly contain `fiscal_year`'s annual report.

        Each chunk advertises the filing-date range it covers. A 10-K for a
        fiscal year is filed within roughly two years of that year starting, so
        chunks outside that window are skipped rather than downloaded - the
        difference between 2-3 requests and 70 for a large bank.
        """
        lower, upper = str(fiscal_year), str(fiscal_year + 2)
        relevant = []
        for entry in files:
            name = entry.get("name")
            if not name:
                continue
            starts = str(entry.get("filingFrom", ""))[:4]
            ends = str(entry.get("filingTo", ""))[:4]
            # Keep the chunk if its window overlaps [fiscal_year, fiscal_year+2].
            if not starts or not ends or (ends >= lower and starts <= upper):
                relevant.append(name)
        return relevant

    @staticmethod
    def _scan_filings(block: dict[str, Any], form: str, fiscal_year: int) -> dict[str, Any] | None:
        """Find `form` for `fiscal_year` within one submissions block."""
        forms = block.get("form", [])
        report_dates = block.get("reportDate", [])
        filing_dates = block.get("filingDate", [])
        accessions = block.get("accessionNumber", [])
        documents = block.get("primaryDocument", [])

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
                "accession_number": accessions[i],
                "filing_date": filing_dates[i] if i < len(filing_dates) else "",
                "report_date": report_date,
                "primary_document": documents[i] if i < len(documents) else "",
            }

        return None

    async def fetch_xbrl_facts(
        self,
        cik: str,
        fiscal_year: int,
        client: httpx.AsyncClient,
        period_end: str = "",
    ) -> dict[str, float]:
        """Pull tagged financial facts for `fiscal_year` from the companyfacts API.

        `period_end` is the filing's `reportDate` (from :meth:`find_filing`) and
        is what actually identifies the period. See
        :meth:`_extract_annual_value` for why the `fy` tag cannot be used for
        this on its own.
        """
        response = await self._get(f"{SEC_DATA}/api/xbrl/companyfacts/CIK{cik}.json", client)
        us_gaap = response.json().get("facts", {}).get("us-gaap", {})

        facts: dict[str, float] = {}
        for concept, candidate_tags in XBRL_CONCEPTS.items():
            for tag in candidate_tags:
                value = self._extract_annual_value(us_gaap.get(tag), fiscal_year, period_end)
                if value is not None:
                    facts[concept] = value
                    break

        return facts

    @staticmethod
    def _extract_annual_value(
        tag_data: dict[str, Any] | None,
        fiscal_year: int,
        period_end: str = "",
    ) -> float | None:
        """Return the USD annual value for `fiscal_year`, or None if not tagged.

        The `fy` / `fp` fields in companyfacts identify **the filing that
        reported the fact, not the period the fact covers.** A FY2024 10-K
        restates FY2023 and FY2022 for comparison, and all three rows carry
        ``fy=2024, fp=FY, form=10-K``. Selecting on those fields alone matches
        all three and - taking the first - returns the *oldest*: for AAPL FY2024
        that yielded $394.3bn, which is the FY2022 figure, presented under a
        genuine FY2024 accession number. Live data, wrong period, and no label
        could have caught it.

        Selection is therefore anchored on the period end date:

        1. Prefer an exact match on the filing's own ``reportDate``.
        2. Otherwise accept an end date within the fiscal year, taking the
           latest, which handles small discrepancies between the submissions
           index and the XBRL tagging.

        Duration facts are additionally required to span 300-400 days so a
        quarterly figure can never satisfy an annual concept. Instant facts
        (balance-sheet items, which have no ``start``) are exempt from that.
        """
        if not tag_data:
            return None

        candidates: list[tuple[str, float]] = []

        for unit_values in tag_data.get("units", {}).get("USD", []):
            if unit_values.get("form") != "10-K":
                continue

            end = unit_values.get("end", "")
            if not end:
                continue

            start = unit_values.get("start")
            if start:
                days = (_date.fromisoformat(end) - _date.fromisoformat(start)).days
                if not 300 <= days <= 400:
                    continue

            value = unit_values.get("val")
            if not isinstance(value, int | float):
                continue

            if period_end and end == period_end:
                return float(value)

            if end.startswith(str(fiscal_year)):
                candidates.append((end, float(value)))

        if not candidates:
            return None

        # Latest period end wins: for a fiscal year ending mid-calendar-year the
        # comparative prior-year row can also start with the same four digits.
        return max(candidates, key=lambda pair: pair[0])[1]

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
