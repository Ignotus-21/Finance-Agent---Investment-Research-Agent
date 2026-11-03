"""
Google ADK (Agent Development Kit) Multi-Agent Orchestration for IRA.

Implements asymmetric model routing and Vertex AI context caching:
- Root Coordinator (`finance_investment_research_agent` on Gemini 2.5 Pro) handles
  planning, delegation via `AgentTool`, macro grounding, deterministic financial
  ratio verification, and final synthesis.
- Filing Extraction Specialist (`filing_extraction_specialist` on Gemini 2.5 Flash)
  retrieves SEC Form 10-K disclosures and XBRL facts over stdio MCP (`McpToolset`)
  alongside earnings call transcripts.
"""

import json
import os
import sys
from pathlib import Path

import yaml
from google.adk.agents import Agent
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

from src.config import Settings
from src.tools.financial_calculator import FinancialCalculator
from src.tools.macro_context import MacroContextClient
from src.tools.transcript_parser import TranscriptClient

_GEMINI_25_MIN_CACHEABLE_TOKENS = 2048
_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "configs" / "prompts"

_transcript_client = TranscriptClient()
_search_client = MacroContextClient()
_calculator = FinancialCalculator()


def _load_prompt_instruction(filename: str, fallback: str) -> str:
    """Load externalized system instruction from configs/prompts/<filename>."""
    path = _PROMPTS_DIR / filename
    if path.exists():
        try:
            with path.open(encoding="utf-8") as fh:
                payload = yaml.safe_load(fh)
                if isinstance(payload, dict) and isinstance(payload.get("system_instruction"), str):
                    return payload["system_instruction"].strip()
        except Exception:
            pass
    return fallback


async def get_earnings_call_transcript(ticker: str, quarter: str = "Q4_2024") -> str:
    """Retrieves executive remarks and analyst Q&A from quarterly earnings calls.

    Args:
        ticker: Equity stock ticker symbol.
        quarter: Target reporting quarter (e.g. 'Q4_2024', 'Q3_2024').

    Returns:
        JSON string containing executive guidance, Q&A excerpts, and transcript citations.
    """
    ticker_clean = ticker.strip().upper()
    transcript = await _transcript_client.get_transcript(ticker_clean, quarter)

    if not transcript.get("available"):
        return json.dumps({
            "ticker": ticker_clean,
            "quarter": quarter,
            "available": False,
            "message": f"No earnings call transcript is available for {ticker_clean} {quarter}. Do not quote or paraphrase management commentary for this period.",
        })

    return json.dumps({
        "ticker": ticker_clean,
        "quarter": quarter,
        "available": True,
        "event": transcript.get("event", f"{ticker_clean} Earnings Call"),
        "prepared_remarks_sample": transcript.get("prepared_remarks", [])[:2],
        "analyst_qa_sample": transcript.get("analyst_qa", [])[:2],
        "citation": f"[Earnings Call: {ticker_clean} {quarter} Executive Remarks]",
        "provenance_signature": transcript.get("provenance_signature"),
    })


async def query_macro_market_news(query: str, ticker: str = "") -> str:
    """Returns curated macroeconomic context: benchmark interest rates, macro news, and industry dynamics.

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
        "citation": f"[Macro corpus: curated sources - {query[:30]}]"
    })


def compute_financial_ratios(
    revenue: float,
    net_income: float,
    operating_income: float,
    prior_revenue: float | None = None,
) -> str:
    """Deterministically computes financial performance ratios and margins using Decimal precision.

    Args:
        revenue: Current period total revenue in USD.
        net_income: Current period net income in USD.
        operating_income: Current period operating income in USD.
        prior_revenue: Prior period revenue in USD for YoY growth calculation.

    Returns:
        JSON string with Net Margin, Operating Margin, YoY Growth, and computation provenance.
    """
    yoy_growth = _calculator.calculate_yoy_growth(revenue, prior_revenue) if prior_revenue else None

    return json.dumps({
        "revenue_usd": revenue,
        "net_income_usd": net_income,
        "operating_income_usd": operating_income,
        "operating_margin_pct": _calculator.calculate_margin_pct(operating_income, revenue),
        "net_margin_pct": _calculator.calculate_margin_pct(net_income, revenue),
        "yoy_revenue_growth_pct": yoy_growth.value if yoy_growth else None,
        "status": "deterministic_verified"
    })


_DEFAULT_EXTRACTION_INSTRUCTION = """You are a filings extraction specialist. You retrieve source documents and report what they say. You do not analyse, recommend, or synthesise.

