"""
Structured JSON logging configuration for Google Cloud Logging integration.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from src.config import Settings

_LEVEL_TO_SEVERITY = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}

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

        if record.exc_info:
            payload["message"] += "\n" + self.formatException(record.exc_info)

        from src.observability.tracer import current_trace_context

        payload.update(current_trace_context(self._project_id))

        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS:
                payload[key] = value

        return json.dumps(payload, default=str)


def configure_logging(settings: Settings | None = None) -> None:
    """Install the Cloud Logging JSON formatter on the root and uvicorn loggers."""
    global _CONFIGURED

    settings = settings or Settings()

    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CloudLoggingFormatter(settings.gcp_project_id))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    _CONFIGURED = True
