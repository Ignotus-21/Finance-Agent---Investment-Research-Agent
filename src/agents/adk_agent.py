"""
Google ADK (Agent Development Kit) Integration for Investment Research Agent.

Exposes a production-ready Google ADK Agent (LlmAgent) and App configured with
Gemini 2.5 Pro, deterministic calculation tools, earnings call transcript
analysis, real-time macroeconomic search grounding, and SEC EDGAR filing
retrieval over the Model Context Protocol.

SEC tools are NOT defined in this module. They are served by
:mod:`src.mcp_servers.sec_edgar_server` and reached over MCP, which is what
ADR-002 specified. Defining local copies as well would create two paths to the
same data that can silently drift apart.
"""

import json
import os
import sys

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

from src.tools.financial_calculator import FinancialCalculator
from src.tools.search_grounding import VertexSearchClient
from src.tools.transcript_parser import TranscriptClient

# Initialize tool dependencies for the natively-hosted tools. SEC retrieval has
# no client here: it lives in the MCP server subprocess.
_transcript_client = TranscriptClient()
_search_client = VertexSearchClient()
_calculator = FinancialCalculator()


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


def create_sec_edgar_mcp_toolset() -> McpToolset:
    """Connect to the in-repo SEC EDGAR MCP server.

    The server runs as a stdio subprocess launched with the *current*
    interpreter (``sys.executable``), so it inherits this virtualenv and its
    configuration - including ``OFFLINE_MODE``. Hard-coding ``python`` would
    silently pick up a different interpreter under Cloud Run.

    stdio rather than SSE/HTTP: the agent and the server share a lifecycle and
    a trust boundary, so there is no reason to open a listening port.

    ADK establishes the connection lazily on first tool listing, which is why
    constructing this is cheap and safe at import time.
    """
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=["-m", "src.mcp_servers.sec_edgar_server"],
                # Inherit the parent environment so OFFLINE_MODE, the SEC
                # User-Agent and GCP credentials reach the subprocess.
                env=dict(os.environ),
            ),
        ),
    )


def create_financial_adk_agent(model_name: str = "gemini-2.5-pro") -> Agent:
    """Creates an ADK Agent instance for Financial Investment Research.

    SEC retrieval is provided by the MCP toolset rather than by in-process
    functions. The remaining three tools stay native: transcripts and search
    have no external protocol server, and the calculator is pure local
    arithmetic where a protocol hop would add latency and nothing else.
    """
    return Agent(
        name="finance_investment_research_agent",
        model=Gemini(
            model=model_name,
            retry_options=types.HttpRetryOptions(attempts=3),
        ),
        instruction=FINANCE_AGENT_INSTRUCTION,
        tools=[
            create_sec_edgar_mcp_toolset(),
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
