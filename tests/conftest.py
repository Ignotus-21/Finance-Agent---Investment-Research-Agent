"""
Pytest configuration and shared fixtures for unit, integration, and chaos testing.
"""

import pytest
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from src.api.app import app
from src.core.container import ApplicationContainer
from src.config import Settings


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
