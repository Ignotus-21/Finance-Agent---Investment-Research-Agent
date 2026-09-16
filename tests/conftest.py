"""
Pytest configuration and shared fixtures for unit, integration, and chaos testing.
"""

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.app import app
from src.config import Settings
from src.core.container import ApplicationContainer


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Test environment configuration."""
    return Settings(
        environment="test",
        debug=True,
        enforce_guardrails=True,
        enable_dlp_masking=True
    )


@pytest.fixture
def app_container(test_settings: Settings) -> ApplicationContainer:
    """Provides isolated DI container for tests."""
    return ApplicationContainer(settings=test_settings)


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Asynchronous HTTP test client for FastAPI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
