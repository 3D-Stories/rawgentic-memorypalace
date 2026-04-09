"""Tests for the NativeBackend ChromaDB implementation."""

import chromadb
import pytest

from rawgentic_memory.models import (
    BackendStats,
    EnrichedSegment,
    IngestResult,
    SearchResult,
    SessionData,
)
from rawgentic_memory.native_backend import NativeBackend


@pytest.fixture
def chroma_client():
    """Ephemeral in-memory ChromaDB client for testing.

    Uses allow_reset=True so we can clear leaked state between tests,
    since ChromaDB's ephemeral client shares state within a process.
    """
    settings = chromadb.Settings(
        allow_reset=True,
        anonymized_telemetry=False,
    )
    client = chromadb.EphemeralClient(settings=settings)
    client.reset()
    return client


@pytest.fixture
def backend(chroma_client):
    """NativeBackend with ephemeral ChromaDB."""
    return NativeBackend(client=chroma_client)


class TestNativeBackendInit:
    """Validate NativeBackend initialization and availability."""

    def test_is_available_after_init(self, backend):
        assert backend.stats().available is True

    def test_starts_with_zero_docs(self, backend):
        assert backend.stats().doc_count == 0

    def test_accepts_chromadb_client(self, chroma_client):
        b = NativeBackend(client=chroma_client)
        assert b.stats().available is True


class TestNativeBackendIngest:
    """Validate ingesting session data into ChromaDB."""

    def test_ingest_returns_ingest_result(self, backend):
        data = SessionData(
            session_id="s1",
            project="testproj",
            notes="We decided to use PostgreSQL for production.",
            source="manual",
            timestamp="2026-04-09T12:00:00Z",
        )
        result = backend.ingest(data)
        assert isinstance(result, IngestResult)

    def test_ingest_indexes_enriched_segments(self, backend):
        data = SessionData(
            session_id="s1",
            project="testproj",
            notes="We decided to use PostgreSQL. Found that ChromaDB is fast.",
            source="manual",
            timestamp="2026-04-09T12:00:00Z",
        )
        result = backend.ingest(data)
        assert result.indexed >= 2

    def test_ingest_increases_doc_count(self, backend):
        data = SessionData(
            session_id="s1",
            project="testproj",
            notes="We decided to use PostgreSQL for the database.",
            source="manual",
            timestamp="2026-04-09T12:00:00Z",
        )
        backend.ingest(data)
        assert backend.stats().doc_count >= 1

    def test_ingest_empty_notes_returns_zero(self, backend):
        data = SessionData(
            session_id="s1",
            project="testproj",
            notes="",
            source="manual",
            timestamp="2026-04-09T12:00:00Z",
        )
        result = backend.ingest(data)
        assert result.indexed == 0

    def test_ingest_stores_metadata(self, backend):
        data = SessionData(
            session_id="sess-abc",
            project="myproject",
            notes="We decided to use Valibot over Zod.",
            source="precompact",
            timestamp="2026-04-09T14:30:00Z",
            source_file="session_notes/myproject.md",
        )
        backend.ingest(data)

        # Search and verify metadata comes back
        results = backend.search("Valibot", project="myproject")
        assert len(results) >= 1
        r = results[0]
        assert r.project == "myproject"
        assert r.memory_type == "decision"
        assert r.session_id == "sess-abc"
        assert r.timestamp == "2026-04-09T14:30:00Z"
        assert r.source_file == "session_notes/myproject.md"

    def test_ingest_multiple_projects(self, backend):
        for proj in ("alpha", "beta"):
            data = SessionData(
                session_id=f"s-{proj}",
                project=proj,
                notes=f"We decided to use {proj} configuration.",
                source="manual",
                timestamp="2026-04-09T12:00:00Z",
            )
            backend.ingest(data)

        assert backend.stats().doc_count >= 2

    def test_ingest_updates_last_ingest(self, backend):
        assert backend.stats().last_ingest is None
        data = SessionData(
            session_id="s1",
            project="testproj",
            notes="We decided to use FastAPI.",
            source="manual",
            timestamp="2026-04-09T12:00:00Z",
        )
        backend.ingest(data)
        assert backend.stats().last_ingest is not None


