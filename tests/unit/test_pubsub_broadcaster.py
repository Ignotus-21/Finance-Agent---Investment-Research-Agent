"""
Unit tests for `PubSubBroadcaster`.

The class these cover used to append a dict to a list and return it, so there
was nothing to assert beyond the dict's own shape - which is exactly why the
missing publish went unnoticed. These tests pin the three behaviours that
matter now: offline mode must not touch the network, a real publish must go to
the configured topic, and a publish failure must not propagate into the request
that produced the brief.
"""

import asyncio
import json

import pytest

from src.config import Settings
from src.observability.pubsub_broadcaster import (
    _EVENT_TAIL_SIZE,
    PubSubBroadcaster,
)

LIVE_SETTINGS_KWARGS = {
    "offline_mode": False,
    # Settings rejects the placeholder contact when offline_mode is false.
    "sec_edgar_user_agent": "IRA Test Suite tests@example.com",
    "gcp_project_id": "test-project",
    "pubsub_topic_id": "ira-research-events-test",
}

BROADCAST_KWARGS = {
    "brief_id": "brief-abc-123",
    "ticker": "NVDA",
    "fiscal_year": 2024,
    "metrics_count": 5,
    "citations_count": 8,
    "risk_categories": ["Supply Chain", "Geopolitical"],
}


class _FakeFuture:
    """Stands in for the concurrent.futures Future publish() returns."""

    def __init__(self, message_id: str | None = None, error: Exception | None = None):
        self._message_id = message_id
        self._error = error

    def result(self, timeout: float | None = None) -> str:
        if self._error is not None:
            raise self._error
        assert self._message_id is not None
        return self._message_id


class _FakePublisher:
    def __init__(self, future: _FakeFuture):
        self._future = future
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def publish(self, topic: str, data: bytes, **attributes: str) -> _FakeFuture:
        self.calls.append((topic, data, attributes))
        return self._future


def _live_broadcaster(future: _FakeFuture) -> tuple[PubSubBroadcaster, _FakePublisher]:
    broadcaster = PubSubBroadcaster(Settings(**LIVE_SETTINGS_KWARGS))
    publisher = _FakePublisher(future)
    broadcaster._publisher = publisher
    return broadcaster, publisher


@pytest.mark.asyncio
async def test_offline_mode_records_the_event_without_publishing() -> None:
    """CI, tests and the eval gate run offline and must not need credentials."""
    broadcaster = PubSubBroadcaster(Settings(offline_mode=True))

    # No publisher is installed: if the code tried to build one, the missing
    # credentials would surface here rather than in CI.
    event = await broadcaster.broadcast_brief_completed(**BROADCAST_KWARGS)

    assert event["published"] is False
    assert event["publish_skipped_reason"] == "offline_mode"
    assert broadcaster._publisher is None
    assert len(broadcaster.published_events) == 1


@pytest.mark.asyncio
async def test_live_mode_publishes_to_the_configured_topic() -> None:
    broadcaster, publisher = _live_broadcaster(_FakeFuture(message_id="msg-1"))

    event = await broadcaster.broadcast_brief_completed(**BROADCAST_KWARGS)

    assert event["published"] is True
    assert event["message_id"] == "msg-1"

    topic, data, attributes = publisher.calls[0]
    assert topic == "projects/test-project/topics/ira-research-events-test"

    # Consumers filter on attributes without deserialising the body, so a
    # rename here is a breaking change for them.
    assert attributes == {
        "event_type": "research.brief.completed",
        "ticker": "NVDA",
        "fiscal_year": "2024",
    }

    decoded = json.loads(data.decode("utf-8"))
    assert decoded["event_type"] == "research.brief.completed"
    assert decoded["payload"]["brief_id"] == "brief-abc-123"
    assert decoded["payload"]["detected_risks"] == ["Supply Chain", "Geopolitical"]


@pytest.mark.asyncio
async def test_publish_failure_is_reported_not_raised() -> None:
    """
    The brief is already computed and audited by the time we broadcast. Losing
    a notification is a degradation; failing the caller's request over it is
    not an acceptable trade.
    """
    broadcaster, _ = _live_broadcaster(_FakeFuture(error=RuntimeError("topic gone")))

    event = await broadcaster.broadcast_brief_completed(**BROADCAST_KWARGS)

    assert event["published"] is False
    assert event["publish_error"] == "RuntimeError"
    assert "message_id" not in event


@pytest.mark.asyncio
async def test_a_hanging_publish_does_not_hang_the_request(monkeypatch) -> None:
    """A Pub/Sub slowdown must be bounded, not inherited by API latency."""
    monkeypatch.setattr(
        "src.observability.pubsub_broadcaster._PUBLISH_TIMEOUT_SECONDS", 0.05
    )

    class _HangingFuture(_FakeFuture):
        def result(self, timeout: float | None = None) -> str:
            import time

            # Long enough to blow the 50ms budget, short enough that the loop's
            # executor shutdown does not stall the suite waiting on the thread.
            time.sleep(0.4)
            return "never"

    broadcaster, _ = _live_broadcaster(_HangingFuture())

    event = await asyncio.wait_for(
        broadcaster.broadcast_brief_completed(**BROADCAST_KWARGS), timeout=2
    )

    assert event["published"] is False
    assert event["publish_error"] == "TimeoutError"


@pytest.mark.asyncio
async def test_event_tail_is_bounded() -> None:
    """
    The tail was an unbounded list. On a warm revision that is a slow leak
    which only shows up in production, weeks in.
    """
    broadcaster = PubSubBroadcaster(Settings(offline_mode=True))

    for index in range(_EVENT_TAIL_SIZE + 10):
        await broadcaster.broadcast_brief_completed(
            **{**BROADCAST_KWARGS, "brief_id": f"brief-{index}"}
        )

    assert len(broadcaster.published_events) == _EVENT_TAIL_SIZE
    assert broadcaster.published_events[-1]["payload"]["brief_id"] == (
        f"brief-{_EVENT_TAIL_SIZE + 9}"
    )
