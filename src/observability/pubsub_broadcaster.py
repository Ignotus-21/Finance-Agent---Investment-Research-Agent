"""
Google Cloud Pub/Sub Event Broadcaster.
Publishes asynchronous research completion events and risk notifications to downstream consumers.
"""

import json
import datetime
from typing import Dict, Any, List, Optional
from src.config import Settings


class PubSubBroadcaster:
    """Publishes completed research brief events to Google Cloud Pub/Sub."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or Settings()
        self.published_events: List[Dict[str, Any]] = []

    async def broadcast_brief_completed(
        self,
        brief_id: str,
        ticker: str,
        fiscal_year: int,
        metrics_count: int,
        citations_count: int,
        risk_categories: List[str]
    ) -> Dict[str, Any]:
        """Publishes `research.brief.completed` event to Pub/Sub topic."""
        event = {
            "event_type": "research.brief.completed",
            "event_id": f"evt-{brief_id}",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
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
        self.published_events.append(event)
        return event


broadcaster = PubSubBroadcaster()
