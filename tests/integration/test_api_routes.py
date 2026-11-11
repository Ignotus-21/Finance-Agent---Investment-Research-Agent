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
    body = res_ready.json()
    assert body["status"] == "READY"

    # Readiness must report which data path the revision is on. This assertion
    # replaces one against a hard-coded "vertex_ai": "CONNECTED" literal, which
    # could not have failed and therefore verified nothing.
    assert body["runtime"]["offline_mode"] is True
    assert "environment" in body["runtime"]
    assert body["dependencies"]["circuit_breaker"] in {"CLOSED", "OPEN", "HALF_OPEN"}


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


@pytest.mark.asyncio
async def test_egress_screening_blocks_brief_with_422(monkeypatch: pytest.MonkeyPatch):
    """A brief whose narrative fails Model Armor egress screening is withheld, not returned."""
    from src.api import routes
    from src.core.exceptions import ResponseBlockedException

    screened: dict[str, str] = {}

    async def _blocking_screen(text: str, user_prompt: str | None = None) -> None:
        screened["text"] = text
        screened["prompt"] = user_prompt or ""
        raise ResponseBlockedException(reason="Model Armor matched filters: malicious_uris", matched_filters=["malicious_uris"])

    verdicts: list[str] = []
    original_log = routes.audit_logger.log_research_execution

    async def _capture(**kwargs):
        verdicts.append(kwargs["guardrail_verdict"])
        return await original_log(**kwargs)

    container = await routes.get_container()
    monkeypatch.setattr(container.guardrail, "screen_response_async", _blocking_screen)
    monkeypatch.setattr(routes.audit_logger, "log_research_execution", _capture)

    headers = {"Authorization": "Bearer test-valid-analyst-token"}
    res = await async_client_for(headers)

    assert res.status_code == 422
    assert res.json()["detail"].startswith("Response Blocked:")
    assert "AAPL" in screened["prompt"]
    assert screened["text"]
    assert verdicts == ["REJECT_RESPONSE"]


async def async_client_for(headers: dict[str, str]):
    from httpx import ASGITransport

    from src.api.app import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/v1/research/equity",
            json={"ticker": "AAPL", "fiscal_year": 2024, "focus_areas": ["Services_Margin"]},
            headers=headers,
        )
