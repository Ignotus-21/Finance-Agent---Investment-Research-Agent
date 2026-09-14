"""
Integration tests for FastAPI REST Endpoints.
Verifies OpenAPI 3.1 contracts, OAuth2 Bearer token checks, and response serialization.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_healthz_and_readyz_probes(async_client: AsyncClient):
    """Verify Cloud Run liveness and readiness probe responses."""
    res_health = await async_client.get("/healthz")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "HEALTHY"

    res_ready = await async_client.get("/readyz")
    assert res_ready.status_code == 200
    assert res_ready.json()["status"] == "READY"
    assert res_ready.json()["dependencies"]["vertex_ai"] == "CONNECTED"


@pytest.mark.asyncio
async def test_unauthorized_request_rejected(async_client: AsyncClient):
    """Verify requests lacking Bearer token are rejected with 401."""
    res = await async_client.post(
        "/v1/research/equity",
        json={"ticker": "AAPL", "fiscal_year": 2024}
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_generate_equity_research_success(async_client: AsyncClient):
    """Verify authorized POST /v1/research/equity returns structured brief."""
    headers = {"Authorization": "Bearer test-valid-analyst-token"}
    payload = {
        "ticker": "AAPL",
        "fiscal_year": 2024,
        "focus_areas": ["Services_Margin", "China_Headwinds"]
    }
    res = await async_client.post("/v1/research/equity", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["ticker"] == "AAPL"
    assert data["fiscal_year"] == 2024
    assert len(data["citations"]) > 0
    assert "brief_id" in data


@pytest.mark.asyncio
async def test_extract_filings_success(async_client: AsyncClient):
    """Verify POST /v1/research/filings endpoint."""
    headers = {"Authorization": "Bearer test-valid-analyst-token"}
    payload = {
        "ticker": "AAPL",
        "fiscal_year": 2024,
        "form": "10-K",
        "sections": ["INCOME_STATEMENT", "BALANCE_SHEET"]
    }
    res = await async_client.post("/v1/research/filings", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "INCOME_STATEMENT" in data["sections"]
    assert "BALANCE_SHEET" in data["sections"]
