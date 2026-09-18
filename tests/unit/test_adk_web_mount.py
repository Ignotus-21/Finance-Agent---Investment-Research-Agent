"""
Tests for the optional ADK developer-UI mount.

The agent and the REST contract are two surfaces over the same code, and until
now only one of them was reachable from a deployment: `src/agents/agent.py`
was importable but not mounted, so the agent existed in CI and in `adk web` and
nowhere a reviewer could actually click.

These drive the app through `TestClient` rather than inspecting `app.routes`.
A mounted sub-application is a single opaque route object, so a path-list
assertion would pass while the mount served 404s - which is precisely the
failure worth catching.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.config import Settings


def _client(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> TestClient:
    monkeypatch.setattr("src.api.app.settings", Settings(enable_adk_web=enabled))
    return TestClient(create_app())


def test_adk_is_not_reachable_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The default must stay closed.

    The ADK surface accepts free-text prompts straight to the model. Those do
    not pass through the `/v1` guardrail chain, so a deployment that mounted it
    by accident would have a prompt-injection path its threat model does not
    describe.
    """
    client = _client(monkeypatch, enabled=False)

    assert client.get("/adk/list-apps").status_code == 404
    # The REST contract is unaffected either way.
    assert client.get("/healthz").status_code == 200


def test_adk_serves_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, enabled=True)

    response = client.get("/adk/list-apps")

    assert response.status_code == 200
    # ADK discovers agents by scanning `src/agents`, so this is also a check
    # that the mounted app found the package rather than an empty directory.
    assert response.json() == ["agents"]


def test_dev_ui_is_served_under_the_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    `url_prefix` is passed to ADK as well as the mount path.

    Without it ADK builds absolute asset URLs from the root, so the HTML loads
    and every script it references 404s - a blank page that looks like a
    deployment problem rather than a configuration one.
    """
    client = _client(monkeypatch, enabled=True)

    response = client.get("/adk/dev-ui/")

    assert response.status_code == 200
    assert "<!doctype html>" in response.text.lower()


def test_mounting_adk_does_not_shadow_the_health_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    `/readyz` is what the blue/green cutover gate asserts on. A mount that
    displaced it would turn a deployment check into a check of something else.
    """
    client = _client(monkeypatch, enabled=True)

    assert client.get("/healthz").json()["status"] == "HEALTHY"
    assert client.get("/readyz").json()["status"] == "READY"
