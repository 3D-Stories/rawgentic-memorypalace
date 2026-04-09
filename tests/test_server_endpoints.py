"""Tests for /ingest, /search, /reindex, and /wakeup server endpoints."""

import time

import pytest
from starlette.testclient import TestClient

from rawgentic_memory.mempalace_backend import MemPalaceBackend


@pytest.fixture
def backend(tmp_path):
    return MemPalaceBackend(palace_path=str(tmp_path / "palace"))


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


class TestIncrementalIngest:
    """Validate offset-based incremental ingest and skip logic."""

    def _make_payload(self, notes="We decided to use PostgreSQL.",
                      session_id="s1", project="testproj", source="manual"):
        return {
            "session_id": session_id,
            "project": project,
            "notes": notes,
            "source": source,
            "timestamp": "2026-04-09T12:00:00Z",
        }

    def test_first_ingest_processes_normally(self, client_with_backend):
        resp = client_with_backend.post("/ingest", json=self._make_payload())
        data = resp.json()
        assert data["indexed"] >= 1
        assert data["skipped"] == 0

    def test_duplicate_ingest_returns_skipped(self, client_with_backend):
        payload = self._make_payload()
        client_with_backend.post("/ingest", json=payload)
        # Same content, same session — should be skipped
        resp = client_with_backend.post("/ingest", json=payload)
        data = resp.json()
        assert data["skipped"] >= 1
        assert data["indexed"] == 0

    def test_appended_content_processes_only_delta(self, client_with_backend):
        payload1 = self._make_payload(notes="We decided to use PostgreSQL.")
        client_with_backend.post("/ingest", json=payload1)

        # Append new content
        payload2 = self._make_payload(
            notes="We decided to use PostgreSQL. Found that ChromaDB is fast."
        )
        resp = client_with_backend.post("/ingest", json=payload2)
        data = resp.json()
        # Should process only the delta (new content)
        assert data["indexed"] >= 1

    def test_empty_notes_returns_skipped(self, client_with_backend):
        resp = client_with_backend.post(
            "/ingest", json=self._make_payload(notes="")
        )
        data = resp.json()
        assert data["skipped"] >= 1
        assert data["indexed"] == 0

    def test_different_projects_have_independent_offsets(self, client_with_backend):
        notes = "We decided to use PostgreSQL."
        # Ingest for project A
        client_with_backend.post(
            "/ingest", json=self._make_payload(project="proj-a", notes=notes)
        )
        # Same content for project B — should NOT be skipped
        resp = client_with_backend.post(
            "/ingest", json=self._make_payload(project="proj-b", notes=notes)
        )
        data = resp.json()
        assert data["indexed"] >= 1

    def test_different_sessions_have_independent_offsets(self, client_with_backend):
        notes = "We decided to use PostgreSQL."
        # Ingest for session s1
        client_with_backend.post(
            "/ingest", json=self._make_payload(session_id="s1", notes=notes)
        )
        # Same content, different session — should NOT be skipped
        resp = client_with_backend.post(
            "/ingest", json=self._make_payload(session_id="s2", notes=notes)
        )
        data = resp.json()
        assert data["indexed"] >= 1

    def test_skip_response_has_standard_shape(self, client_with_backend):
        payload = self._make_payload()
        client_with_backend.post("/ingest", json=payload)
        resp = client_with_backend.post("/ingest", json=payload)
        data = resp.json()
        # Must have same fields as normal IngestResult
        for field in ("indexed", "skipped", "errors"):
            assert field in data, f"Missing field in skip response: {field}"

    def test_shorter_content_after_longer_is_skipped(self, client_with_backend):
        # Ingest long content
        client_with_backend.post(
            "/ingest",
            json=self._make_payload(notes="We decided to use PostgreSQL. Found that it scales well."),
        )
        # Send shorter content (subset) — should be skipped (offset past end)
        resp = client_with_backend.post(
            "/ingest",
            json=self._make_payload(notes="We decided to use PostgreSQL."),
        )
        data = resp.json()
        assert data["skipped"] >= 1
        assert data["indexed"] == 0

    def test_lru_eviction_allows_reingest(self, app_with_backend):
        """When LRU evicts an old offset, the next call for that key reprocesses."""
        from rawgentic_memory.server import _INGEST_OFFSET_MAX_ENTRIES

        with TestClient(app_with_backend) as c:
            # Ingest for the target project first
            notes = "We decided to use PostgreSQL."
            c.post("/ingest", json=self._make_payload(
                project="target", session_id="s0", notes=notes,
            ))
            # Fill the LRU with other keys to evict "target:s0"
            for i in range(_INGEST_OFFSET_MAX_ENTRIES):
                c.post("/ingest", json=self._make_payload(
                    project=f"filler-{i}", session_id="s0",
                    notes=f"We decided to use tech {i}.",
                ))
            # Now "target:s0" should have been evicted — same content reprocesses
            resp = c.post("/ingest", json=self._make_payload(
                project="target", session_id="s0", notes=notes,
            ))
            data = resp.json()
            assert data["indexed"] >= 1  # Reprocessed, not skipped

    def test_ingest_source_preserved_in_metadata(self, client_with_backend):
        """Different source values (precompact, timer, stop) are passed through."""
        for source in ("precompact", "timer", "stop"):
            resp = client_with_backend.post("/ingest", json=self._make_payload(
                notes=f"We decided to use {source} approach.",
                source=source,
                session_id=f"s-{source}",
            ))
            assert resp.status_code == 200
            assert resp.json()["indexed"] >= 1


