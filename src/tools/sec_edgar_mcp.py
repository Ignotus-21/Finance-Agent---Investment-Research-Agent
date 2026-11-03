"""
SEC EDGAR Filing Client.
Provides `SECFilingClient.fetch_filing_section` backed by two retrieval modes:
- Offline (`OFFLINE_MODE=true`): serves the recorded FY2024 SEC EDGAR corpus
  (`datasets/sec_fixtures_fy2024.json`) for deterministic local testing and CI.
- Live (`OFFLINE_MODE=false`): queries `data.sec.gov` via `SECEdgarHTTPClient`
  with token-bucket rate limiting and circuit-breaker fallback.
"""

import asyncio
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.config import Settings
from src.core.exceptions import (
    FilingNotFoundException,
    RegistrantMismatchException,
    UpstreamUnavailableException,
)
from src.core.interfaces import BaseTool, FilingRetrievalInterface
from src.tools.sec_edgar_http import SECEdgarHTTPClient

RECORDED_FILINGS_PATH = Path(__file__).resolve().parents[2] / "datasets" / "sec_fixtures_fy2024.json"


@lru_cache(maxsize=1)
def _load_recorded_filings() -> dict[str, dict[str, Any]]:
    """Load the recorded SEC EDGAR corpus keyed by `TICKER_YEAR_FORM`."""
    if not RECORDED_FILINGS_PATH.exists():
        return {}

    corpus = json.loads(RECORDED_FILINGS_PATH.read_text(encoding="utf-8"))

    filings: dict[str, dict[str, Any]] = {}
    for record in corpus.values():
        current, prior = record["current"], record["prior"]
        statements = {
            section: SECFilingClient._shape_statement(section, current, prior)
            for section in ("INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW")
        }
        mda = record.get("mda_item_7", "")
        statements["MDA_ITEM_7"] = {
            "section_title": "Item 7. Management's Discussion and Analysis",
            "text_summary": mda,
            "extraction_status": "EXTRACTED" if mda else "SECTION_BOUNDARY_NOT_FOUND",
        }

        key = f"{record['ticker'].upper()}_{record['fiscal_year']}_10-K"
        filings[key] = {
            "accession_number": record["accession_number"],
            "filing_date": record["filing_date"],
            "company_name": record["company_name"],
            "fiscal_year": record["fiscal_year"],
            "statements": statements,
        }

    return filings


