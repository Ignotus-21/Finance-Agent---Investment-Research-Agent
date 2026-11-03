"""
OpenTelemetry distributed tracing configuration and Cloud Logging trace correlation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.config import Settings

if TYPE_CHECKING:  # pragma: no cover - import only for type checking
    from fastapi import FastAPI

_CONFIGURED = False


def current_trace_context(project_id: str) -> dict[str, str | bool]:
    """Return Google Cloud Logging fields linking a log entry to the active trace span."""
    from opentelemetry import trace

    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return {}

    return {
        "logging.googleapis.com/trace": (
            f"projects/{project_id}/traces/{span_context.trace_id:032x}"
        ),
        "logging.googleapis.com/spanId": f"{span_context.span_id:016x}",
        "logging.googleapis.com/trace_sampled": bool(span_context.trace_flags.sampled),
    }


def _build_tracer_provider(settings: Settings) -> Any:
    """Construct the OpenTelemetry TracerProvider with service resource attributes and ALWAYS_ON sampling."""
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON

    resource = Resource.create(
        {
            "service.name": settings.app_name,
            "service.namespace": settings.environment,
        }
    )
    return TracerProvider(
        resource=resource,
        sampler=ALWAYS_ON,
    )


def configure_tracing(app: FastAPI, settings: Settings | None = None) -> bool:
    """Configure the OpenTelemetry tracer provider and instrument the FastAPI application."""
    global _CONFIGURED

    settings = settings or Settings()

    if not settings.enable_cloud_trace or settings.offline_mode:
        return False

    if _CONFIGURED:
        return True

    from opentelemetry import trace
    from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = _build_tracer_provider(settings)
    provider.add_span_processor(
        BatchSpanProcessor(CloudTraceSpanExporter(project_id=settings.gcp_project_id))
    )
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")

    _CONFIGURED = True
    return True


def get_tracer(name: str = "ira") -> Any:
    """Return an OpenTelemetry tracer for manual span instrumentation."""
    from opentelemetry import trace

    return trace.get_tracer(name)
