"""
Google ADK (Agent Development Kit) Integration for Investment Research Agent.

Two agents, not one, and they run on different models.

The coordinator plans and synthesises on ``coordinator_model``
(Gemini 2.5 Pro). Retrieval - pulling 10-K sections and earnings-call
transcripts and condensing them into facts - is delegated to a specialist on
``extraction_model`` (Gemini 2.5 Flash), reached through ``AgentTool``.

That split is the point. Retrieval is where the tokens are and where the
reasoning is not: a 10-K section is tens of thousands of tokens of prose from
which a handful of tagged figures need lifting. Paying Pro rates to read it is
waste, and Pro is no better at it. Synthesis is the reverse - little input,
and the judgement that the brief is actually for.

``AgentTool`` rather than ``sub_agents`` deliberately. Transfer would hand the
conversation to Flash and leave it there; the coordinator would never get to
write the brief. As a tool, the specialist answers and control returns.

Context caching is ADK's, configured on the App and performed by
``GeminiContextCacheManager`` against Vertex's ``CachedContent`` API. This
module previously carried a hand-rolled ``ContextCachingManager`` that kept an
in-process dict, estimated token counts, and reported savings from a hardcoded
price delta while never calling Vertex at all. It has been deleted.

SEC tools are NOT defined in this module. They are served by
:mod:`src.mcp_servers.sec_edgar_server` and reached over MCP, which is what
ADR-002 specified. Defining local copies as well would create two paths to the
same data that can silently drift apart.
"""

import json
import os
import sys

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

# Gemini will not cache a prefix below this no matter what ADK is configured
# with: 2048 tokens for the 2.5 family, 4096 for 3.x. Written down rather than
# left to ADK's default of 0 because the number is the whole story - a single
# short exchange is never cached, and a reader checking why the hit rate is
# zero should not have to find that out from a blog post.
_GEMINI_25_MIN_CACHEABLE_TOKENS = 2048

# Initialize tool dependencies for the natively-hosted tools. SEC retrieval has
# no client here: it lives in the MCP server subprocess.
_transcript_client = TranscriptClient()
_search_client = MacroContextClient()
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

    if not transcript.get("available"):
        # No citation key at all: nothing here is citable, and an empty
        # citation string invites the model to fill one in.
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
    # Every ratio goes through the Decimal engine - the same one the REST path
    # uses - so the two paths cannot disagree on a margin by a float rounding.
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


EXTRACTION_AGENT_INSTRUCTION = """You are a filings extraction specialist. You retrieve source documents and report what they say. You do not analyse, recommend, or synthesise.

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


FINANCE_AGENT_INSTRUCTION = """You are the Senior Wall Street Equity Research Analyst Agent built with Google ADK and Gemini 2.5 Pro.
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


def create_filing_extraction_agent(model_name: str | None = None) -> Agent:
    """The retrieval half, on the cheap model.

    Holds both high-volume tools: SEC over MCP, and earnings-call transcripts.
    Between them they account for essentially all of the input tokens in a
    brief, and none of the judgement.
    """
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
    """Creates the coordinator: planning, delegation, and synthesis.

    Both models come from ``Settings`` rather than being hard-coded, so the
    Cloud Run revision's ``COORDINATOR_MODEL`` and ``EXTRACTION_MODEL`` env vars
    finally mean something. They were set by Terraform and read by nothing.

    The calculator stays here rather than on the specialist. Arithmetic is the
    one thing in this system that must not be done by a language model at all,
    and keeping it beside the synthesis step is what makes "never guess a
    margin" enforceable in one place.
    """
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
    """Creates an ADK App wrapping the financial research agent.

    Context caching is on, and it is ADK's real implementation - it calls
    Vertex's ``CachedContent`` API through ``GeminiContextCacheManager``. Two
    honest caveats, because the predecessor of this code reported savings it
    had not made:

    * Nothing is cached on the first turn of a session. ADK gates on the
      *previous* request's measured token count, so a single-shot brief - which
      is what most API traffic looks like - never benefits.
    * Gemini will not cache a prefix under 2048 tokens for the 2.5 family
      regardless of configuration.

    Both agents get their own cache, which is the reason to configure this at
    all once there are two of them: every hop between the coordinator and the
    specialist swaps the system instruction and the tool set, so without a
    cache each one re-sends its whole prefix.
    """
    settings = Settings()
    root = agent or create_financial_adk_agent()
    return App(
        root_agent=root,
        name="finance_research_app",
        # ContextCacheConfig is marked experimental in ADK 2.9. Accepted: the
        # alternative is calling CachedContent.create by hand and reimplementing
        # the invalidation ADK already does on every prefix change.
        context_cache_config=context_cache_config
        or ContextCacheConfig(
            ttl_seconds=settings.context_cache_ttl_minutes * 60,
            min_tokens=_GEMINI_25_MIN_CACHEABLE_TOKENS,
        ),
    )
