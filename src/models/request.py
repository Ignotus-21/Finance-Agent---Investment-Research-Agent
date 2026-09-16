"""
Pydantic Request Schemas for the IRA REST API.
"""

from pydantic import BaseModel, Field, field_validator


class EquityResearchRequest(BaseModel):
    """Payload for initiating end-to-end equity research brief synthesis."""

    ticker: str = Field(
        ...,
        description="Public equity ticker symbol (e.g. AAPL, MSFT, NVDA).",
        examples=["AAPL"]
    )
    fiscal_year: int = Field(
        ...,
        description="Fiscal year to analyze.",
        ge=2010,
        le=2030,
        examples=[2024]
    )
    focus_areas: list[str] = Field(
        default_factory=lambda: ["Operating_Margin", "Segment_Revenue", "Risk_Factors"],
        description="Specific fundamental topics to analyze.",
        examples=[["Services_Margin", "China_Headwinds"]]
    )
    include_macro_context: bool = Field(
        default=True,
        description="Whether to run live search grounding for macroeconomic context."
    )

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned.isalnum() or len(cleaned) > 10:
            raise ValueError(f"Invalid equity ticker symbol format: '{v}'")
        return cleaned


class FilingResearchRequest(BaseModel):
    """Payload for extracting audited SEC statements directly via MCP."""

    ticker: str = Field(..., description="Equity ticker symbol.")
    fiscal_year: int = Field(..., description="Fiscal year to extract.")
    form: str = Field(default="10-K", description="SEC filing type (10-K, 10-Q, 8-K).")
    sections: list[str] = Field(
        default_factory=lambda: ["BALANCE_SHEET", "INCOME_STATEMENT"],
        description="Statement sections to parse."
    )

    @field_validator("form")
    @classmethod
    def validate_form(cls, v: str) -> str:
        allowed = {"10-K", "10-Q", "8-K"}
        upper = v.strip().upper()
        if upper not in allowed:
            raise ValueError(f"Form must be one of {allowed}, got '{v}'")
        return upper
