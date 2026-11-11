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
    ResponseBlockedException,
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
    tags=["Equity Research"],
)
async def generate_equity_research(
    request: EquityResearchRequest,
    user_id: str = Depends(verify_auth_token),
    app_container: ApplicationContainer = Depends(get_container),
) -> ResearchBriefResponse:
    """
    Executes the multi-source equity research synthesis pipeline:
    1. Pre-execution security guardrail inspection & PII masking.
    2. Concurrent sub-agent extraction (SEC EDGAR, transcripts, macro context).
    3. Deterministic financial ratio computation (Python Decimal).
    4. Synthesis of an audit-ready brief with line-item provenance.
    5. Egress screening of the brief's narrative text (Model Armor).
    6. Structured compliance audit logging and Pub/Sub event broadcast.
    """
    req_start = time.monotonic()

    # Step 1: Pre-execution Guardrail & DLP Sanitization
    try:
        combined_prompt = f"Analyze {request.ticker} for FY{request.fiscal_year} focus: {', '.join(request.focus_areas)}"
        sanitized_prompt = await app_container.guardrail.inspect_and_sanitize_async(combined_prompt)
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
            guardrail_verdict="REJECT_INJECTION",
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
            guardrail_verdict="REJECT_SCOPE",
        )
        raise HTTPException(status_code=400, detail=f"Scope Violation: {e.message}") from e

    # Step 2: Multi-Agent Orchestration Loop
    try:
        brief = await app_container.root_coordinator.execute_research(request)
    except FinancialAgentException as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Multi-agent execution failure: {str(e)}") from e

    # Step 2b: Egress screening of the brief's narrative surfaces
    try:
        await app_container.guardrail.screen_response_async(
            brief.narrative_text(), user_prompt=sanitized_prompt
        )
    except ResponseBlockedException as e:
        await audit_logger.log_research_execution(
            ticker=request.ticker,
            fiscal_year=request.fiscal_year,
            prompt=sanitized_prompt,
            user_id=user_id,
            tools_called=[],
            latency_ms=int((time.monotonic() - req_start) * 1000),
            total_tokens=brief.metadata.total_tokens_consumed,
            cost_usd=brief.metadata.estimated_cost_usd,
            guardrail_verdict="REJECT_RESPONSE",
        )
        raise HTTPException(status_code=e.status_code, detail=f"Response Blocked: {e.message}") from e

    elapsed_ms = int((time.monotonic() - req_start) * 1000)

    # Step 3: Stream Compliance Audit Record
    await audit_logger.log_research_execution(
        ticker=request.ticker,
        fiscal_year=request.fiscal_year,
        prompt=sanitized_prompt,
        user_id=user_id,
        tools_called=[
            "fetch_sec_filing_section",
            "get_earnings_transcript",
            "query_macro_news",
            "financial_calculator",
        ],
        latency_ms=elapsed_ms,
        total_tokens=brief.metadata.total_tokens_consumed,
        cost_usd=brief.metadata.estimated_cost_usd,
        guardrail_verdict="PASS",
        citations_count=len(brief.citations),
    )

    # Step 4: Asynchronous Pub/Sub Event Broadcast
    await broadcaster.broadcast_brief_completed(
        brief_id=brief.brief_id,
        ticker=brief.ticker,
        fiscal_year=brief.fiscal_year,
        metrics_count=len(brief.key_financial_metrics),
        citations_count=len(brief.citations),
        risk_categories=[r.risk_category for r in brief.risk_matrices],
    )

    return brief


@router.post(
    "/v1/research/filings",
    status_code=status.HTTP_200_OK,
    summary="Extract & Normalize SEC Filing Statements",
    tags=["Regulatory Filings"],
)
async def extract_filings(
    request: FilingResearchRequest,
    user_id: str = Depends(verify_auth_token),
    app_container: ApplicationContainer = Depends(get_container),
) -> dict[str, Any]:
    """Direct MCP extraction of normalized SEC filing statement sections."""
    try:
        results = {}
        for sec in request.sections:
            data = await app_container.sec_client.fetch_filing_section(
                ticker=request.ticker,
                form=request.form,
                fiscal_year=request.fiscal_year,
                section=sec,
            )
            results[sec] = data
        return {
            "ticker": request.ticker,
            "fiscal_year": request.fiscal_year,
            "form": request.form,
            "sections": results,
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
    """Cloud Run readiness probe reporting active runtime mode and circuit breaker state."""
    return {
        "status": "READY",
        "runtime": {
            "environment": settings.environment,
            "offline_mode": settings.offline_mode,
        },
        "dependencies": {
            "circuit_breaker": app_container.sec_client.circuit_breaker.state,
        },
    }
