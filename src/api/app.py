"""
FastAPI Application Entrypoint.
Initializes middleware, CORS, routers, and exception handlers.
"""

import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.routes import router
from src.core.exceptions import FinancialAgentException


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application."""
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

    return app


app = create_app()
