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


class UpstreamRateLimitException(FinancialAgentException):
    """Raised when an upstream service returns 429 after retries."""

    def __init__(self, service: str, retry_after: int | None = None) -> None:
        super().__init__(
            message=f"Upstream provider '{service}' rate limit reached. Circuit breaker engaged.",
            error_code="UPSTREAM_RATE_LIMIT",
            status_code=429,
            details={"service": service, "retry_after": retry_after},
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
