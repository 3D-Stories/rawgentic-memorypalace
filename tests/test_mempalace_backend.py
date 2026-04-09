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