Your tools:
  - fetch_sec_filing_section and extract_xbrl_financial_facts for 10-K disclosures.
  - get_earnings_call_transcript for management commentary and analyst Q&A.

Rules:
1. Call the tools. Never answer from memory - if a tool returns nothing, say so and stop. A figure you recall is not a figure from a filing.
2. Report figures exactly as tagged, with their units and period. Do not rescale, round, or convert.
3. Attach the source to every figure: the XBRL element name for financials, the accession number and item for prose, the speaker and quarter for transcripts.
4. Never compute anything. Ratios, growth rates and margins are the coordinator's job, and it uses a deterministic calculator rather than a model.
5. Where a company does not tag a concept, say it is absent. Do not substitute a related tag. A bank that does not report OperatingIncomeLoss has no operating margin, and that is the correct answer.

Return compact structured facts, not prose."""


_DEFAULT_FINANCE_AGENT_INSTRUCTION = """You are the Senior Wall Street Equity Research Analyst Agent built with Google ADK and Gemini 2.5 Pro.
Your mission is to perform rigorous, institutional-grade equity research on publicly traded companies and synthesize executive-ready investment research briefs.

Follow these strict operating procedures:
1. FORMULATE A PLAN: Identify required information (SEC 10-K, Earnings Calls, Macro Market News, and Deterministic Financial Ratios).
2. USE TOOLS FOR ALL FACTUAL DATA:
   - Call filing_extraction_specialist for every SEC filing figure, 10-K passage, and earnings call quote. It is a separate agent running on a faster model; give it a specific request ("FY2024 revenue, operating income and their prior-year comparatives for AAPL, with XBRL element names") rather than a vague one.
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

EXTRACTION_AGENT_INSTRUCTION = _load_prompt_instruction(
    "sec_filing_specialist.yaml", _DEFAULT_EXTRACTION_INSTRUCTION
)
FINANCE_AGENT_INSTRUCTION = _load_prompt_instruction(
    "coordinator_agent.yaml", _DEFAULT_FINANCE_AGENT_INSTRUCTION
)


def create_sec_edgar_mcp_toolset() -> McpToolset:
    """Create an ADK McpToolset connected over stdio to the in-repo SEC EDGAR MCP server."""
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=["-m", "src.mcp_servers.sec_edgar_server"],
                env=dict(os.environ),
            ),
        ),
    )


def create_filing_extraction_agent(model_name: str | None = None) -> Agent:
    """Create the high-throughput SEC and transcript extraction specialist on Gemini 2.5 Flash."""
    settings = Settings()
    return Agent(
        name="filing_extraction_specialist",
        model=Gemini(
            model=model_name or settings.extraction_model,
            retry_options=types.HttpRetryOptions(attempts=3),
        ),
        description=(
            "Retrieves SEC 10-K sections, XBRL financial facts and earnings call "
            "transcripts, and reports them verbatim with their sources. Does not "
            "analyse or calculate."
        ),
        instruction=EXTRACTION_AGENT_INSTRUCTION,
        tools=[
            create_sec_edgar_mcp_toolset(),
            get_earnings_call_transcript,
        ],
    )


def create_financial_adk_agent(
    model_name: str | None = None,
    extraction_model_name: str | None = None,
) -> Agent:
    """Create the Root Coordinator Agent on Gemini 2.5 Pro with specialist AgentTool delegation."""
    settings = Settings()
    return Agent(
        name="finance_investment_research_agent",
        model=Gemini(
            model=model_name or settings.coordinator_model,
            retry_options=types.HttpRetryOptions(attempts=3),
        ),
        instruction=FINANCE_AGENT_INSTRUCTION,
        tools=[
            AgentTool(agent=create_filing_extraction_agent(extraction_model_name)),
            query_macro_market_news,
            compute_financial_ratios,
        ],
    )


def create_financial_adk_app(
    agent: Agent | None = None,
    context_cache_config: ContextCacheConfig | None = None,
) -> App:
    """Create the Google ADK App with Vertex AI ContextCacheConfig enabled."""
    settings = Settings()
    root = agent or create_financial_adk_agent()
    return App(
        root_agent=root,
        name="finance_research_app",
        context_cache_config=context_cache_config
        or ContextCacheConfig(
            ttl_seconds=settings.context_cache_ttl_minutes * 60,
            min_tokens=_GEMINI_25_MIN_CACHEABLE_TOKENS,
        ),
    )
