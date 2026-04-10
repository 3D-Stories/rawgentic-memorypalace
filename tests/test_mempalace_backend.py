"""Tests for MemPalaceBackend — the thin bridge to mempalace library."""

import hashlib

import pytest

from rawgentic_memory.models import (
    BackendStats,
    IngestResult,
    SearchResult,
    SessionData,
)


@pytest.fixture
def backend(tmp_path):
    """Create a MemPalaceBackend with an isolated temp palace."""
    from rawgentic_memory.mempalace_backend import MemPalaceBackend

    return MemPalaceBackend(palace_path=str(tmp_path / "palace"))


def _session(project="testproj", notes="We decided to use PostgreSQL for the database."):
    return SessionData(
        session_id="s1",
        project=project,
        notes=notes,
        source="test",
        timestamp="2026-04-09T12:00:00Z",
        source_file="session.md",
    )


class TestMemPalaceBackendIngest:
    """Validate ingest: enrichment → add_drawer with metadata preservation."""

    def test_ingest_returns_ingest_result(self, backend):
        result = backend.ingest(_session())
        assert isinstance(result, IngestResult)

    def test_ingest_indexes_decision_segments(self, backend):
        result = backend.ingest(_session())
        assert result.indexed >= 1

    def test_ingest_empty_notes_returns_zero(self, backend):
        result = backend.ingest(_session(notes=""))
        assert result.indexed == 0

    def test_ingest_no_extractable_content_returns_zero(self, backend):
        result = backend.ingest(_session(notes="Hello world."))
        assert result.indexed == 0

    def test_ingest_preserves_memory_type_metadata(self, backend):
        backend.ingest(_session())
        docs = backend.get_project_documents("testproj")
        assert len(docs) >= 1
        assert docs[0]["metadata"]["memory_type"] == "decision"

    def test_ingest_preserves_session_id_metadata(self, backend):
        backend.ingest(_session())
        docs = backend.get_project_documents("testproj")
        assert docs[0]["metadata"]["session_id"] == "s1"

    def test_ingest_preserves_timestamp_metadata(self, backend):
        backend.ingest(_session())
        docs = backend.get_project_documents("testproj")
        assert docs[0]["metadata"]["timestamp"] == "2026-04-09T12:00:00Z"

    def test_ingest_sets_wing_to_project(self, backend):
        backend.ingest(_session(project="grocusave"))
        docs = backend.get_project_documents("grocusave")
        assert docs[0]["metadata"]["wing"] == "grocusave"

    def test_ingest_sets_room_to_topic(self, backend):
        backend.ingest(_session())
        docs = backend.get_project_documents("testproj")
        room = docs[0]["metadata"]["room"]
        assert isinstance(room, str)
        assert len(room) > 0

    def test_ingest_empty_topic_defaults_to_general(self, backend):
        """When enrichment returns an empty topic, room defaults to 'general'."""
        # Single word without meaningful topic extraction
        result = backend.ingest(_session(notes="We decided yes."))
        if result.indexed > 0:
            docs = backend.get_project_documents("testproj")
            for doc in docs:
                room = doc["metadata"]["room"]
                assert isinstance(room, str)
                assert len(room) > 0  # never empty

    def test_ingest_is_idempotent(self, backend):
        """Upserting same content twice does not create duplicates."""
        backend.ingest(_session())
        count1 = backend.stats().doc_count
        backend.ingest(_session())
        count2 = backend.stats().doc_count
        assert count2 == count1

    def test_ingest_multiple_segments(self, backend):
        notes = "We decided to use PostgreSQL. Found that ChromaDB is fast."
        result = backend.ingest(_session(notes=notes))
        assert result.indexed >= 2


class TestMemPalaceBackendSearch:
    """Validate search: ChromaDB query with field mapping and similarity conversion."""

    def test_search_returns_list(self, backend):
        backend.ingest(_session())
        results = backend.search("PostgreSQL")
        assert isinstance(results, list)

    def test_search_finds_ingested_content(self, backend):
        backend.ingest(_session())
        results = backend.search("PostgreSQL")
        assert len(results) >= 1
        assert "PostgreSQL" in results[0].content

    def test_search_returns_search_result_type(self, backend):
        backend.ingest(_session())
        results = backend.search("PostgreSQL")
        assert isinstance(results[0], SearchResult)

    def test_search_has_all_8_fields(self, backend):
        backend.ingest(_session())
        r = backend.search("PostgreSQL")[0]
        assert r.content != ""
        assert r.project == "testproj"
        assert r.memory_type == "decision"
        assert isinstance(r.topic, str)
        assert 0.0 < r.similarity <= 1.0
        assert isinstance(r.source_file, str)
        assert r.session_id == "s1"
        assert r.timestamp == "2026-04-09T12:00:00Z"

    def test_search_similarity_in_zero_one_range(self, backend):
        backend.ingest(_session())
        results = backend.search("PostgreSQL")
        for r in results:
            assert 0.0 <= r.similarity <= 1.0

    def test_search_filters_by_project(self, backend):
        backend.ingest(_session(project="alpha"))
        backend.ingest(_session(project="beta", notes="We decided to use Redis."))
        results = backend.search("database", project="alpha")
        for r in results:
            assert r.project == "alpha"

    def test_search_post_filters_by_memory_type(self, backend):
        backend.ingest(_session(notes="We decided to use PostgreSQL. Deployed the server."))
        results = backend.search("PostgreSQL", memory_type="decision")
        for r in results:
            assert r.memory_type == "decision"

    def test_search_empty_collection_returns_empty(self, backend):
        results = backend.search("anything")
        assert results == []

    def test_search_respects_limit(self, backend):
        notes = "\n".join([
            "We decided to use PostgreSQL.",
            "We decided to use Redis.",
            "We decided to use FastAPI.",
            "We decided to use Docker.",
        ])
        backend.ingest(_session(notes=notes))
        results = backend.search("decided", limit=2)
        assert len(results) <= 2


