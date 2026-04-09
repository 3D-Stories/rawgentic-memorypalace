"""Tests for NativeBackend.reindex() — rebuilding index from source files."""

import chromadb
import pytest

from rawgentic_memory.models import IngestResult
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


class TestReindex:
    """Validate rebuilding the ChromaDB index from source files."""

    def test_reindex_returns_ingest_result(self, backend, tmp_path):
        (tmp_path / "proj.md").write_text("We decided to use FastAPI.")
        result = backend.reindex([str(tmp_path)])
        assert isinstance(result, IngestResult)

    def test_reindex_indexes_markdown_files(self, backend, tmp_path):
        (tmp_path / "proj.md").write_text(
            "We decided to use PostgreSQL.\nFound that ChromaDB is fast."
        )
        result = backend.reindex([str(tmp_path)])
        assert result.indexed >= 2

    def test_reindex_indexes_txt_files(self, backend, tmp_path):
        (tmp_path / "notes.txt").write_text("We decided to use Redis for caching.")
        result = backend.reindex([str(tmp_path)])
        assert result.indexed >= 1

    def test_reindex_indexes_jsonl_files(self, backend, tmp_path):
        (tmp_path / "archive.jsonl").write_text(
            "We decided to use Docker for deployment."
        )
        result = backend.reindex([str(tmp_path)])
        assert result.indexed >= 1

    def test_reindex_skips_non_text_files(self, backend, tmp_path):
        (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n")
        result = backend.reindex([str(tmp_path)])
        assert result.indexed == 0

    def test_reindex_walks_subdirectories(self, backend, tmp_path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "deep.md").write_text("We decided to use nested directories.")
        result = backend.reindex([str(tmp_path)])
        assert result.indexed >= 1

    def test_reindex_derives_project_from_parent_dir(self, backend, tmp_path):
        """Files in subdirs get project from the subdir name, not filename."""
        proj_dir = tmp_path / "grocusave"
        proj_dir.mkdir()
        (proj_dir / "session_01.md").write_text("We decided to use Algolia.")
        backend.reindex([str(tmp_path)])
        results = backend.search("Algolia", project="grocusave")
        assert len(results) >= 1
        assert results[0].project == "grocusave"

    def test_reindex_populates_search(self, backend, tmp_path):
        (tmp_path / "proj.md").write_text(
            "We decided to use PostgreSQL for the database."
        )
        backend.reindex([str(tmp_path)])
        results = backend.search("database")
        assert len(results) >= 1
        assert "PostgreSQL" in results[0].content

    def test_reindex_missing_dir_returns_zero(self, backend, tmp_path):
        result = backend.reindex([str(tmp_path / "nonexistent")])
        assert result.indexed == 0

    def test_reindex_multiple_source_dirs(self, backend, tmp_path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "one.md").write_text("We decided to use approach A.")
        (dir_b / "two.md").write_text("Found that approach B is better.")
        result = backend.reindex([str(dir_a), str(dir_b)])
        assert result.indexed >= 2

    def test_reindex_is_idempotent(self, backend, tmp_path):
        (tmp_path / "proj.md").write_text("We decided to use FastAPI.")
        r1 = backend.reindex([str(tmp_path)])
        r2 = backend.reindex([str(tmp_path)])
        # Same content = same doc IDs = upsert, not duplicate
        assert backend.stats().doc_count == r1.indexed

    def test_reindex_after_corruption(self, backend, chroma_client, tmp_path):
        """Simulates re-indexing after ChromaDB data loss."""
        (tmp_path / "proj.md").write_text(
            "We decided to use PostgreSQL.\nDeployed the server."
        )
        backend.reindex([str(tmp_path)])
        original_count = backend.stats().doc_count
        assert original_count >= 2

        # Simulate corruption: reset clears all data
        chroma_client.reset()
        assert backend.stats().doc_count == 0

        # Re-index recovers
        backend.reindex([str(tmp_path)])
        assert backend.stats().doc_count == original_count
