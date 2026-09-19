"""
Domain-Specific Exception Hierarchy.
Enables structured error handling and standard RFC 7807 problem responses.
"""

from typing import Any


class FinancialAgentException(Exception):
    """Base domain exception for all IRA system errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "INTERNAL_AGENT_ERROR",
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}


class SecurityViolationException(FinancialAgentException):
    """Raised when an adversarial prompt injection or jailbreak is detected."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            error_code="SECURITY_VIOLATION",
            status_code=400,
            details=details,
        )


class OutOfDomainQueryException(FinancialAgentException):
    """Raised when a request falls outside financial equity research boundaries."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message=message,
            error_code="OUT_OF_DOMAIN_QUERY",
            status_code=400,
            details=details,
        )


class FilingNotFoundException(FinancialAgentException):
    """Raised when an audited SEC filing or fiscal period is not available."""

    def __init__(self, ticker: str, form: str, fiscal_year: int) -> None:
        super().__init__(
            message=f"No audited filing found for ticker '{ticker}', form '{form}', year {fiscal_year}.",
            error_code="FILING_NOT_FOUND",
            status_code=404,
            details={"ticker": ticker, "form": form, "fiscal_year": fiscal_year},
        )


class RegistrantMismatchException(FinancialAgentException):
    """The entity holding the ticker today is not the one that filed the report.

    Distinct from FilingNotFoundException on purpose. "This company has no
    FY2024 10-K" and "you are looking at the wrong company" need different
    answers, and conflating them sent a reader hunting for a missing filing
    when the filing exists under another CIK.
    """

    def __init__(
        self, ticker: str, cik: str, entity_name: str, form: str, fiscal_year: int
    ) -> None:
        super().__init__(
            message=(
                f"Ticker '{ticker}' currently resolves to '{entity_name}' (CIK {cik}), "
                f"which has never filed a {form}. The ticker has most likely moved "
                f"registrant - a reorganisation, merger or holding-company insertion - "
                f"so the FY{fiscal_year} {form} belongs to a predecessor entity under a "
                f"different CIK. SEC publishes no reverse index from ticker to former "
                f"registrant; map it explicitly in TICKER_CIK_OVERRIDES "
                f"(src/tools/sec_edgar_http.py)."
            ),
            error_code="REGISTRANT_MISMATCH",
            status_code=404,
            details={
                "ticker": ticker,
                "resolved_cik": cik,
                "resolved_entity": entity_name,
                "form": form,
                "fiscal_year": fiscal_year,
            },
        )


class UpstreamUnavailableException(FinancialAgentException):
    """Raised when an upstream source is unreachable and no real data is cached.

    Deliberately distinct from FilingNotFoundException (404, "this does not
    exist"). This one means "the filing exists, we just cannot reach it right
    now" - a 503. SEC 429s land here too: sec_edgar_http backs off and retries,
    and an exhausted retry budget is an unreachable upstream like any other.

    It exists because the alternative was worse. The degraded path used to fall
    through to generated placeholder figures, which meant an EDGAR outage
    produced a brief full of confident, fabricated numbers rather than an
    error. An analyst can act on an error; they cannot detect a plausible lie.
    """

    def __init__(self, service: str, ticker: str, form: str, fiscal_year: int) -> None:
        super().__init__(
            message=(
                f"Upstream provider '{service}' is unavailable and no verified filing "
                f"for {ticker} {form} FY{fiscal_year} is cached locally. Refusing to "
                f"substitute synthetic figures for filed data."
            ),
            error_code="UPSTREAM_UNAVAILABLE",
            status_code=503,
            details={
                "service": service,
                "ticker": ticker,
                "form": form,
                "fiscal_year": fiscal_year,
            },
        )


class VerificationFailedException(FinancialAgentException):
    """Raised when evidentiary line-item provenance fails validation."""

    def __init__(self, metric_name: str, reason: str) -> None:
        super().__init__(
            message=f"Line-item verification failed for metric '{metric_name}': {reason}",
            error_code="VERIFICATION_FAILED",
            status_code=422,
            details={"metric_name": metric_name, "reason": reason},
        )
