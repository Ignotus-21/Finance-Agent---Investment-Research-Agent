"""
Structured logging for the standard library `logging` module.

`AuditLogger` has always emitted structured JSON, but it is the only thing that
did. The stdlib root logger was configured nowhere, so uvicorn's access logs and
every third-party library's output reached Cloud Logging as a plain
`textPayload` at whatever severity the Cloud Run agent inferred from the stream
- which is `INFO` for stdout and `ERROR` for stderr, and never anything else.

That is not cosmetic. A library logging at `WARNING` was indistinguishable from
one logging at `DEBUG`, so no severity-based log alert could ever be written
against them. It is also precisely how this project lost several hours: the
Cloud Trace exporter was failing every single export with
`403 cloudtrace.traces.patch denied`, and the traceback sat on stderr where
nothing was watching for it.

The formatter emits the special fields Cloud Logging promotes out of
`jsonPayload` onto the entry itself - `severity`, `message`, and the trace
correlation fields - so library logs join the same query surface as the audit
records.

Deliberately still `print`-to-stdout in spirit: no `google-cloud-logging`
client, no network call in the logging path, no credentials. On Cloud Run the
agent does the shipping. See `refrence/checklist.md` §9.1.1.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from src.config import Settings

# Python level names are not Cloud Logging severities. Most happen to collide,
# but `WARNING`/`CRITICAL` do not, and an unmapped name is silently treated as
# DEFAULT severity - which sorts below INFO and hides the entry.
_LEVEL_TO_SEVERITY = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}

# Attributes LogRecord always carries. Anything outside this set was attached by
# the caller via `extra=` and is worth forwarding.
_STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"message", "asctime", "taskName"}

_CONFIGURED = False


class CloudLoggingFormatter(logging.Formatter):
    """Render a LogRecord as a single line of Cloud Logging structured JSON."""

    def __init__(self, project_id: str) -> None:
        super().__init__()
        self._project_id = project_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": _LEVEL_TO_SEVERITY.get(record.levelname, "DEFAULT"),
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Tracebacks belong in `message`. Cloud Error Reporting picks up
        # exceptions from there; as a separate field they are merely decorative.
        if record.exc_info:
            payload["message"] += "\n" + self.formatException(record.exc_info)

        # Correlate library logs with the request that produced them, using the
        # same helper as the audit record so the two agree by construction.
        from src.observability.tracer import current_trace_context

        payload.update(current_trace_context(self._project_id))

        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS:
                payload[key] = value

        # `default=str` because a caller passing a non-serialisable object via
        # `extra=` should cost a slightly ugly log line, not a lost one.
        return json.dumps(payload, default=str)


def configure_logging(settings: Settings | None = None) -> None:
    """Install the JSON formatter on the root logger.

    Idempotent: uvicorn's own logging setup runs on worker start and app
    factories are called repeatedly under pytest, and stacking handlers would
    duplicate every line once per call.
    """
    global _CONFIGURED

    settings = settings or Settings()

    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CloudLoggingFormatter(settings.gcp_project_id))

    root = logging.getLogger()
    # Replace rather than append. uvicorn installs its own handlers, and leaving
    # them attached emits every line twice - once structured, once not.
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    # uvicorn's loggers set propagate=False and carry their own handlers, so the
    # root configuration above would not reach them.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    _CONFIGURED = True
