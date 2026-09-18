"""
Distributed tracing.

This module used to define a `Tracer` class with a `spans: list[TraceSpan]`,
UUID trace ids of the form ``trace-a1b2c3``, and a docstring promising export
to Google Cloud Trace. It exported nothing. There was no SDK, no exporter and
no processor - `opentelemetry` was declared in `pyproject.toml` and never
imported. Nothing in `src/` called it either: the only references were the
re-export in `src/observability/__init__.py` and one unit test that asserted
the class stored what it had just been handed.

So the previous version could not fail, which is the same defect as a `/readyz`
that returns the literal string "CONNECTED". It is replaced here with the real
thing:

* the OpenTelemetry SDK, with a `TracerProvider` carrying Cloud Run's resource
  attributes so spans land against the right service and revision;
* `CloudTraceSpanExporter`, behind a `BatchSpanProcessor` - batched because a
  synchronous export would put a Cloud Trace round trip on the request path,
  and a tracing outage must never become a latency incident;
* `FastAPIInstrumentor`, so every request is a span without a decorator on
  every handler. Hand-instrumented spans are the ones that get forgotten.

The trace id produced here is what `AuditLogger` stamps onto each audit record,
which is what makes a compliance record clickable through to the request that
produced it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.config import Settings

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from fastapi import FastAPI

# Set once, at startup. Guarded because OpenTelemetry's global provider can
# only be set once per process: a second call is ignored with a warning, and
# under pytest - where app factories are called repeatedly - that warning would
# be the only signal that half the tests traced into a dead provider.
_CONFIGURED = False


def current_trace_context(project_id: str) -> dict[str, str]:
    """Cloud Logging fields that link a log entry to its trace.

    Returns an empty dict when there is no active span, rather than inventing
    an id. The field this replaces was set to the audit record's own UUID -
    accepted by Cloud Logging, formatted wrongly, and therefore matching no
    trace, ever. A missing link is visibly missing; a malformed one looks like
    a working link that just never resolves.
    """
    from opentelemetry import trace

    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return {}

    return {
        # Cloud Logging requires the full resource name, not a bare id.
        "logging.googleapis.com/trace": (
            f"projects/{project_id}/traces/{span_context.trace_id:032x}"
        ),
        "logging.googleapis.com/spanId": f"{span_context.span_id:016x}",
        "logging.googleapis.com/trace_sampled": str(
            bool(span_context.trace_flags.sampled)
        ).lower(),
    }


def configure_tracing(app: FastAPI, settings: Settings | None = None) -> bool:
    """Install the tracer provider and instrument `app`.

    Returns whether tracing was configured, so the caller can log the decision
    instead of leaving an operator to guess why Cloud Trace is empty.
    """
    global _CONFIGURED

    settings = settings or Settings()

    # Offline mode is for tests, CI and the evaluation gate. Those have no
    # credentials and must make no network call, and a tracing exporter that
    # retries against a metadata server that is not there turns a fast test
    # suite into a slow one.
    if not settings.enable_cloud_trace or settings.offline_mode:
        return False

    if _CONFIGURED:
        return True

    from opentelemetry import trace
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({
        "service.name": settings.app_name,
        "service.namespace": settings.environment,
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(CloudTraceSpanExporter(project_id=settings.gcp_project_id))
    )
    trace.set_tracer_provider(provider)

    # `/healthz` and `/readyz` are excluded: Cloud Run probes them every few
    # seconds forever, and paying to store a million identical 2ms spans buys
    # nothing but a bill and a diluted latency histogram.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")

    _CONFIGURED = True
    return True


def get_tracer(name: str = "ira") -> Any:
    """The OpenTelemetry tracer, for spans worth naming by hand.

    Safe to call whether or not `configure_tracing` ran: with no provider
    installed OpenTelemetry returns a no-op tracer, so instrumented code does
    not need to know whether tracing is on.
    """
    from opentelemetry import trace

    return trace.get_tracer(name)
