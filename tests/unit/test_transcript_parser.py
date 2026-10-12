"""
Unit tests for Transcript Parser and Speaker Segmentation.
"""

import pytest

from src.tools.transcript_parser import TranscriptClient


@pytest.mark.asyncio
async def test_transcript_parser_speaker_segmentation():
    """Verify isolation of CFO and CEO remarks vs Analyst Q&A."""
    client = TranscriptClient()
    res = await client.get_transcript("AAPL", "Q4_2024")
    assert res["ticker"] == "AAPL"
    assert res["quarter"] == "Q4_2024"
    assert len(res["prepared_remarks"]) >= 2
    assert len(res["analyst_qa"]) >= 2

    # Check CFO attribution
    cfo_remarks = [r for r in res["prepared_remarks"] if "Luca Maestri" in r["speaker_name"]]
    assert len(cfo_remarks) == 1
    assert "74.0%" in cfo_remarks[0]["text"]
    assert cfo_remarks[0]["sentiment"] > 0.5


@pytest.mark.asyncio
async def test_transcript_parser_unknown_ticker_is_unavailable_not_invented():
    """A ticker with no transcript must come back empty, never with a generated quote."""
    client = TranscriptClient()
    res = await client.get_transcript("XYZ", "Q3_2024")
    assert res["ticker"] == "XYZ"
    assert res["available"] is False
    assert res["prepared_remarks"] == []
    assert res["analyst_qa"] == []
    assert res["provenance_signature"] is None


@pytest.mark.asyncio
async def test_adk_transcript_tool_emits_no_citation_when_unavailable():
    """The ADK tool must give the model nothing to cite for a missing transcript."""
    import json

    from src.agents.adk_agent import get_earnings_call_transcript

    payload = json.loads(await get_earnings_call_transcript("XYZ", "Q3_2024"))
    assert payload["available"] is False
    assert "citation" not in payload


@pytest.mark.asyncio
async def test_macro_client_does_not_invent_ticker_news():
    """Tickers outside the curated corpus get the global backdrop only, no generated headline."""
    from src.tools.search_grounding import VertexSearchClient

    results = await VertexSearchClient().query_market_context("XYZ", ["rates"])
    assert results, "global macro backdrop should still be returned"
    assert not any("XYZ" in (r.get("title", "") + r.get("url", "")) for r in results)
