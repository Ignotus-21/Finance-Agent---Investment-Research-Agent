"""Tests for OpenTelemetry tracing configuration and Cloud Logging trace correlation."""

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
    """Reset the process-wide provider guard between tests."""
    original = tracer_module._CONFIGURED
    tracer_module._CONFIGURED = False
    yield
    tracer_module._CONFIGURED = original


def test_offline_mode_does_not_configure_tracing() -> None:
    """Offline mode must not install an exporter."""
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
    """No active span yields no trace correlation fields."""
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


def test_trace_sampled_is_a_real_boolean() -> None:
    """`trace_sampled` must be a JSON boolean for Cloud Logging to promote it."""
    from opentelemetry.sdk.trace import TracerProvider

    tracer = TracerProvider().get_tracer("test")

    with tracer.start_as_current_span("unit-test-span"):
        fields = current_trace_context("adis-workshop")

    sampled = fields["logging.googleapis.com/trace_sampled"]
    assert isinstance(sampled, bool), f"expected bool, got {type(sampled).__name__}"


def test_a_span_under_an_unsampled_upstream_parent_is_still_recorded() -> None:
    """An unsampled upstream `traceparent` must not suppress span export (ALWAYS_ON sampling)."""
    from opentelemetry.trace import (
        NonRecordingSpan,
        SpanContext,
        TraceFlags,
        set_span_in_context,
    )

    from src.observability.tracer import _build_tracer_provider

    provider = _build_tracer_provider(
        Settings(offline_mode=True, gcp_project_id="a-real-project")
    )

    parent_trace_id = 0x1234_5678_9ABC_DEF0_1234_5678_9ABC_DEF0
    unsampled_parent = set_span_in_context(
        NonRecordingSpan(
            SpanContext(
                trace_id=parent_trace_id,
                span_id=0x0FED_CBA9_8765_4321,
                is_remote=True,
                trace_flags=TraceFlags(TraceFlags.DEFAULT),  # not sampled
            )
        )
    )

    span = provider.get_tracer("test").start_span("child", context=unsampled_parent)
    try:
        assert span.get_span_context().trace_flags.sampled
        assert span.get_span_context().trace_id == parent_trace_id
    finally:
        span.end()


def test_get_tracer_is_safe_without_a_provider() -> None:
    """get_tracer returns a usable no-op tracer when no provider is installed."""
    with get_tracer("ira-test").start_as_current_span("noop") as span:
        assert span is not None
