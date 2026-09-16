"""Integration tests for the SEC EDGAR MCP server.

These are deliberately end-to-end over a real stdio subprocess rather than
calling the decorated functions directly. Calling them in-process would test
the retrieval logic (already covered by ``test_sec_edgar_live.py``) while
proving nothing about what this module actually adds: that a real MCP handshake
succeeds, that the tools are advertised with schemas a model can act on, and
that the payloads survive serialisation across the transport.

Every test runs with ``OFFLINE_MODE=true``, so no network call is made.
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Launched with the interpreter running the tests, so the subprocess picks up
# this virtualenv rather than whatever "python" happens to resolve to.
SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=["-m", "src.mcp_servers.sec_edgar_server"],
    env={
        "OFFLINE_MODE": "true",
        "SEC_USER_AGENT": "IRA Test Suite test@ira-research.cloud.internal",
        # stdio_client does not inherit the parent env, so PYTHONPATH has to be
        # set explicitly for "-m src.mcp_servers..." to resolve.
        "PYTHONPATH": ".",
    },
)


@asynccontextmanager
async def mcp_session() -> AsyncGenerator[ClientSession, None]:
    """Spawn the server subprocess and yield an initialised MCP session."""
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def unwrap(result: Any) -> dict[str, Any]:
    """Pull the tool's dict payload back out of an MCP CallToolResult.

    Prefers ``structured_content`` (the typed channel) and falls back to the
    text block, so assertions do not depend on which of the two the server
    library chooses to populate for a given return annotation.
    """
    if result.structured_content:
        return dict(result.structured_content)
    return dict(json.loads(result.content[0].text))


@pytest.mark.asyncio
async def test_server_advertises_both_sec_tools() -> None:
    """The MCP handshake succeeds and both retrieval tools are discoverable.

    This is what ADR-002 claimed and what was previously untrue: the agent can
    enumerate SEC capabilities over the protocol rather than by importing them.
    """
    async with mcp_session() as session:
        tools = (await session.list_tools()).tools

    assert {tool.name for tool in tools} == {
        "fetch_sec_filing_section",
        "extract_xbrl_financial_facts",
    }


@pytest.mark.asyncio
async def test_advertised_schema_is_usable_by_a_model() -> None:
    """Tool schemas must carry descriptions and correctly typed parameters.

    An untyped or undescribed tool still "works" mechanically, but the model
    cannot choose it or fill its arguments reliably - so this is a correctness
    property, not a style check.
    """
    async with mcp_session() as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}

    fetch = tools["fetch_sec_filing_section"]
    assert fetch.description and "accession" in fetch.description.lower()

    props = fetch.input_schema["properties"]
    assert props["ticker"]["type"] == "string"
    assert props["fiscal_year"]["type"] == "integer"
    # Every other parameter has a default, so ticker must be the only required one.
    assert fetch.input_schema["required"] == ["ticker"]


@pytest.mark.asyncio
async def test_fetch_filing_section_returns_cited_fixture_data() -> None:
    """A round trip returns real fixture data tagged with its provenance."""
    async with mcp_session() as session:
        result = await session.call_tool(
            "fetch_sec_filing_section",
            {"ticker": "AAPL", "fiscal_year": 2024, "section": "INCOME_STATEMENT"},
        )

    assert not result.is_error
    payload = unwrap(result)
    assert payload["data_source"] == "OFFLINE_FIXTURE"
    assert payload["accession_number"] == "0000320193-24-000106"
    assert payload["data"]["revenue_current"] == 391035000000.0


@pytest.mark.asyncio
async def test_synthetic_placeholder_is_labelled_as_such_across_the_transport() -> None:
    """Invented figures must stay distinguishable from filed ones over MCP.

    An unknown ticker/year falls back to generated placeholder arithmetic. That
    is acceptable offline, but only because the provenance label travels with
    it - otherwise the model would cite fabricated revenue as an SEC figure.
    This asserts the label survives serialisation, which is the whole risk.
    """
    async with mcp_session() as session:
        result = await session.call_tool(
            "fetch_sec_filing_section", {"ticker": "AAPL", "fiscal_year": 1970}
        )

    payload = unwrap(result)
    assert payload["data_source"] == "OFFLINE_SYNTHETIC_PLACEHOLDER"
    assert payload["provenance_signature"].startswith("SYNTHETIC:")


@pytest.mark.asyncio
async def test_extract_xbrl_returns_all_three_statements_from_one_filing() -> None:
    """The convenience tool returns all three statements with shared provenance."""
    async with mcp_session() as session:
        result = await session.call_tool(
            "extract_xbrl_financial_facts", {"ticker": "AAPL", "fiscal_year": 2024}
        )

    assert not result.is_error
    payload = unwrap(result)
    assert set(payload["statements"]) == {
        "INCOME_STATEMENT",
        "BALANCE_SHEET",
        "CASH_FLOW",
    }
    assert payload["accession_number"] == "0000320193-24-000106"
    assert payload["data_source"] == "OFFLINE_FIXTURE"


@pytest.mark.asyncio
async def test_missing_filing_is_reported_as_data_not_as_a_protocol_error() -> None:
    """A filing that cannot be located returns a structured, readable error.

    Letting the exception escape through MCP would abort the tool call and
    leave the model unable to tell the analyst why the figure is absent.
    """
    async with mcp_session() as session:
        result = await session.call_tool(
            "fetch_sec_filing_section", {"ticker": "NOT A TICKER!", "fiscal_year": 2024}
        )

    payload = unwrap(result)
    assert payload["error"] == "FILING_NOT_FOUND"
    assert payload["ticker"] == "NOT A TICKER!"
