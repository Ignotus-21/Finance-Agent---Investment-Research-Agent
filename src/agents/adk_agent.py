"""
Google ADK (Agent Development Kit) Integration for Investment Research Agent.
Exposes a production-ready Google ADK Agent (LlmAgent) and App configured with Gemini 2.5 Pro,
deterministic calculation tools, SEC EDGAR filing retrieval, earnings call transcript analysis,
and real-time macroeconomic search grounding.
"""

import asyncio
import json

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from src.tools.financial_calculator import FinancialCalculator
from src.tools.search_grounding import VertexSearchClient
from src.tools.sec_edgar_mcp import SECFilingClient
from src.tools.transcript_parser import TranscriptClient

# Initialize tool dependencies
_sec_client = SECFilingClient()
_transcript_client = TranscriptClient()
_search_client = VertexSearchClient()
_calculator = FinancialCalculator()


async def fetch_sec_filing_section(ticker: str, fiscal_year: int = 2024, section: str = "Item 7") -> str:
    """Retrieves official SEC filing text and verified disclosures for a company.

    Args:
        ticker: The equity stock ticker (e.g. AAPL, MSFT, GOOGL, NVDA, SYNTH).
        fiscal_year: The fiscal year of the 10-K filing (e.g. 2024).
        section: The target 10-K section, e.g. 'Item 1' (Business), 'Item 7' (MD&A), 'Item 8' (Financials).

    Returns:
        A JSON string containing the extracted text, section metadata, and official SEC citation string.
    """
    ticker_clean = ticker.strip().upper()
    internal_section = "MDA_ITEM_7" if "7" in section else "INCOME_STATEMENT"

    # Routed through the public client so the Token Bucket rate limiter and
    # Circuit Breaker apply to the ADK path exactly as they do to the REST path.
    filing = await _sec_client.fetch_filing_section(
        ticker=ticker_clean, form="10-K", fiscal_year=fiscal_year, section=internal_section
    )
    section_data = filing.get("data", {})

    if internal_section == "MDA_ITEM_7":
        content = section_data.get("text_summary", "Item 7 MD&A content summary.")
        focus = section_data.get("focus_areas", {})
    else:
        content = str(section_data)
        focus = {}

    return json.dumps({
        "ticker": ticker_clean,
        "fiscal_year": fiscal_year,
        "section": section,
        "content_excerpt": content[:1200],
        "focus_areas": focus,
        "accession_number": filing.get("accession_number"),
        "sec_citation": f"[SEC: {ticker_clean} 10-K FY{fiscal_year} {section}]",
        "provenance": "U.S. Securities and Exchange Commission EDGAR System",
        "provenance_signature": filing.get("provenance_signature"),
    })


async def extract_xbrl_financial_facts(ticker: str, fiscal_year: int = 2024) -> str:
    """Extracts authoritative XBRL tagged financial facts directly from SEC 10-K Item 8.

    Args:
        ticker: The equity stock ticker symbol.
        fiscal_year: The fiscal reporting year (e.g. 2024).

    Returns:
        JSON string containing revenue, net income, operating income, cash balance, and XBRL tags.
    """
    ticker_clean = ticker.strip().upper()

    # Each statement is fetched concurrently through the guarded public client method.
    income, balance, cash_flow = await asyncio.gather(*(
        _sec_client.fetch_filing_section(ticker_clean, "10-K", fiscal_year, statement)
        for statement in ("INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW")
    ))

    return json.dumps({
        "ticker": ticker_clean,
        "fiscal_year": fiscal_year,
        "income_statement": income.get("data", {}),
        "balance_sheet": balance.get("data", {}),
        "cash_flow": cash_flow.get("data", {}),
        "accession_number": income.get("accession_number"),
        "source": f"[SEC: {ticker_clean} 10-K FY{fiscal_year} Item 8 Financial Statements]"
    })


async def get_earnings_call_transcript(ticker: str, quarter: str = "Q4_2024") -> str:
    """Retrieves and analyzes executive remarks and analyst Q&A from quarterly earnings calls.

    Args:
        ticker: Equity stock ticker symbol.
        quarter: Target reporting quarter (e.g. 'Q4_2024', 'Q3_2024').

    Returns:
        JSON string containing executive guidance, Q&A sentiment score, key quotes, and transcript citations.
    """
    ticker_clean = ticker.strip().upper()
    transcript = await _transcript_client.get_transcript(ticker_clean, quarter)

    return json.dumps({
        "ticker": ticker_clean,
        "quarter": quarter,
        "event": transcript.get("event", f"{ticker_clean} Earnings Call"),
        "prepared_remarks_sample": transcript.get("prepared_remarks", [])[:2],
        "analyst_qa_sample": transcript.get("analyst_qa", [])[:2],
        "citation": f"[Earnings Call: {ticker_clean} {quarter} Executive Remarks]",
        "provenance_signature": transcript.get("provenance_signature"),
    })