class TestWakeupEndpoint:
    """Validate GET /wakeup endpoint."""

    def _ingest_sample(self, client):
        client.post("/ingest", json={
            "session_id": "s1",
            "project": "testproj",
            "notes": "We decided to use PostgreSQL. Found that ChromaDB is fast.",
            "source": "manual",
            "timestamp": "2026-04-09T12:00:00Z",
        })

    def test_wakeup_returns_200(self, client_with_backend):
        resp = client_with_backend.get("/wakeup?project=testproj")
        assert resp.status_code == 200

    def test_wakeup_returns_json_with_expected_fields(self, client_with_backend):
        resp = client_with_backend.get("/wakeup?project=testproj")
        data = resp.json()
        for field in ("text", "tokens", "layers", "backend"):
            assert field in data, f"Missing field: {field}"

    def test_wakeup_returns_l1_after_ingest(self, client_with_backend):
        self._ingest_sample(client_with_backend)
        resp = client_with_backend.get("/wakeup?project=testproj")
        data = resp.json()
        assert "L1" in data["layers"]
        assert data["tokens"] > 0
        assert len(data["text"]) > 0

    def test_wakeup_reflects_ingested_data(self, client_with_backend):
        self._ingest_sample(client_with_backend)
        resp = client_with_backend.get("/wakeup?project=testproj")
        data = resp.json()
        assert "PostgreSQL" in data["text"] or "ChromaDB" in data["text"]

    def test_wakeup_empty_project_returns_200(self, client_with_backend):
        resp = client_with_backend.get("/wakeup")
        assert resp.status_code == 200
        data = resp.json()
        assert data["layers"] == [] or "L0" in data["layers"]

    def test_wakeup_without_backend_returns_200(self, client_no_backend):
        resp = client_no_backend.get("/wakeup?project=test")
        assert resp.status_code == 200
        data = resp.json()
        # Graceful degradation — empty context
        assert data["text"] == ""
        assert data["layers"] == []

    def test_wakeup_with_l0_file(self, tmp_path):
        from rawgentic_memory.server import create_app
        l0_file = tmp_path / "l0.md"
        l0_file.write_text("I am a developer working on testproj.")
        backend = MemPalaceBackend(palace_path=str(tmp_path / "palace"))
        app = create_app(backend=backend, l0_path=str(l0_file))
        with TestClient(app) as c:
            resp = c.get("/wakeup?project=testproj")
            data = resp.json()
            assert "L0" in data["layers"]
            assert "developer" in data["text"]

    def test_wakeup_backend_mempalace(self, client_with_backend):
        resp = client_with_backend.get("/wakeup?project=testproj")
        assert resp.json()["backend"] == "mempalace"

    def test_wakeup_resets_idle_timer(self, app_with_backend, client_with_backend):
        initial = app_with_backend.state.last_activity
        time.sleep(0.05)
        client_with_backend.get("/wakeup?project=testproj")
        assert app_with_backend.state.last_activity > initial

    def test_wakeup_project_too_long_returns_422(self, client_with_backend):
        long_project = "a" * 200
        resp = client_with_backend.get(f"/wakeup?project={long_project}")
        assert resp.status_code == 422
