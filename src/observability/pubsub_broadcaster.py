"""
Google Cloud Pub/Sub Event Broadcaster.

Publishes `research.brief.completed` events so downstream consumers (alerting,
portfolio rebalancing, the analyst notification fan-out) can react without
polling the API.

This module used to append the event to an in-process list and return it. The
Terraform topic existed, the runtime service account held ``pubsub.publisher``,
and nothing was ever published - the only observable difference between a
working broadcaster and a broken one was a list nobody read. It now publishes
for real.

Two properties are deliberate:

* **Offline mode short-circuits.** Tests, CI and the evaluation gate run with
  ``OFFLINE_MODE=true`` and must not need credentials or a topic.
* **A publish failure never fails the research request.** The brief is already
  computed and audited by the time we get here; losing a notification is a
  degradation, not an error. Failures surface as a structured stderr record,
  and the returned event carries ``published=False`` so a caller (or a test)
  can tell the difference.
"""

import asyncio
import collections
import datetime
import json
import sys
from typing import Any

from src.config import Settings

# Bounded in-process tail of what we emitted. Previously an unbounded list, so
# on a warm revision it grew for the lifetime of the container.
_EVENT_TAIL_SIZE = 256

# Publishing is fire-and-confirm: we wait briefly for the server-assigned
# message id so a misconfigured topic is loud, but we cap the wait so a Pub/Sub
# slowdown cannot inflate API latency.
_PUBLISH_TIMEOUT_SECONDS = 5.0


class PubSubBroadcaster:
    """Publishes completed research brief events to Google Cloud Pub/Sub."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.published_events: collections.deque[dict[str, Any]] = collections.deque(
            maxlen=_EVENT_TAIL_SIZE
        )
        self._publisher: Any | None = None

    @property
    def topic_path(self) -> str:
        """Fully-qualified topic name this broadcaster targets."""
        return (
            f"projects/{self.settings.gcp_project_id}"
            f"/topics/{self.settings.pubsub_topic_id}"
        )

    def _get_publisher(self) -> Any:
        """
        Lazily construct the publisher client.

        Constructed on first use rather than in ``__init__`` because importing
        this module must not require credentials - ``src.api.routes`` imports a
        module-level singleton at process start, including under pytest.
        """
        if self._publisher is None:
            # Imported as a submodule, not `from google.cloud import pubsub_v1`:
            # google.cloud is a namespace package, so the `from` form is an
            # attribute lookup that static analysis cannot resolve.
            import google.cloud.pubsub_v1 as pubsub_v1

            self._publisher = pubsub_v1.PublisherClient()
        return self._publisher

    async def broadcast_brief_completed(
        self,
        brief_id: str,
        ticker: str,
        fiscal_year: int,
        metrics_count: int,
        citations_count: int,
        risk_categories: list[str]
    ) -> dict[str, Any]:
        """Publishes `research.brief.completed` event to Pub/Sub topic."""
        event: dict[str, Any] = {
            "event_type": "research.brief.completed",
            "event_id": f"evt-{brief_id}",
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "topic": self.settings.pubsub_topic_id,
            "payload": {
                "brief_id": brief_id,
                "ticker": ticker,
                "fiscal_year": fiscal_year,
                "metrics_count": metrics_count,
                "citations_count": citations_count,
                "detected_risks": risk_categories
            }
        }

        if self.settings.offline_mode:
            event["published"] = False
            event["publish_skipped_reason"] = "offline_mode"
        else:
            event.update(await self._publish(event))

        self.published_events.append(event)
        return event

    async def _publish(self, event: dict[str, Any]) -> dict[str, Any]:
        """Publishes one event, converting any failure into a reported outcome."""
        try:
            publisher = self._get_publisher()
            future = publisher.publish(
                self.topic_path,
                json.dumps(event).encode("utf-8"),
                event_type=event["event_type"],
                ticker=str(event["payload"]["ticker"]),
                fiscal_year=str(event["payload"]["fiscal_year"]),
            )
            # publish() batches and returns a concurrent.futures Future whose
            # result() blocks; off-loading it keeps the event loop free.
            message_id = await asyncio.wait_for(
                asyncio.to_thread(future.result),
                timeout=_PUBLISH_TIMEOUT_SECONDS,
            )
            return {"published": True, "message_id": message_id}
        except Exception as exc:  # noqa: BLE001 - notification must not fail the brief
            print(
                json.dumps({
                    "severity": "ERROR",
                    "message": "Pub/Sub broadcast failed; brief was still returned.",
                    "topic": self.topic_path,
                    "event_id": event["event_id"],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }),
                file=sys.stderr,
            )
            return {"published": False, "publish_error": type(exc).__name__}


broadcaster = PubSubBroadcaster()
