"""
Tests for tracing.

The version of this file that these replace asserted that a hand-rolled
`Tracer` class stored the spans it had just been handed. It passed against an
implementation that had no SDK, no exporter and no callers, while its docstring
claimed export to Cloud Trace - so the test suite's only opinion about tracing
was that a list could hold objects.

What matters now is the wiring: does the exporter get installed when it should,
does it stay out of the way when it should not, and does the trace id that
reaches an audit record actually point at a trace.
"""

import pytest
from fastapi import FastAPI

import src.observability.tracer as tracer_module
from src.config import Settings
from src.observability.tracer import (
    configure_tracing,
    current_trace_context,
    get_tracer,
)


@pytest.fixture(autouse=True)
def _reset_provider_guard():
    """OpenTelemetry's global provider is process-wide and set-once.

    Without resetting the module guard between tests, the first test to
    configure tracing would make every later test believe it was already
    configured.
    """
    original = tracer_module._CONFIGURED
    tracer_module._CONFIGURED = False
    yield
    tracer_module._CONFIGURED = original


def test_offline_mode_does_not_configure_tracing() -> None:
    """
    Tests, CI and the eval gate run offline with no credentials.

    An exporter there would retry against a metadata server that is not
    present, turning a hermetic suite into a slow one that fails for reasons
    unrelated to the code under test.
    """
    configured = configure_tracing(
        FastAPI(), Settings(offline_mode=True, enable_cloud_trace=True)
    )

    assert configured is False


def test_tracing_can_be_disabled_explicitly() -> None:
    configured = configure_tracing(
        FastAPI(),
        Settings(
            offline_mode=False,
            enable_cloud_trace=False,
            sec_edgar_user_agent="IRA Test tests@example.com",
        ),
    )

    assert configured is False


def test_no_active_span_yields_no_trace_fields() -> None:
    """
    The field this guards used to be populated with the audit record's own
    uuid4. Cloud Logging accepts any string there and correlates nothing, so
    every audit record carried a trace link that resolved to nothing. Absent is
    better than wrong.
    """
    assert current_trace_context("some-project") == {}


def test_active_span_yields_a_correctly_formatted_trace_resource_name() -> None:
    """Cloud Logging needs `projects/<id>/traces/<32 hex>`, not a bare id."""
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("unit-test-span"):
        fields = current_trace_context("adis-workshop")

    assert fields["logging.googleapis.com/trace"].startswith(
        "projects/adis-workshop/traces/"
    )
    trace_hex = fields["logging.googleapis.com/trace"].rsplit("/", 1)[1]
    assert len(trace_hex) == 32
    assert int(trace_hex, 16) != 0
    assert len(fields["logging.googleapis.com/spanId"]) == 16


def test_get_tracer_is_safe_without_a_provider() -> None:
    """
    Instrumented code must not need to know whether tracing is on.

    With no provider installed OpenTelemetry hands back a no-op tracer, so a
    span in a code path that runs offline is free rather than fatal.
    """
    with get_tracer("ira-test").start_as_current_span("noop") as span:
        assert span is not None