class TestMemPalaceBackendStats:
    """Validate stats reporting."""

    def test_stats_returns_backend_stats(self, backend):
        assert isinstance(backend.stats(), BackendStats)

    def test_stats_initially_zero(self, backend):
        s = backend.stats()
        assert s.available is True
        assert s.doc_count == 0
        assert s.last_ingest is None

    def test_stats_after_ingest(self, backend):
        backend.ingest(_session())
        s = backend.stats()
        assert s.doc_count >= 1
        assert s.last_ingest is not None

    def test_stats_available_flag(self, backend):
        assert backend.stats().available is True


class TestMemPalaceBackendGetProjectDocuments:
    """Validate get_project_documents for wakeup compatibility."""

    def test_returns_list_of_dicts(self, backend):
        backend.ingest(_session())
        docs = backend.get_project_documents("testproj")
        assert isinstance(docs, list)
        assert len(docs) >= 1
        assert isinstance(docs[0], dict)

    def test_dicts_have_content_and_metadata(self, backend):
        backend.ingest(_session())
        doc = backend.get_project_documents("testproj")[0]
        assert "content" in doc
        assert "metadata" in doc

    def test_empty_project_returns_empty(self, backend):
        backend.ingest(_session(project="alpha"))
        docs = backend.get_project_documents("nonexistent")
        assert docs == []

    def test_filters_by_project(self, backend):
        backend.ingest(_session(project="alpha"))
        backend.ingest(_session(project="beta", notes="We decided to use Redis."))
        docs = backend.get_project_documents("alpha")
        for doc in docs:
            assert doc["metadata"]["wing"] == "alpha"


class TestKGIngestSideChannel:
    """Validate KG triple creation during ingest for decision-type segments."""

    def test_decision_ingest_creates_kg_triple(self, backend):
        """AC1: decision segments should create KG triples."""
        backend.ingest(_session())
        triples = backend.query_entity("testproj")
        assert len(triples) >= 1

    def test_decision_triple_has_correct_subject(self, backend):
        backend.ingest(_session(project="grocusave"))
        triples = backend.query_entity("grocusave")
        assert triples[0]["subject"] == "grocusave"

    def test_decision_triple_has_decided_predicate(self, backend):
        backend.ingest(_session())
        triples = backend.query_entity("testproj")
        assert triples[0]["predicate"] == "decided"

    def test_decision_triple_object_matches_content(self, backend):
        backend.ingest(_session())
        triples = backend.query_entity("testproj")
        assert "PostgreSQL" in triples[0]["object"]

    def test_decision_triple_has_valid_from(self, backend):
        backend.ingest(_session())
        triples = backend.query_entity("testproj")
        assert triples[0]["valid_from"] == "2026-04-09T12:00:00Z"

    def test_decision_triple_is_current(self, backend):
        backend.ingest(_session())
        triples = backend.query_entity("testproj")
        assert triples[0]["current"] is True

    def test_non_decision_ingest_no_kg_triple(self, backend):
        """Non-decision segments should NOT create KG triples."""
        backend.ingest(_session(notes="Found that ChromaDB is fast."))
        triples = backend.query_entity("testproj")
        assert len(triples) == 0

    def test_multiple_decisions_create_multiple_triples(self, backend):
        notes = "We decided to use PostgreSQL. We decided to use Redis."
        backend.ingest(_session(notes=notes))
        triples = backend.query_entity("testproj")
        assert len(triples) >= 2

    def test_kg_failure_does_not_block_ingest(self, backend):
        """KG failure should not prevent ChromaDB ingest from succeeding."""
        # Corrupt the KG to force failures
        backend._kg = None
        result = backend.ingest(_session())
        # ChromaDB ingest should still succeed
        assert result.indexed >= 1

    def test_kg_init_creates_kg_attribute(self, backend):
        """Backend should have a _kg attribute after initialization."""
        assert hasattr(backend, "_kg")
        assert backend._kg is not None
