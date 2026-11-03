"""
FastAPI Application Entrypoint.
Initializes structured logging, OpenTelemetry tracing, API routes,
global exception handlers, and optional ADK developer UI mount.
"""

import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.routes import router
from src.config import settings
from src.core.exceptions import FinancialAgentException
from src.observability.logging_config import configure_logging
from src.observability.tracer import configure_tracing

ADK_AGENTS_DIR = "src/agents"
ADK_URL_PREFIX = "/adk"


def _mount_adk_web(app: FastAPI) -> None:
    """Mount the Google ADK FastAPI runtime and developer UI under /adk."""
    from google.adk.cli.fast_api import get_fast_api_app

    adk_app = get_fast_api_app(
        agents_dir=ADK_AGENTS_DIR,
        web=True,
        url_prefix=ADK_URL_PREFIX,
    )
    app.mount(ADK_URL_PREFIX, adk_app)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    configure_logging(settings)

    app = FastAPI(
        title="Autonomous Investment Research Intelligence Agent (IRA) API",
        version="1.0.0",
        description="Enterprise multi-agent equity due diligence API built on Google Cloud Platform and ADK.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    @app.exception_handler(FinancialAgentException)
    async def financial_agent_exception_handler(request: Request, exc: FinancialAgentException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            },
        )

    app.include_router(router)
    configure_tracing(app, settings)

    if settings.enable_adk_web:
        _mount_adk_web(app)

    return app


app = create_app()
