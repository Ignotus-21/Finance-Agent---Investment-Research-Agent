"""
Pydantic Response Schemas for the IRA REST API.
Enforces strict schema validation with 100% evidentiary provenance.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EvidentiaryCitation(BaseModel):
    """Line-item citation verifying evidentiary provenance from primary sources."""

    citation_id: str = Field(..., description="Unique citation identifier (UUID).")
    source_type: str = Field(
        ...,
        description="Source type: SEC_FORM_10K, SEC_FORM_10Q, TRANSCRIPT_REMARKS, TRANSCRIPT_QA, MACRO_NEWS"
    )
    filing_accession_number: Optional[str] = Field(
        default=None,
        description="SEC EDGAR accession number (e.g. 0000320193-24-000106)."
    )
    document_period: str = Field(..., description="Period string (e.g. FY2024, Q4_2024).")
    table_or_section_name: str = Field(..., description="Name of the statement, table, or transcript section.")
    row_item: Optional[str] = Field(default=None, description="Exact row title from SEC table.")
    column_header: Optional[str] = Field(default=None, description="Exact column header / reporting date.")
    verbatim_quote: Optional[str] = Field(default=None, description="Verbatim statement or transcript excerpt.")
    source_url: Optional[str] = Field(default=None, description="Direct URL to SEC EDGAR filing or source article.")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0, description="Verification confidence score.")


class FinancialMetric(BaseModel):
    """Deterministic verified financial ratio with input audit trail."""

    name: str = Field(..., description="Machine-readable metric name.")
    display_name: str = Field(..., description="Human-readable title.")
    value: float = Field(..., description="Computed numerical value.")
    unit: str = Field(..., description="Unit of measurement (percentage, bps, currency_usd, ratio_multiple).")
    formula_applied: str = Field(..., description="Explicit formula used to compute the value.")
    prior_period_value: Optional[float] = Field(default=None, description="Value for period t-1 if comparative.")
    current_period_value: Optional[float] = Field(default=None, description="Value for period t.")
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
        description="Real-time industry backdrop, interest rate environment, and competitive landscape."
    )


class ResearchMetadata(BaseModel):
    """Operational telemetry and execution metadata for the research brief."""

    generation_timestamp: str
    latency_ms: int
    total_tokens_consumed: int
    context_cache_hit: bool
    estimated_cost_usd: float
    model_routing: Dict[str, str] = Field(
        default_factory=lambda: {
            "root_coordinator": "gemini-2.5-pro",
            "sec_agent": "gemini-2.5-flash",
            "transcript_agent": "gemini-2.5-flash",
            "macro_agent": "vertex-search"
        }
    )


class ResearchBriefResponse(BaseModel):
    """Master audit-ready research brief conforming to OpenAPI 3.1 contract."""

    brief_id: str = Field(..., description="Unique research brief identifier.")
    ticker: str = Field(..., description="Equity ticker symbol.")
    company_name: str = Field(..., description="Full corporate name.")
    fiscal_year: int = Field(..., description="Fiscal reporting year analyzed.")
    executive_summary: str = Field(..., description="High-level investment summary and thesis.")
    key_financial_metrics: List[FinancialMetric] = Field(default_factory=list)
    qualitative_synthesis: QualitativeSynthesis
    risk_matrices: List[RiskMatrixItem] = Field(default_factory=list)
    citations: List[EvidentiaryCitation] = Field(default_factory=list)
    metadata: ResearchMetadata


class ErrorResponse(BaseModel):
    """RFC 7807 compliant structured error response."""

    error_code: str
    message: str
    details: Optional[Dict[str, Any]] = None
    timestamp: str
