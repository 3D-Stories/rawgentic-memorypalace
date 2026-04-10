"""Tests for /kg/invalidate, /kg/entity, and /kg/timeline server endpoints."""

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


def _ingest_decision(client, project="testproj",
                     notes="We decided to use PostgreSQL."):
    client.post("/ingest", json={
        "session_id": "s1",
        "project": project,
        "notes": notes,
        "source": "manual",
        "timestamp": "2026-04-09T12:00:00Z",
    })


class TestKGInvalidateEndpoint:
    """Validate POST /kg/invalidate endpoint."""

    def test_invalidate_returns_200(self, client_with_backend):
        _ingest_decision(client_with_backend)
        # Get the exact content from entity query
        entity_resp = client_with_backend.get("/kg/entity?name=testproj")
        triples = entity_resp.json()["triples"]
        obj = triples[0]["object"]
        resp = client_with_backend.post("/kg/invalidate", json={
            "subject": "testproj",
            "predicate": "decided",
            "object": obj,
        })
        assert resp.status_code == 200

    def test_invalidate_returns_found_true(self, client_with_backend):
        _ingest_decision(client_with_backend)
        entity_resp = client_with_backend.get("/kg/entity?name=testproj")
        obj = entity_resp.json()["triples"][0]["object"]
        resp = client_with_backend.post("/kg/invalidate", json={
            "subject": "testproj",
            "predicate": "decided",
            "object": obj,
        })
        assert resp.json()["found"] is True

    def test_invalidate_nonexistent_returns_not_found(self, client_with_backend):
        resp = client_with_backend.post("/kg/invalidate", json={
            "subject": "nothing",
            "predicate": "decided",
            "object": "fake",
        })
        assert resp.status_code == 200
        assert resp.json()["found"] is False

    def test_invalidate_echoes_triple(self, client_with_backend):
        resp = client_with_backend.post("/kg/invalidate", json={
            "subject": "testproj",
            "predicate": "decided",
            "object": "anything",
        })
        data = resp.json()
        assert data["subject"] == "testproj"
        assert data["predicate"] == "decided"
        assert data["object"] == "anything"

    def test_invalidate_without_backend_returns_503(self, client_no_backend):
        resp = client_no_backend.post("/kg/invalidate", json={
            "subject": "x", "predicate": "y", "object": "z",
        })
        assert resp.status_code == 503

    def test_invalidate_missing_field_returns_422(self, client_with_backend):
        resp = client_with_backend.post("/kg/invalidate", json={
            "subject": "x",
            # missing predicate and object
        })
        assert resp.status_code == 422

    def test_invalidate_resets_idle_timer(self, app_with_backend, client_with_backend):
        initial = app_with_backend.state.last_activity
        time.sleep(0.05)
        client_with_backend.post("/kg/invalidate", json={
            "subject": "x", "predicate": "y", "object": "z",
        })
        assert app_with_backend.state.last_activity > initial


class TestKGEntityEndpoint:
    """Validate GET /kg/entity endpoint."""

    def test_entity_returns_200(self, client_with_backend):
        resp = client_with_backend.get("/kg/entity?name=testproj")
        assert resp.status_code == 200

    def test_entity_returns_triples(self, client_with_backend):
        _ingest_decision(client_with_backend)
        resp = client_with_backend.get("/kg/entity?name=testproj")
        data = resp.json()
        assert "triples" in data
        assert len(data["triples"]) >= 1

    def test_entity_triple_has_expected_fields(self, client_with_backend):
        _ingest_decision(client_with_backend)
        triple = client_with_backend.get("/kg/entity?name=testproj").json()["triples"][0]
        for field in ("subject", "predicate", "object", "valid_from", "valid_to", "current"):
            assert field in triple, f"Missing field: {field}"

    def test_entity_filters_by_as_of(self, client_with_backend):
        _ingest_decision(client_with_backend)
        # Query at a time before the decision was made
        resp = client_with_backend.get("/kg/entity?name=testproj&as_of=2025-01-01T00:00:00Z")
        assert len(resp.json()["triples"]) == 0

    def test_entity_empty_returns_empty_list(self, client_with_backend):
        resp = client_with_backend.get("/kg/entity?name=nonexistent")
        assert resp.json()["triples"] == []

    def test_entity_without_backend_returns_503(self, client_no_backend):
        resp = client_no_backend.get("/kg/entity?name=test")
        assert resp.status_code == 503

    def test_entity_missing_name_returns_422(self, client_with_backend):
        resp = client_with_backend.get("/kg/entity")
        assert resp.status_code == 422


class TestKGTimelineEndpoint:
    """Validate GET /kg/timeline endpoint."""

    def test_timeline_returns_200(self, client_with_backend):
        resp = client_with_backend.get("/kg/timeline?entity=testproj")
        assert resp.status_code == 200

    def test_timeline_returns_events(self, client_with_backend):
        _ingest_decision(client_with_backend)
        resp = client_with_backend.get("/kg/timeline?entity=testproj")
        data = resp.json()
        assert "timeline" in data
        assert len(data["timeline"]) >= 1

    def test_timeline_event_has_expected_fields(self, client_with_backend):
        _ingest_decision(client_with_backend)
        event = client_with_backend.get("/kg/timeline?entity=testproj").json()["timeline"][0]
        for field in ("subject", "predicate", "object", "valid_from", "valid_to", "current"):
            assert field in event, f"Missing field: {field}"

    def test_timeline_shows_invalidated_as_non_current(self, client_with_backend):
        _ingest_decision(client_with_backend)
        # Get and invalidate
        entity_resp = client_with_backend.get("/kg/entity?name=testproj")
        obj = entity_resp.json()["triples"][0]["object"]
        client_with_backend.post("/kg/invalidate", json={
            "subject": "testproj", "predicate": "decided", "object": obj,
        })
        tl = client_with_backend.get("/kg/timeline?entity=testproj").json()["timeline"]
        invalidated = [t for t in tl if t["current"] is False]
        assert len(invalidated) >= 1

    def test_timeline_empty_returns_empty_list(self, client_with_backend):
        resp = client_with_backend.get("/kg/timeline?entity=nonexistent")
        assert resp.json()["timeline"] == []

    def test_timeline_without_backend_returns_503(self, client_no_backend):
        resp = client_no_backend.get("/kg/timeline?entity=test")
        assert resp.status_code == 503

    def test_timeline_missing_entity_returns_422(self, client_with_backend):
        resp = client_with_backend.get("/kg/timeline")
        assert resp.status_code == 422
