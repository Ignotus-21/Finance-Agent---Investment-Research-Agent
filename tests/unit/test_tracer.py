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


def test_trace_sampled_is_a_real_boolean() -> None:
    """Cloud Logging only promotes this special field when it is typed right.

    It was emitted as the string "true"/"false". Cloud Logging accepted the
    record, declined to promote the field, and left it sitting in jsonPayload
    where nothing reads it - so the entry's `traceSampled` was never set.
    Confirmed against the live deployment before this was pinned.
    """
    from opentelemetry.sdk.trace import TracerProvider

    tracer = TracerProvider().get_tracer("test")

    with tracer.start_as_current_span("unit-test-span"):
        fields = current_trace_context("adis-workshop")

    sampled = fields["logging.googleapis.com/trace_sampled"]
    assert isinstance(sampled, bool), f"expected bool, got {type(sampled).__name__}"


def test_a_span_under_an_unsampled_upstream_parent_is_still_recorded() -> None:
    """Reproduces the production failure, at the level it actually occurred.

    Google's front end sets `traceparent` with its own sampling decision, and
    that decision is "no" for most requests. Under OpenTelemetry's default
    ParentBased sampler that decision is inherited: the span exists, so the
    audit record gets a valid trace id, and the span is then never exported -
    leaving a compliance record pointing at a trace Cloud Trace has never
    heard of. Measured live before the fix: three of five requests.

    So the assertion is not "the sampler is ALWAYS_ON" - that just restates the
    source. It is that an unsampled upstream parent no longer silences us.
    """
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

    # Exactly what arrives on the wire as `...-00`: a valid remote context
    # carrying a negative sampling decision.
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
        assert span.get_span_context().trace_flags.sampled, (
            "the upstream sampling decision was inherited; this span would "
            "never reach Cloud Trace and its audit record would link nowhere"
        )
        # The parent's trace id must still be honoured, or the span is exported
        # but detached from the request it belongs to.
        assert span.get_span_context().trace_id == parent_trace_id
    finally:
        span.end()


def test_get_tracer_is_safe_without_a_provider() -> None:
    """
    Instrumented code must not need to know whether tracing is on.

    With no provider installed OpenTelemetry hands back a no-op tracer, so a
    span in a code path that runs offline is free rather than fatal.
    """
    with get_tracer("ira-test").start_as_current_span("noop") as span:
        assert span is not None