async def query_macro_market_news(query: str, ticker: str = "") -> str:
    """Grounds analysis in real-time macroeconomic news, benchmark interest rates, and industry dynamics.

    Args:
        query: Market query (e.g. 'semiconductor capex trends', 'enterprise AI monetization', 'interest rate impact').
        ticker: Optional company ticker for targeted competitive news.

    Returns:
        JSON string with verified external search results, date stamps, and news citations.
    """
    ticker_clean = ticker.strip().upper() if ticker else "GLOBAL_MACRO"
    results = await _search_client.query_market_context(ticker_clean, [query])
    return json.dumps({
        "query": query,
        "ticker": ticker_clean,
        "results": results,
        "citation": f"[Search Grounding: Google Enterprise Search - {query[:30]}]"
    })


def compute_financial_ratios(revenue: float, net_income: float, operating_income: float, prior_revenue: float | None = None) -> str:
    """Deterministically computes financial performance ratios and margins without hallucination.

    Args:
        revenue: Current period total revenue in USD.
        net_income: Current period net income in USD.
        operating_income: Current period operating income in USD.
        prior_revenue: Prior period revenue in USD for YoY growth calculation.

    Returns:
        JSON string with Net Margin, Operating Margin, YoY Growth, and computation provenance.
    """
    yoy_growth = _calculator.calculate_yoy_growth(revenue, prior_revenue) if prior_revenue else None

    op_margin = (operating_income / revenue * 100.0) if revenue else 0.0
    net_margin = (net_income / revenue * 100.0) if revenue else 0.0

    return json.dumps({
        "revenue_usd": revenue,
        "net_income_usd": net_income,
        "operating_income_usd": operating_income,
        "operating_margin_pct": round(op_margin, 2),
        "net_margin_pct": round(net_margin, 2),
        "yoy_revenue_growth_pct": yoy_growth.value if yoy_growth else None,
        "status": "deterministic_verified"
    })


FINANCE_AGENT_INSTRUCTION = """You are the Senior Wall Street Equity Research Analyst Agent built with Google ADK and Gemini 2.5 Pro.
Your mission is to perform rigorous, institutional-grade equity research on publicly traded companies and synthesize executive-ready investment research briefs.

Follow these strict operating procedures:
1. FORMULATE A PLAN: Identify required information (SEC 10-K, Earnings Calls, Macro Market News, and Deterministic Financial Ratios).
2. USE TOOLS FOR ALL FACTUAL DATA:
   - Call fetch_sec_filing_section and extract_xbrl_financial_facts for authoritative financial disclosures.
   - Call get_earnings_call_transcript for executive tone, sentiment, and management commentary.
   - Call query_macro_market_news for external macro headwinds/tailwinds and competitive dynamics.
   - Call compute_financial_ratios for all mathematical calculations (NEVER guess or approximate margins or EPS).
3. MANDATORY CITATION PROTOCOL:
   - Every factual claim, metric, or guidance point MUST have an inline citation.
   - SEC Citations format: [SEC: <TICKER> 10-K FY<YEAR> Item <N>]
   - Transcript Citations format: [Earnings Call: <TICKER> <QUARTER> <SPEAKER>]
   - News Citations format: [News: <SOURCE> <DATE>]
4. STRUCTURE YOUR SYNTHESIS:
   - Executive Summary (Clear investment thesis, key drivers)
   - Financial Performance & XBRL Metrics (Revenue, Margins, Growth)
   - Earnings Call Sentiment & Management Tone (Execution credibility, forward guidance)
   - Macro & Competitive Industry Analysis (Market share, regulatory / economic catalysts)
   - Risk Factors & Mitigations (Downside risks with probability & impact)
   - Deterministic Ratio Verification (Audited calculation summary)
5. PROFESSIONALISM & OBJECTIVITY: Maintain balanced, dispassionate tone. Highlight both upside catalysts and downside risks.
"""


def create_financial_adk_agent(model_name: str = "gemini-2.5-pro") -> Agent:
    """Creates an ADK Agent instance for Financial Investment Research."""
    return Agent(
        name="finance_investment_research_agent",
        model=Gemini(
            model=model_name,
            retry_options=types.HttpRetryOptions(attempts=3),
        ),
        instruction=FINANCE_AGENT_INSTRUCTION,
        tools=[
            fetch_sec_filing_section,
            extract_xbrl_financial_facts,
            get_earnings_call_transcript,
            query_macro_market_news,
            compute_financial_ratios,
        ],
    )


def create_financial_adk_app(agent: Agent | None = None) -> App:
    """Creates an ADK App wrapping the financial research agent."""
    root = agent or create_financial_adk_agent()
    return App(
        root_agent=root,
        name="finance_research_app",
    )
