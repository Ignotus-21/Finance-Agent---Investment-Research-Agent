# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
from typing import Optional
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types


def fetch_sec_filing_section(ticker: str, fiscal_year: int = 2024, section: str = "Item 7") -> str:
    """Simulates SEC EDGAR retrieval for financial disclosures and MD&A.

    Args:
        ticker: Equity stock ticker (e.g. AAPL, MSFT, GOOGL, NVDA, SYNTH).
        fiscal_year: Fiscal reporting year (e.g. 2024).
        section: SEC 10-K section (e.g. 'Item 1', 'Item 7', 'Item 8').

    Returns:
        JSON string containing filing text and SEC citation.
    """
    return json.dumps({
        "ticker": ticker.upper(),
        "fiscal_year": fiscal_year,
        "section": section,
        "content": f"{ticker.upper()} reported strong fiscal {fiscal_year} performance with sustained gross margin expansion.",
        "citation": f"[SEC: {ticker.upper()} 10-K FY{fiscal_year} {section}]"
    })


def analyze_earnings_transcript(ticker: str, quarter: str = "Q4_2024") -> str:
    """Simulates earnings call transcript retrieval and executive commentary analysis.

    Args:
        ticker: Equity stock ticker symbol.
        quarter: Target reporting quarter (e.g. 'Q4_2024').

    Returns:
        JSON string containing executive sentiment, guidance, and citation.
    """
    return json.dumps({
        "ticker": ticker.upper(),
        "quarter": quarter,
        "executive_sentiment": "Constructive / Bullish",
        "guidance": "Management raised full-year operating cash flow outlook.",
        "citation": f"[Earnings Call: {ticker.upper()} {quarter} Executive Remarks]"
    })


def calculate_financial_metrics(revenue: float, net_income: float, operating_income: float) -> str:
    """Computes deterministic financial ratios: Net Margin and Operating Margin.

    Args:
        revenue: Total revenue in USD.
        net_income: Net income in USD.
        operating_income: Operating income in USD.

    Returns:
        JSON string containing computed margins and EPS.
    """
    op_margin = (operating_income / revenue * 100.0) if revenue else 0.0
    net_margin = (net_income / revenue * 100.0) if revenue else 0.0
    return json.dumps({
        "revenue": revenue,
        "operating_margin_pct": round(op_margin, 2),
        "net_margin_pct": round(net_margin, 2),
        "status": "deterministic_verified"
    })


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are the Senior Equity Research Analyst Agent built with Google ADK.
Your mission is to perform institutional-grade equity research and generate verified research briefs.
Always use fetch_sec_filing_section for disclosures, analyze_earnings_transcript for management sentiment,
and calculate_financial_metrics for deterministic calculations. Always cite sources!""",
    tools=[fetch_sec_filing_section, analyze_earnings_transcript, calculate_financial_metrics],
)

app = App(
    root_agent=root_agent,
    name="apple_agent",
)
