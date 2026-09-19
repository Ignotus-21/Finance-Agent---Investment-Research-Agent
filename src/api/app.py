"""
FastAPI Application Entrypoint.
Initializes middleware, CORS, routers, and exception handlers.
"""

import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.routes import router
from src.config import settings
from src.core.exceptions import FinancialAgentException
from src.observability.logging_config import configure_logging
from src.observability.tracer import configure_tracing

# The ADK agent package, relative to the container's working directory. ADK
# loads agents by scanning a directory, not by import, so this is a path.
ADK_AGENTS_DIR = "src/agents"
ADK_URL_PREFIX = "/adk"


def _mount_adk_web(app: FastAPI) -> None:
    """Mount ADK's own FastAPI app - dev UI and agent REST - under /adk.

    Why mount rather than run a second service: the two surfaces share the
    agent definition, the settings and the SEC client, and running them as
    separate revisions means two images, two deploys and two chances for the
    versions to diverge. `adk web` exists for local development; in a
    deployment the agent should be reachable from the same revision whose
    `/readyz` you just checked.

    `url_prefix` is passed as well as the mount path because ADK's dev UI
    builds absolute asset URLs; mounting alone serves the HTML and then 404s
    every script it references.

    Imported inside the function: pulling in `google.adk.cli` drags the whole
    dev-server dependency tree, and the default configuration does not use it.
    """
    from google.adk.cli.fast_api import get_fast_api_app

    adk_app = get_fast_api_app(
        agents_dir=ADK_AGENTS_DIR,
        web=True,
        url_prefix=ADK_URL_PREFIX,
    )
    app.mount(ADK_URL_PREFIX, adk_app)


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application."""
    # First, before anything else can emit a line: until this runs, library and
    # uvicorn logs reach Cloud Logging as undifferentiated `textPayload` with no
    # real severity and no trace correlation.
    configure_logging(settings)

    app = FastAPI(
        title="Autonomous Investment Research Intelligence Agent (IRA) API",
        version="1.0.0",
        description="Enterprise multi-agent equity due diligence API built on Google Cloud Platform and ADK.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json"
    )

    # Global Exception Handler
    @app.exception_handler(FinancialAgentException)
    async def financial_agent_exception_handler(request: Request, exc: FinancialAgentException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error_code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat()
            }
        )

    # Mount API Routes
    app.include_router(router)

    # Auto-instrument before any other mount: FastAPIInstrumentor wraps the
    # ASGI app, so anything mounted afterwards is traced through it too.
    configure_tracing(app, settings)

    if settings.enable_adk_web:
        _mount_adk_web(app)

    return app


app = create_app()

