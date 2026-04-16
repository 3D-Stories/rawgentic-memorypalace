"""Tests for the slim HTTP server routing through MempalaceAdapter."""
import pytest
from starlette.testclient import TestClient


@pytest.fixture
def slim_app(isolated_palace):
    """Build the slim server app pointing at the isolated palace."""
    from rawgentic_memory.server import build_app

    return build_app(palace_path=str(isolated_palace))


@pytest.fixture
def client(slim_app):
    """Synchronous test client for the slim server."""
    with TestClient(slim_app) as c:
        yield c


class TestHealthz:
    def test_healthz_returns_200(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert data["backend"] == "mempalace"
        assert "doc_count" in data

    def test_healthz_reports_version(self, client):
        resp = client.get("/healthz")
        data = resp.json()
        assert "version" in data
        assert data["version"] != ""
