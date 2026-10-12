"""
FastAPI REST API Endpoints.
Conforms to the OpenAPI 3.1 specification (openapi.yaml).
"""

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.dependencies import get_container, verify_auth_token
from src.config import settings
from src.core.container import ApplicationContainer
from src.core.exceptions import (
    FilingNotFoundException,
    FinancialAgentException,
    OutOfDomainQueryException,
    SecurityViolationException,
)
from src.models.request import EquityResearchRequest, FilingResearchRequest
from src.models.response import ResearchBriefResponse
from src.observability.audit_logger import audit_logger
from src.observability.pubsub_broadcaster import broadcaster

router = APIRouter()
start_server_time = time.monotonic()


@router.post(
    "/v1/research/equity",
    response_model=ResearchBriefResponse,
    status_code=status.HTTP_200_OK,
    summary="Synthesize Comprehensive Equity Research Brief",
    tags=["Equity Research"]
)
async def generate_equity_research(
    request: EquityResearchRequest,
    user_id: str = Depends(verify_auth_token),
    app_container: ApplicationContainer = Depends(get_container)
) -> ResearchBriefResponse:
    """
    Executes the deterministic research pipeline (no model call on this path):
    1. Pre-execution PII masking & security guardrail inspection.
    2. Concurrent sub-agent extraction (SEC EDGAR, transcripts, macro context).
    3. Deterministic financial ratio computation (Python Decimal).
    4. Synthesis of an audit-ready brief with line-item provenance.
    5. Structured audit logging (exported to BigQuery by a log sink) and Pub/Sub event broadcast.
    """
    req_start = time.monotonic()

    # Step 1: Pre-execution Guardrail & DLP Sanitization
    try:
        combined_prompt = f"Analyze {request.ticker} for FY{request.fiscal_year} focus: {', '.join(request.focus_areas)}"
        sanitized_prompt = app_container.guardrail.inspect_and_sanitize(combined_prompt)
    except SecurityViolationException as e:
        await audit_logger.log_research_execution(
            ticker=request.ticker,
            fiscal_year=request.fiscal_year,
            prompt=str(e),
            user_id=user_id,
            tools_called=[],
            latency_ms=int((time.monotonic() - req_start) * 1000),
            total_tokens=0,
            cost_usd=0.0,
            guardrail_verdict="REJECT_INJECTION"
        )
        raise HTTPException(status_code=400, detail=f"Security Violation: {e.message}") from e
    except OutOfDomainQueryException as e:
        await audit_logger.log_research_execution(
            ticker=request.ticker,
            fiscal_year=request.fiscal_year,
            prompt=str(e),
            user_id=user_id,
            tools_called=[],
            latency_ms=int((time.monotonic() - req_start) * 1000),
            total_tokens=0,
            cost_usd=0.0,
            guardrail_verdict="REJECT_SCOPE"
        )
        raise HTTPException(status_code=400, detail=f"Scope Violation: {e.message}") from e

    # Step 2: Multi-Agent Orchestration Loop
    try:
        brief = await app_container.root_coordinator.execute_research(request)
    except FinancialAgentException as e:
        # Every domain exception already declares the status it means - 404 for
        # a missing filing or a registrant mismatch, 422 for a provenance
        # failure, 503 for an unreachable upstream. Honour that instead of
        # re-deriving it here and collapsing the interesting ones into 500.
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Multi-agent execution failure: {str(e)}") from e

    elapsed_ms = int((time.monotonic() - req_start) * 1000)

    # Step 3: Stream Compliance Audit Record
    await audit_logger.log_research_execution(
        ticker=request.ticker,
        fiscal_year=request.fiscal_year,
        prompt=sanitized_prompt,
        user_id=user_id,
        tools_called=[
            "fetch_sec_filing_section", "get_earnings_transcript", "query_macro_news", "financial_calculator"
        ],
        latency_ms=elapsed_ms,
        total_tokens=brief.metadata.total_tokens_consumed,
        cost_usd=brief.metadata.estimated_cost_usd,
        guardrail_verdict="PASS",
        citations_count=len(brief.citations)
    )

    # Step 4: Asynchronous Pub/Sub Event Broadcast
    await broadcaster.broadcast_brief_completed(
        brief_id=brief.brief_id,
        ticker=brief.ticker,
        fiscal_year=brief.fiscal_year,
        metrics_count=len(brief.key_financial_metrics),
        citations_count=len(brief.citations),
        risk_categories=[r.risk_category for r in brief.risk_matrices]
    )

    return brief


@router.post(
    "/v1/research/filings",
    status_code=status.HTTP_200_OK,
    summary="Extract & Normalize SEC Filing Statements",
    tags=["Regulatory Filings"]
)
async def extract_filings(
    request: FilingResearchRequest,
    user_id: str = Depends(verify_auth_token),
    app_container: ApplicationContainer = Depends(get_container)
) -> dict[str, Any]:
    """Direct MCP extraction of SEC filing tables."""
    try:
        results = {}
        for sec in request.sections:
            data = await app_container.sec_client.fetch_filing_section(
                ticker=request.ticker,
                form=request.form,
                fiscal_year=request.fiscal_year,
                section=sec
            )
            results[sec] = data
        return {
            "ticker": request.ticker,
            "fiscal_year": request.fiscal_year,
            "form": request.form,
            "sections": results
        }
    except FilingNotFoundException as e:
        raise HTTPException(status_code=404, detail=e.message) from e


@router.get("/healthz", tags=["Health & Diagnostics"])
async def healthz() -> dict[str, Any]:
    """Cloud Run liveness probe."""
    uptime = round(time.monotonic() - start_server_time, 2)
    return {"status": "HEALTHY", "uptime_seconds": uptime}


@router.get("/readyz", tags=["Health & Diagnostics"])
async def readyz(app_container: ApplicationContainer = Depends(get_container)) -> dict[str, Any]:
    """
    Cloud Run readiness probe.

    Reports only what the process can establish without making a network call.
    The `vertex_ai`, `bigquery` and `secret_manager` entries this used to return
    were not checks - they were the string literal "CONNECTED", and would have
    gone on saying CONNECTED through a total outage of all three. A probe that
    cannot fail is not a probe.

    `runtime` answers the question an operator actually has after a deploy: is
    this revision reading sec.gov, or the recorded FY2024 corpus? Both paths
    return HTTP 200 with an identical response shape, so short of inspecting the
    provenance field on a generated brief there was no way to tell them apart.
    """
    return {
        "status": "READY",
        "runtime": {
            "environment": settings.environment,
            "offline_mode": settings.offline_mode,
        },
        "dependencies": {
            "circuit_breaker": app_container.sec_client.circuit_breaker.state
        }
    }
