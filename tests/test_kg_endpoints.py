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


class TestSearchDemotion:
    """Validate AC5: invalidated decisions are demoted in search results."""

    def _ingest_and_invalidate(self, client):
        """Ingest a decision, then invalidate it via KG."""
        _ingest_decision(client, notes="We decided to use Zod for validation.")
        entity_resp = client.get("/kg/entity?name=testproj")
        triples = entity_resp.json()["triples"]
        obj = triples[0]["object"]
        client.post("/kg/invalidate", json={
            "subject": "testproj", "predicate": "decided", "object": obj,
        })
        return obj

    def test_invalidated_decision_similarity_is_demoted(self, client_with_backend):
        """AC5: invalidated decisions should have demoted similarity score."""
        # Ingest and search to get the original similarity
        _ingest_decision(client_with_backend, notes="We decided to use Zod for validation.")
        before = client_with_backend.post("/search", json={
            "query": "validation", "project": "testproj",
        }).json()["results"]
        original_sim = before[0]["similarity"]

        # Now invalidate the decision
        entity_resp = client_with_backend.get("/kg/entity?name=testproj")
        obj = entity_resp.json()["triples"][0]["object"]
        client_with_backend.post("/kg/invalidate", json={
            "subject": "testproj", "predicate": "decided", "object": obj,
        })

        # Search again — similarity should be halved
        after = client_with_backend.post("/search", json={
            "query": "validation", "project": "testproj",
        }).json()["results"]
        demoted_sim = after[0]["similarity"]
        # Demoted similarity should be approximately original * 0.5
        assert demoted_sim < original_sim, (
            f"Expected demoted ({demoted_sim}) < original ({original_sim})"
        )
        expected = round(original_sim * 0.5, 4)
        assert demoted_sim == expected, (
            f"Expected {expected}, got {demoted_sim}"
        )

    def test_invalidated_decision_still_in_results(self, client_with_backend):
        """AC5: historical facts are still included, not filtered out."""
        self._ingest_and_invalidate(client_with_backend)
        results = client_with_backend.post("/search", json={
            "query": "validation",
        }).json()["results"]
        zod = [r for r in results if "Zod" in r["content"]]
        assert len(zod) >= 1, "Invalidated decision should still appear"

    def test_non_decision_types_not_demoted(self, client_with_backend):
        """Only decision-type results should be checked for demotion."""
        client_with_backend.post("/ingest", json={
            "session_id": "s1", "project": "testproj",
            "notes": "Found that Zod is popular.",
            "source": "manual", "timestamp": "2026-04-09T12:00:00Z",
        })
        results = client_with_backend.post("/search", json={
            "query": "Zod", "project": "testproj",
        }).json()["results"]
        discoveries = [r for r in results if r["memory_type"] == "discovery"]
        # Discovery results should not be affected by KG demotion
        for r in discoveries:
            assert r["similarity"] > 0

    def test_search_without_kg_still_works(self, client_with_backend):
        """If backend has no KG, search should still return results."""
        _ingest_decision(client_with_backend)
        # Disable KG on the backend
        client_with_backend.app.state.backend._kg = None
        results = client_with_backend.post("/search", json={
            "query": "PostgreSQL",
        }).json()["results"]
        assert len(results) >= 1
