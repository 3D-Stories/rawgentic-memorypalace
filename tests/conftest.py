"""Shared fixtures for rawgentic-memorypalace tests."""

import httpx
import pytest


@pytest.fixture
def app():
    """Create a fresh FastAPI app instance for testing."""
    from rawgentic_memory.server import create_app

    return create_app()


@pytest.fixture
def client(app):
    """Synchronous httpx client wired to the FastAPI app via ASGITransport."""
    transport = httpx.ASGITransport(app=app)
    with httpx.Client(transport=transport, base_url="http://testserver") as c:
        yield c
