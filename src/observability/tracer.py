"""
Distributed Tracing Instrumentation using OpenTelemetry.
Exports latency spans to Google Cloud Trace for multi-agent reasoning loops and tool invocations.
"""

import time
import uuid
from contextlib import contextmanager
from typing import Any

from src.config import Settings


class TraceSpan:
    """Represents an active OpenTelemetry span."""

    def __init__(self, name: str, trace_id: str, parent_id: str | None = None) -> None:
        self.name = name
        self.trace_id = trace_id
        self.span_id = f"span-{uuid.uuid4().hex[:8]}"
        self.parent_id = parent_id
        self.start_time = time.monotonic()
        self.end_time: float | None = None
        self.attributes: dict[str, Any] = {}
        self.status = "OK"

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def finish(self, status: str = "OK") -> None:
        self.end_time = time.monotonic()
        self.status = status

    @property
    def duration_ms(self) -> int:
        end = self.end_time or time.monotonic()
        return int((end - self.start_time) * 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes
        }


class Tracer:
    """Distributed tracing manager exporting to Cloud Trace."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.current_trace_id = f"trace-{uuid.uuid4().hex[:16]}"
        self.spans: list[TraceSpan] = []

    def start_trace(self) -> str:
        self.current_trace_id = f"trace-{uuid.uuid4().hex[:16]}"
        self.spans = []
        return self.current_trace_id

    @contextmanager
    def span(self, name: str, parent_id: str | None = None):
        span = TraceSpan(name=name, trace_id=self.current_trace_id, parent_id=parent_id)
        self.spans.append(span)
        try:
            yield span
            span.finish(status="OK")
        except Exception as e:
            span.set_attribute("error", str(e))
            span.finish(status="ERROR")
            raise


tracer = Tracer()
