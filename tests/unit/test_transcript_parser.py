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
async def test_transcript_parser_fallback():
    """Verify generic transcript generation for arbitrary tickers."""
    client = TranscriptClient()
    res = await client.get_transcript("XYZ", "Q3_2024")
    assert res["ticker"] == "XYZ"
    assert len(res["prepared_remarks"]) >= 1
