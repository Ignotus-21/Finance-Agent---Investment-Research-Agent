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


def current_trace_context(project_id: str) -> dict[str, str | bool]:
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
        # A real JSON boolean, not "true"/"false". Cloud Logging only promotes
        # this special field when it is typed correctly; given a string it
        # leaves it sitting in jsonPayload and the entry's `traceSampled` stays
        # unset. Verified against the live deployment, where the string form
        # appeared verbatim in the payload and promoted nothing.
        "logging.googleapis.com/trace_sampled": bool(span_context.trace_flags.sampled),
    }


def _build_tracer_provider(settings: Settings) -> Any:
    """Construct the provider - resource and sampler only, no exporter.

    Split out because the global provider can only be set once per process,
    which makes the sampling decision - the part that was actually wrong in
    production - untestable while it is welded to `set_tracer_provider`.

    The exporter deliberately stays in `configure_tracing`: building a
    `CloudTraceSpanExporter` constructs a real gRPC client that resolves
    credentials and calls out on flush. A unit test that reached for one would
    need either credentials or a mock, and the first attempt at this test
    produced `404 projects/a-real-project does not exist` from a background
    export thread. Sampling is decided here; talking to Google is decided
    there.
    """
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON

    resource = Resource.create({
        "service.name": settings.app_name,
        "service.namespace": settings.environment,
    })
    return TracerProvider(
        resource=resource,
        # Explicitly ALWAYS_ON, not the default ParentBased(ALWAYS_ON).
        #
        # Every request here arrives through Google's front end, which sets
        # `traceparent` with its own sampling decision - and that decision is
        # "no" for the overwhelming majority of requests. ParentBased honours
        # it, so the span is created (the audit record gets a valid, correctly
        # formatted trace id) and then never exported. Measured on the live
        # deployment: of five research requests, two were sampled upstream and
        # resolved in Cloud Trace; three did not exist there at all, while
        # their audit records still advertised a trace link.
        #
        # That is the original defect wearing a better disguise - a compliance
        # record whose trace link resolves to nothing. An audit trail that is
        # only navigable for a random ~40% of requests is not an audit trail.
        # Volume is low and Cloud Trace's free tier is 2.5M spans/month, so
        # sampling buys nothing worth this.
        sampler=ALWAYS_ON,
    )


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
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = _build_tracer_provider(settings)
    # Batched, not simple: a synchronous export would put a Cloud Trace round
    # trip on the request path, and a tracing outage must never become a
    # latency incident.
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