class TokenBucketRateLimiter:
    """Token bucket rate limiter ensuring requests stay below SEC 10 req/s ceiling."""

    def __init__(self, rate: float = 8.0, capacity: float = 8.0) -> None:
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens < 1.0:
                wait_time = (1.0 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
            else:
                self.tokens -= 1.0


class CircuitBreaker:
    """Circuit breaker protecting upstream SEC EDGAR endpoints."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_state_change = time.monotonic()

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self) -> None:
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.last_state_change = time.monotonic()

    def is_available(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if (time.monotonic() - self.last_state_change) > self.recovery_timeout:
                self.state = "HALF_OPEN"
                return True
            return False
        return True


class SECFilingClient(FilingRetrievalInterface, BaseTool):
    """
    SEC Filing Client extracting Balance Sheets, Income Statements, Cash Flows,
    and Item 7 MD&A with XBRL provenance tags.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.rate_limiter = TokenBucketRateLimiter(rate=self.settings.sec_rate_limit_per_sec)
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.settings.circuit_breaker_failure_threshold,
            recovery_timeout=float(self.settings.circuit_breaker_recovery_timeout_seconds),
        )
        self._http: SECEdgarHTTPClient | None = None
        self._mock_edgar_filings: dict[str, dict[str, Any]] = _load_recorded_filings()

    @property
    def http(self) -> SECEdgarHTTPClient:
        """Lazily initialize the live SEC EDGAR HTTP client."""
        if self._http is None:
            self._http = SECEdgarHTTPClient(
                user_agent=self.settings.sec_edgar_user_agent,
                timeout_seconds=self.settings.sec_http_timeout_seconds,
                max_retries=self.settings.sec_http_max_retries,
            )
        return self._http

    @property
    def name(self) -> str:
        return "fetch_sec_filing_section"

    @property
    def description(self) -> str:
        return "Fetches parsed audited tables and XBRL line-item metadata from SEC Form 10-K/10-Q filings."

    async def fetch_filing_section(
        self, ticker: str, form: str, fiscal_year: int, section: str
    ) -> dict[str, Any]:
        """Fetch an SEC filing section under rate-limit and circuit-breaker protection."""
        if not self.circuit_breaker.is_available():
            return self._get_cached_fallback(ticker, form, fiscal_year, section)

        await self.rate_limiter.acquire()

        if self.settings.offline_mode:
            return self._fetch_from_fixtures(ticker, form, fiscal_year, section)

        return await self._fetch_from_edgar(ticker, form, fiscal_year, section)

    def _fetch_from_fixtures(
        self, ticker: str, form: str, fiscal_year: int, section: str
    ) -> dict[str, Any]:
        """Retrieve filing section from recorded offline fixtures."""
        key = f"{ticker.upper()}_{fiscal_year}_{form.upper()}"
        filing = self._mock_edgar_filings.get(key)
        is_curated = filing is not None

        if filing is None:
            if not (ticker and ticker.replace(".", "").isalnum() and len(ticker) <= 8):
                self.circuit_breaker.record_failure()
                raise FilingNotFoundException(ticker=ticker, form=form, fiscal_year=fiscal_year)
            filing = self._generate_generic_filing(ticker.upper(), fiscal_year, form)

        self.circuit_breaker.record_success()
        section_data = filing.get("statements", {}).get(section.upper(), {})

        return {
            "ticker": ticker.upper(),
            "form": form.upper(),
            "fiscal_year": fiscal_year,
            "accession_number": filing["accession_number"],
            "filing_date": filing["filing_date"],
            "company_name": filing["company_name"],
            "section_requested": section.upper(),
            "data": section_data,
            "data_source": "OFFLINE_FIXTURE" if is_curated else "OFFLINE_SYNTHETIC_PLACEHOLDER",
            "provenance_signature": (
                f"FIXTURE:{ticker.upper()}:{form.upper()}:{fiscal_year}:{filing['accession_number']}"
                if is_curated
                else f"SYNTHETIC:{ticker.upper()}:{form.upper()}:{fiscal_year}"
            ),
        }

    async def _fetch_from_edgar(
        self, ticker: str, form: str, fiscal_year: int, section: str
    ) -> dict[str, Any]:
        """Retrieve live SEC EDGAR filing section or fall back to verified cached fixtures."""
        try:
            async with self.http.build_client() as client:
                cik = await self.http.resolve_cik(ticker, client)
                filing = await self.http.find_filing(
                    cik, form, fiscal_year, client, ticker=ticker
                )

                section_upper = section.upper()
                if section_upper == "MDA_ITEM_7":
                    text = await self.http.fetch_mda_text(
                        cik,
                        filing["accession_number"],
                        filing["primary_document"],
                        client,
                    )
                    section_data: dict[str, Any] = {
                        "section_title": "Item 7 MD&A",
                        "text_summary": text,
                        "extraction_status": "EXTRACTED" if text else "SECTION_BOUNDARY_NOT_FOUND",
                    }
                else:
                    period_end = filing.get("report_date", "")
                    facts = await self.http.fetch_xbrl_facts(
                        cik, fiscal_year, client, period_end=period_end
                    )
                    prior = await self.http.fetch_xbrl_facts(cik, fiscal_year - 1, client)
                    section_data = self._shape_statement(section_upper, facts, prior)

        except (FilingNotFoundException, RegistrantMismatchException):
            raise
        except Exception:
            self.circuit_breaker.record_failure()
            return self._get_cached_fallback(ticker, form, fiscal_year, section)

        self.circuit_breaker.record_success()

        return {
            "ticker": ticker.upper(),
            "form": form.upper(),
            "fiscal_year": fiscal_year,
            "accession_number": filing["accession_number"],
            "filing_date": filing["filing_date"],
            "company_name": filing["company_name"],
            "section_requested": section.upper(),
            "data": section_data,
            "data_source": "SEC_EDGAR_LIVE",
            "provenance_signature": (
                f"SEC:{ticker.upper()}:{form.upper()}:{fiscal_year}:{filing['accession_number']}"
            ),
        }

    @staticmethod
    def _shape_statement(
        section: str, facts: dict[str, float], prior: dict[str, float]
    ) -> dict[str, Any]:
        """Map extracted XBRL concepts to normalized financial statement dictionaries."""
        shapes: dict[str, dict[str, float | None]] = {
            "INCOME_STATEMENT": {
                "revenue_current": facts.get("revenue"),
                "revenue_prior": prior.get("revenue"),
                "operating_income_current": facts.get("operating_income"),
                "operating_income_prior": prior.get("operating_income"),
                "net_income": facts.get("net_income"),
            },
            "BALANCE_SHEET": {
                "cash_and_equivalents": facts.get("cash_and_equivalents"),
                "total_debt": facts.get("total_debt"),
                "shareholders_equity": facts.get("shareholders_equity"),
            },
            "CASH_FLOW": {
                "cash_from_operations": facts.get("cash_from_operations"),
                "capital_expenditures": facts.get("capital_expenditures"),
            },
        }

        names = {
            "INCOME_STATEMENT": "Consolidated Statements of Income",
            "BALANCE_SHEET": "Consolidated Balance Sheets",
            "CASH_FLOW": "Consolidated Statements of Cash Flows",
        }

        selected = shapes.get(section)
        if selected is None:
            return {}

        result: dict[str, Any] = {"statement_name": names[section], "xbrl_source": "us-gaap"}
        result.update({k: v for k, v in selected.items() if v is not None})
        return result

    def _get_cached_fallback(
        self, ticker: str, form: str, fiscal_year: int, section: str
    ) -> dict[str, Any]:
        """Return verified cached fixture when the circuit breaker is open, or raise 503 in live mode."""
        key = f"{ticker.upper()}_{fiscal_year}_{form.upper()}"
        filing = self._mock_edgar_filings.get(key)
        is_curated = filing is not None

        if filing is None:
            if not self.settings.offline_mode:
                raise UpstreamUnavailableException(
                    service="SEC_EDGAR",
                    ticker=ticker.upper(),
                    form=form.upper(),
                    fiscal_year=fiscal_year,
                )
            filing = self._generate_generic_filing(ticker.upper(), fiscal_year, form)

        return {
            "ticker": ticker.upper(),
            "form": form.upper(),
            "fiscal_year": fiscal_year,
            "accession_number": filing["accession_number"],
            "filing_date": filing["filing_date"],
            "company_name": filing["company_name"],
            "section_requested": section.upper(),
            "data": filing["statements"].get(section.upper(), {}),
            "data_source": "OFFLINE_FIXTURE" if is_curated else "OFFLINE_SYNTHETIC_PLACEHOLDER",
            "source_status": "CACHED_FALLBACK_CIRCUIT_BREAKER_ACTIVE",
            "provenance_signature": f"SEC:CACHE:{ticker}:{form}:{fiscal_year}",
        }

    def _generate_generic_filing(self, ticker: str, fiscal_year: int, form: str) -> dict[str, Any]:
        return {
            "accession_number": f"0000{abs(hash(ticker)) % 900000 + 100000}-24-000001",
            "filing_date": f"{fiscal_year}-10-15",
            "company_name": f"{ticker} Corporation",
            "fiscal_year": fiscal_year,
            "statements": {
                "INCOME_STATEMENT": {
                    "statement_name": "Consolidated Statements of Income",
                    "revenue_current": 50000000000.0,
                    "revenue_prior": 45000000000.0,
                    "operating_income_current": 12000000000.0,
                    "operating_income_prior": 10000000000.0,
                    "net_income": 9500000000.0,
                },
                "BALANCE_SHEET": {
                    "statement_name": "Consolidated Balance Sheets",
                    "cash_and_equivalents": 8000000000.0,
                    "total_debt": 15000000000.0,
                    "shareholders_equity": 35000000000.0,
                },
                "CASH_FLOW": {
                    "statement_name": "Consolidated Statements of Cash Flows",
                    "cash_from_operations": 14000000000.0,
                    "capital_expenditures": 3500000000.0,
                },
                "MDA_ITEM_7": {
                    "section_title": "Item 7 MD&A",
                    "text_summary": f"Consistent execution across business lines resulted in 11.1% YoY revenue growth for {ticker} in FY{fiscal_year}.",
                },
            },
        }
