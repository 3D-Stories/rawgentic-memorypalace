"""Shared fixtures for rawgentic-memorypalace tests."""

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def app():
    """Create a fresh FastAPI app instance for testing."""
    from rawgentic_memory.server import create_app

    return create_app()


@pytest.fixture
def client(app):
    """Synchronous test client for the FastAPI app."""
    with TestClient(app) as c:
        yield c
