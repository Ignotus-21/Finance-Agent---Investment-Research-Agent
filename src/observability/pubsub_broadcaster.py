"""
Google Cloud Pub/Sub Event Broadcaster.
Publishes `research.brief.completed` events so downstream consumers can react
asynchronously without polling the API.
"""

import asyncio
import collections
import datetime
import json
import sys
from typing import Any

from src.config import Settings

_EVENT_TAIL_SIZE = 256
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
        """Lazily construct the Google Cloud Pub/Sub publisher client."""
        if self._publisher is None:
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
        risk_categories: list[str],
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
                "detected_risks": risk_categories,
            },
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
            message_id = await asyncio.wait_for(
                asyncio.to_thread(future.result),
                timeout=_PUBLISH_TIMEOUT_SECONDS,
            )
            return {"published": True, "message_id": message_id}
        except Exception as exc:  # noqa: BLE001
            print(
                json.dumps(
                    {
                        "severity": "ERROR",
                        "message": "Pub/Sub broadcast failed; brief was still returned.",
                        "topic": self.topic_path,
                        "event_id": event["event_id"],
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                ),
                file=sys.stderr,
            )
            return {"published": False, "publish_error": type(exc).__name__}


broadcaster = PubSubBroadcaster()
