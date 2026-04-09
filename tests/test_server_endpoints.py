"""Tests for /ingest, /search, and /reindex server endpoints."""

import time

import chromadb
import pytest
from starlette.testclient import TestClient

from rawgentic_memory.native_backend import NativeBackend


@pytest.fixture
def chroma_client():
    settings = chromadb.Settings(allow_reset=True, anonymized_telemetry=False)
    client = chromadb.EphemeralClient(settings=settings)
    client.reset()
    return client


@pytest.fixture
def backend(chroma_client):
    return NativeBackend(client=chroma_client)


@pytest.fixture
def app_with_backend(backend):
    from rawgentic_memory.server import create_app
    return create_app(backend=backend)


@pytest.fixture
def client_with_backend(app_with_backend):
    with TestClient(app_with_backend) as c:
        yield c


@pytest.fixture
def app_no_backend():
    from rawgentic_memory.server import create_app
    return create_app(backend=None)


@pytest.fixture
def client_no_backend(app_no_backend):
    with TestClient(app_no_backend) as c:
        yield c


class TestIngestEndpoint:
    """Validate POST /ingest endpoint."""

    def test_ingest_returns_200(self, client_with_backend):
        resp = client_with_backend.post("/ingest", json={
            "session_id": "s1",
            "project": "testproj",
            "notes": "We decided to use PostgreSQL.",
            "source": "manual",
            "timestamp": "2026-04-09T12:00:00Z",
        })
        assert resp.status_code == 200

    def test_ingest_returns_result(self, client_with_backend):
        resp = client_with_backend.post("/ingest", json={
            "session_id": "s1",
            "project": "testproj",
            "notes": "We decided to use PostgreSQL.",
            "source": "manual",
            "timestamp": "2026-04-09T12:00:00Z",
        })
        data = resp.json()
        assert "indexed" in data
        assert data["indexed"] >= 1

    def test_ingest_empty_notes_returns_zero(self, client_with_backend):
        resp = client_with_backend.post("/ingest", json={
            "session_id": "s1",
            "project": "testproj",
            "notes": "",
            "source": "manual",
            "timestamp": "2026-04-09T12:00:00Z",
        })
        data = resp.json()
        assert data["indexed"] == 0

    def test_ingest_missing_required_field_returns_422(self, client_with_backend):
        resp = client_with_backend.post("/ingest", json={
            "session_id": "s1",
            # missing project, notes, source, timestamp
        })
        assert resp.status_code == 422

    def test_ingest_without_backend_returns_503(self, client_no_backend):
        resp = client_no_backend.post("/ingest", json={
            "session_id": "s1",
            "project": "testproj",
            "notes": "test",
            "source": "manual",
            "timestamp": "2026-04-09T12:00:00Z",
        })
        assert resp.status_code == 503

    def test_ingest_resets_idle_timer(self, app_with_backend, client_with_backend):
        initial = app_with_backend.state.last_activity
        time.sleep(0.05)
        client_with_backend.post("/ingest", json={
            "session_id": "s1",
            "project": "testproj",
            "notes": "We decided to use PostgreSQL.",
            "source": "manual",
            "timestamp": "2026-04-09T12:00:00Z",
        })
        assert app_with_backend.state.last_activity > initial


class TestSearchEndpoint:
    """Validate POST /search endpoint."""

    def _ingest_sample(self, client):
        client.post("/ingest", json={
            "session_id": "s1",
            "project": "testproj",
            "notes": "We decided to use PostgreSQL. Found that ChromaDB is fast.",
            "source": "manual",
            "timestamp": "2026-04-09T12:00:00Z",
        })

    def test_search_returns_200(self, client_with_backend):
        self._ingest_sample(client_with_backend)
        resp = client_with_backend.post("/search", json={"query": "database"})
        assert resp.status_code == 200

    def test_search_returns_results(self, client_with_backend):
        self._ingest_sample(client_with_backend)
        resp = client_with_backend.post("/search", json={"query": "database"})
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) >= 1

    def test_search_results_have_all_fields(self, client_with_backend):
        self._ingest_sample(client_with_backend)
        resp = client_with_backend.post("/search", json={"query": "database"})
        result = resp.json()["results"][0]
        for field in ("content", "project", "memory_type", "topic",
                       "similarity", "source_file", "session_id", "timestamp"):
            assert field in result, f"Missing field: {field}"

    def test_search_filters_by_project(self, client_with_backend):
        self._ingest_sample(client_with_backend)
        resp = client_with_backend.post("/search", json={
            "query": "database",
            "project": "testproj",
        })
        for r in resp.json()["results"]:
            assert r["project"] == "testproj"

    def test_search_filters_by_memory_type(self, client_with_backend):
        self._ingest_sample(client_with_backend)
        resp = client_with_backend.post("/search", json={
            "query": "database",
            "memory_type": "decision",
        })
        for r in resp.json()["results"]:
            assert r["memory_type"] == "decision"

    def test_search_respects_limit(self, client_with_backend):
        self._ingest_sample(client_with_backend)
        resp = client_with_backend.post("/search", json={
            "query": "database",
            "limit": 1,
        })
        assert len(resp.json()["results"]) <= 1

    def test_search_without_backend_returns_503(self, client_no_backend):
        resp = client_no_backend.post("/search", json={"query": "test"})
        assert resp.status_code == 503

    def test_search_missing_query_returns_422(self, client_with_backend):
        resp = client_with_backend.post("/search", json={})
        assert resp.status_code == 422


class TestReindexEndpoint:
    """Validate POST /reindex endpoint."""

    def test_reindex_returns_200(self, client_with_backend, tmp_path):
        resp = client_with_backend.post("/reindex", json={
            "source_dirs": [str(tmp_path)],
        })
        assert resp.status_code == 200

    def test_reindex_returns_result(self, client_with_backend, tmp_path):
        (tmp_path / "test.md").write_text("We decided to use FastAPI.")
        resp = client_with_backend.post("/reindex", json={
            "source_dirs": [str(tmp_path)],
        })
        data = resp.json()
        assert "indexed" in data
        assert data["indexed"] >= 1

    def test_reindex_without_backend_returns_503(self, client_no_backend, tmp_path):
        resp = client_no_backend.post("/reindex", json={
            "source_dirs": [str(tmp_path)],
        })
        assert resp.status_code == 503

    def test_reindex_missing_source_dirs_returns_422(self, client_with_backend):
        resp = client_with_backend.post("/reindex", json={})
        assert resp.status_code == 422