class TestNativeBackendSearch:
    """Validate semantic search via ChromaDB."""

    def _ingest_sample(self, backend):
        """Ingest a varied sample corpus."""
        samples = [
            ("We decided to use PostgreSQL instead of SQLite.", "proj-a"),
            ("Deployed the auth service to production.", "proj-a"),
            ("Found that ChromaDB uses SQLite under the hood.", "proj-b"),
            ("Always run tests before pushing to main.", "proj-a"),
        ]
        for notes, project in samples:
            backend.ingest(SessionData(
                session_id="s1",
                project=project,
                notes=notes,
                source="manual",
                timestamp="2026-04-09T12:00:00Z",
            ))

    def test_search_returns_list_of_search_results(self, backend):
        self._ingest_sample(backend)
        results = backend.search("database choice")
        assert isinstance(results, list)
        assert all(isinstance(r, SearchResult) for r in results)

    def test_search_returns_relevant_results(self, backend):
        self._ingest_sample(backend)
        results = backend.search("database")
        assert len(results) >= 1
        # PostgreSQL or SQLite should appear in top results
        contents = " ".join(r.content for r in results)
        assert "PostgreSQL" in contents or "SQLite" in contents

    def test_search_results_have_similarity_scores(self, backend):
        self._ingest_sample(backend)
        results = backend.search("database")
        for r in results:
            assert 0.0 <= r.similarity <= 1.0

    def test_search_results_sorted_by_similarity(self, backend):
        self._ingest_sample(backend)
        results = backend.search("database")
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i].similarity >= results[i + 1].similarity

    def test_search_filters_by_project(self, backend):
        self._ingest_sample(backend)
        results = backend.search("database", project="proj-b")
        for r in results:
            assert r.project == "proj-b"

    def test_search_filters_by_memory_type(self, backend):
        self._ingest_sample(backend)
        results = backend.search("database", memory_type="decision")
        for r in results:
            assert r.memory_type == "decision"

    def test_search_respects_limit(self, backend):
        self._ingest_sample(backend)
        results = backend.search("test", limit=2)
        assert len(results) <= 2

    def test_search_empty_query_returns_results(self, backend):
        self._ingest_sample(backend)
        # Even an empty-ish query should not crash
        results = backend.search("anything")
        assert isinstance(results, list)

    def test_search_no_results_returns_empty_list(self, backend):
        # No data ingested
        results = backend.search("nothing here")
        assert results == []


class TestNativeBackendGetProjectDocuments:
    """Validate bulk document retrieval for wakeup context."""

    def _ingest_sample(self, backend):
        backend.ingest(SessionData(
            session_id="s1",
            project="proj-a",
            notes="We decided to use PostgreSQL. Found that ChromaDB is fast.",
            source="manual",
            timestamp="2026-04-09T12:00:00Z",
            source_file="notes/proj-a/session.md",
        ))

    def test_returns_list_of_dicts(self, backend):
        self._ingest_sample(backend)
        docs = backend.get_project_documents("proj-a")
        assert isinstance(docs, list)
        assert all(isinstance(d, dict) for d in docs)

    def test_returns_content_and_metadata(self, backend):
        self._ingest_sample(backend)
        docs = backend.get_project_documents("proj-a")
        assert len(docs) >= 1
        doc = docs[0]
        assert "content" in doc
        assert "metadata" in doc
        assert isinstance(doc["content"], str)
        assert isinstance(doc["metadata"], dict)

    def test_metadata_has_required_fields(self, backend):
        self._ingest_sample(backend)
        docs = backend.get_project_documents("proj-a")
        meta = docs[0]["metadata"]
        for field in ("topic", "timestamp", "memory_type", "project",
                       "source_file", "session_id"):
            assert field in meta, f"Missing metadata field: {field}"

    def test_empty_project_returns_empty_list(self, backend):
        docs = backend.get_project_documents("nonexistent")
        assert docs == []

    def test_respects_limit(self, backend):
        # Ingest enough to have multiple docs
        for i in range(5):
            backend.ingest(SessionData(
                session_id=f"s{i}",
                project="bulk",
                notes=f"We decided to use approach {i}. Found that method {i} works.",
                source="manual",
                timestamp=f"2026-04-0{i+1}T12:00:00Z",
            ))
        all_docs = backend.get_project_documents("bulk")
        limited = backend.get_project_documents("bulk", limit=2)
        assert len(limited) <= 2
        assert len(all_docs) >= len(limited)

    def test_does_not_include_other_projects(self, backend):
        backend.ingest(SessionData(
            session_id="s1", project="alpha",
            notes="We decided to use Redis.", source="manual",
            timestamp="2026-04-09T12:00:00Z",
        ))
        backend.ingest(SessionData(
            session_id="s2", project="beta",
            notes="We decided to use Postgres.", source="manual",
            timestamp="2026-04-09T12:00:00Z",
        ))
        docs = backend.get_project_documents("alpha")
        for d in docs:
            assert d["metadata"]["project"] == "alpha"


class TestNativeBackendStats:
    """Validate stats reporting."""

    def test_stats_returns_backend_stats(self, backend):
        stats = backend.stats()
        assert isinstance(stats, BackendStats)

    def test_stats_available_true(self, backend):
        assert backend.stats().available is True

    def test_stats_doc_count_accurate(self, backend):
        data = SessionData(
            session_id="s1",
            project="testproj",
            notes="We decided to use PostgreSQL. Found that it scales well.",
            source="manual",
            timestamp="2026-04-09T12:00:00Z",
        )
        backend.ingest(data)
        stats = backend.stats()
        assert stats.doc_count >= 2
