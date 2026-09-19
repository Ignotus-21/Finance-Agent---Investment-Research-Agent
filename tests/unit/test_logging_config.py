"""
Tests for structured stdlib logging.

These assert on what Cloud Logging actually consumes - a single line of JSON
carrying a `severity` it recognises - rather than on the formatter having been
constructed. The gap this closes is exactly the kind that looks configured and
reports nothing: before it, a library logging at WARNING was indistinguishable
from one logging at DEBUG, and a `PermissionDenied` traceback from the Cloud
Trace exporter went unnoticed for hours.
"""

import json
import logging

import pytest

from src.config import Settings
from src.observability import logging_config
from src.observability.logging_config import CloudLoggingFormatter, configure_logging


@pytest.fixture
def formatter() -> CloudLoggingFormatter:
    return CloudLoggingFormatter("a-real-project")


def _record(level: int, msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("some.library", level, "f.py", 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_output_is_a_single_line_of_json(formatter: CloudLoggingFormatter) -> None:
    """Cloud Logging parses one JSON object per line; a newline splits the entry."""
    line = formatter.format(_record(logging.INFO, "hello"))

    assert "\n" not in line
    assert json.loads(line)["message"] == "hello"


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (logging.DEBUG, "DEBUG"),
        (logging.INFO, "INFO"),
        (logging.WARNING, "WARNING"),
        (logging.ERROR, "ERROR"),
        (logging.CRITICAL, "CRITICAL"),
    ],
)
def test_severity_is_carried_rather_than_inferred_from_the_stream(
    formatter: CloudLoggingFormatter, level: int, expected: str
) -> None:
    """
    The whole point of the module. Without it every one of these arrives as
    INFO, because that is what the Cloud Run agent infers from stdout, and no
    severity-based alert can distinguish them.
    """
    assert json.loads(formatter.format(_record(level, "x")))["severity"] == expected


def test_an_unmapped_level_does_not_silently_become_low_severity(
    formatter: CloudLoggingFormatter,
) -> None:
    """A custom level must not land somewhere that sorts below INFO unnoticed."""
    record = _record(logging.INFO, "x")
    record.levelname = "TRACE"  # a level some libraries define themselves

    assert json.loads(formatter.format(record))["severity"] == "DEFAULT"


def test_exception_text_is_included_in_the_message(
    formatter: CloudLoggingFormatter,
) -> None:
    """
    The traceback is the payload. This is the case that actually mattered: the
    Cloud Trace exporter's PermissionDenied was a traceback and nothing else.
    """
    try:
        raise PermissionError("403 cloudtrace.traces.patch denied")
    except PermissionError:
        import sys

        record = _record(logging.ERROR, "export failed")
        record.exc_info = sys.exc_info()

    payload = json.loads(formatter.format(record))

    assert payload["severity"] == "ERROR"
    assert "PermissionError" in payload["message"]
    assert "403 cloudtrace.traces.patch denied" in payload["message"]


def test_extra_fields_are_forwarded_but_record_internals_are_not(
    formatter: CloudLoggingFormatter,
) -> None:
    """`extra=` is how callers attach queryable context; internals are noise."""
    payload = json.loads(formatter.format(_record(logging.INFO, "x", ticker="NVDA")))

    assert payload["ticker"] == "NVDA"
    for internal in ("args", "msg", "levelno", "pathname", "exc_info"):
        assert internal not in payload


def test_unserialisable_extra_costs_an_ugly_line_not_a_lost_one(
    formatter: CloudLoggingFormatter,
) -> None:
    """A bad `extra=` value must never take the log entry down with it."""

    class NotSerialisable:
        def __repr__(self) -> str:
            return "<obj>"

    payload = json.loads(formatter.format(_record(logging.INFO, "x", thing=NotSerialisable())))

    assert payload["thing"] == "<obj>"


def test_configure_logging_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    uvicorn configures logging on worker start and app factories are called
    repeatedly under pytest. Stacking handlers would duplicate every line once
    per call - which reads as the service doing the work twice.
    """
    monkeypatch.setattr(logging_config, "_CONFIGURED", False)
    root = logging.getLogger()
    original = root.handlers[:]
    original_level = root.level
    try:
        settings = Settings(offline_mode=True, gcp_project_id="a-real-project")
        configure_logging(settings)
        after_first = len(root.handlers)

        monkeypatch.setattr(logging_config, "_CONFIGURED", True)
        configure_logging(settings)

        assert after_first == 1
        assert len(root.handlers) == after_first
    finally:
        root.handlers = original
        root.setLevel(original_level)


def test_uvicorn_loggers_are_made_to_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    uvicorn's loggers ship with `propagate = False` and their own handlers, so
    configuring the root logger alone leaves access logs unstructured - the
    single largest source of log volume in the service.
    """
    monkeypatch.setattr(logging_config, "_CONFIGURED", False)
    root = logging.getLogger()
    original = root.handlers[:]
    access = logging.getLogger("uvicorn.access")
    original_propagate = access.propagate
    try:
        access.propagate = False
        configure_logging(Settings(offline_mode=True, gcp_project_id="a-real-project"))

        assert access.propagate is True
        assert access.handlers == []
    finally:
        root.handlers = original
        access.propagate = original_propagate
