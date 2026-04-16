"""Shared fixtures for rawgentic-memorypalace tests."""

import sys

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


@pytest.fixture
def isolated_palace(tmp_path, monkeypatch):
    """Provide an isolated mempalace palace per test."""
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(palace_dir))
    return palace_dir


@pytest.fixture
def mock_mempalace_unavailable(monkeypatch):
    """Simulate mempalace not being installed.

    NOTE: This only works for code that does lazy/late imports of mempalace.
    Module-level imports in adapter.py have already resolved by the time this
    fixture activates. To test 'mempalace not installed' for already-imported
    symbols, use direct mock patching like:
        with patch('rawgentic_memory.adapter.search_memories', None):
            ...
    """
    monkeypatch.setitem(sys.modules, "mempalace", None)
    # monkeypatch auto-reverts on test exit — no manual cleanup needed.


@pytest.fixture
def adapter(isolated_palace):
    """Adapter instance pointing at isolated palace."""
    from rawgentic_memory.adapter import MempalaceAdapter
    return MempalaceAdapter(palace_path=str(isolated_palace))
