"""
Pydantic Response Schemas for the IRA REST API.
Enforces strict schema validation with 100% evidentiary provenance.
"""

from typing import Any

from pydantic import BaseModel, Field


class EvidentiaryCitation(BaseModel):
    """Line-item citation verifying evidentiary provenance from primary sources."""

    citation_id: str = Field(..., description="Unique citation identifier (UUID).")
    source_type: str = Field(
        ...,
        description="Source type: SEC_FORM_10K, SEC_FORM_10Q, TRANSCRIPT_REMARKS, TRANSCRIPT_QA, MACRO_NEWS"
    )
    filing_accession_number: str | None = Field(
        default=None,
        description="SEC EDGAR accession number (e.g. 0000320193-24-000106)."
    )
    document_period: str = Field(..., description="Period string (e.g. FY2024, Q4_2024).")
    table_or_section_name: str = Field(..., description="Name of the statement, table, or transcript section.")
    row_item: str | None = Field(default=None, description="Exact row title from SEC table.")
    column_header: str | None = Field(default=None, description="Exact column header / reporting date.")
    verbatim_quote: str | None = Field(default=None, description="Verbatim statement or transcript excerpt.")
    source_url: str | None = Field(default=None, description="Direct URL to SEC EDGAR filing or source article.")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Verification confidence score.")


class FinancialMetric(BaseModel):
    """Deterministic verified financial ratio with input audit trail."""

    name: str = Field(..., description="Machine-readable metric name.")
    display_name: str = Field(..., description="Human-readable title.")
    value: float = Field(..., description="Computed numerical value.")
    unit: str = Field(..., description="Unit of measurement (percentage, bps, currency_usd, ratio_multiple).")
    formula_applied: str = Field(..., description="Explicit formula used to compute the value.")
    prior_period_value: float | None = Field(default=None, description="Value for period t-1 if comparative.")
    current_period_value: float | None = Field(default=None, description="Value for period t.")
    provenance_verified: bool = Field(default=True, description="Whether line-item provenance was confirmed.")


class RiskMatrixItem(BaseModel):
    """Qualitative and quantitative risk disclosure from Item 1A / Transcripts."""

    risk_category: str = Field(..., description="Category (e.g. Geopolitical, Regulatory, Supply Chain, Valuation).")
    description: str = Field(..., description="Detailed description of the risk exposure.")
    severity: str = Field(..., description="Risk severity rating: LOW, MEDIUM, HIGH, CRITICAL.")
    source_disclosure: str = Field(..., description="Source statement or transcript disclosure.")


class QualitativeSynthesis(BaseModel):
    """Synthesis of qualitative executive commentary and analyst sentiment."""

    executive_commentary_analysis: str = Field(
        ...,
        description="Synthesis of CEO/CFO strategic outlook, capital allocation, and forward guidance."
    )
    analyst_qa_highlights: str = Field(
        ...,
        description="Highlights of tough analyst questions, margin pushback, and management defenses."
    )
    macro_market_context: str = Field(
        ...,
        description="Industry backdrop, interest rate environment, and competitive landscape."
    )


class ResearchMetadata(BaseModel):
    """Operational telemetry and execution metadata for the research brief.

    The inference fields below are zero on this endpoint, and that is the
    correct value rather than a missing measurement.

    ``POST /v1/research/equity`` runs the deterministic pipeline: XBRL facts are
    read from the filing, ratios are computed in Python by
    ``FinancialCalculator``, and the brief is assembled by template. No language
    model is called anywhere in it. That is what makes the faithfulness score
    1.0 and the P95 a quarter of a second, and it is also why there is nothing
    to cache and nothing to route.

    These fields previously carried ``total_tokens_consumed = 24500`` and
    ``estimated_cost_usd = 0.165`` - a hardcoded pair selected by a boolean that
    was itself always true - and a ``model_routing`` map naming two models the
    request never invoked. Every report in ``docs/`` quoted the $0.165 as a
    measurement.

    The LLM path is the ADK agent (``adk run src/agents``), which does route
    between Pro and Flash and does use ADK's context caching. It does not
    produce a ``ResearchBriefResponse``, so it does not fill these in either.
    """

    generation_timestamp: str
    latency_ms: int
    total_tokens_consumed: int = Field(
        default=0,
        description="LLM tokens consumed. Zero on the deterministic REST path, which calls no model.",
    )
    context_cache_hit: bool = Field(
        default=False,
        description="Whether a Gemini context cache was reused. Always false on the REST path: no model call, nothing to cache.",
    )
    estimated_cost_usd: float = Field(
        default=0.0,
        description="Inference cost. Zero on the REST path. Compute cost is Cloud Run's, and is not attributed per brief.",
    )
    model_routing: dict[str, str] = Field(
        default_factory=dict,
        description="Model used per agent. Empty on the REST path. Populated only where a model was actually invoked.",
    )


class ResearchBriefResponse(BaseModel):
    """Master audit-ready research brief conforming to OpenAPI 3.1 contract."""

    brief_id: str = Field(..., description="Unique research brief identifier.")
    ticker: str = Field(..., description="Equity ticker symbol.")
    company_name: str = Field(..., description="Full corporate name.")
    fiscal_year: int = Field(..., description="Fiscal reporting year analyzed.")
    executive_summary: str = Field(..., description="High-level investment summary and thesis.")
    key_financial_metrics: list[FinancialMetric] = Field(default_factory=list)
    qualitative_synthesis: QualitativeSynthesis
    risk_matrices: list[RiskMatrixItem] = Field(default_factory=list)
    citations: list[EvidentiaryCitation] = Field(default_factory=list)
    metadata: ResearchMetadata


class ErrorResponse(BaseModel):
    """RFC 7807 compliant structured error response."""

    error_code: str
    message: str
    details: dict[str, Any] | None = None
    timestamp: str
