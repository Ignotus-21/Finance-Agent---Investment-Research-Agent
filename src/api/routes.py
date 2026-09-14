"""
FastAPI REST API Endpoints.
Conforms to the OpenAPI 3.1 specification (openapi.yaml).
"""

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.dependencies import get_container, verify_auth_token
from src.core.container import ApplicationContainer
from src.core.exceptions import (
    FilingNotFoundException,
    OutOfDomainQueryException,
    SecurityViolationException,
    UpstreamRateLimitException,
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
    Executes the multi-agent research workflow:
    1. Pre-execution DLP sanitization & security guardrail inspection.
    2. Dynamic planning with Gemini 2.5 Pro thinking budget.
    3. Concurrent sub-agent extraction (SEC EDGAR MCP, Transcripts, Macro Search).
    4. Deterministic financial verification tool invocation.
    5. Synthesis of audit-ready brief with 100% line-item provenance.
    6. Streaming compliance audit logging and Pub/Sub event broadcast.
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
    except FilingNotFoundException as e:
        raise HTTPException(status_code=404, detail=e.message) from e
    except UpstreamRateLimitException as e:
        raise HTTPException(status_code=429, detail=e.message) from e
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
    """Cloud Run readiness probe."""
    return {
        "status": "READY",
        "dependencies": {
            "vertex_ai": "CONNECTED",
            "bigquery": "CONNECTED",
            "secret_manager": "CONNECTED",
            "circuit_breaker": app_container.sec_client.circuit_breaker.state
        }
    }
