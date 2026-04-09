"""Tests for the MemoryBackend abstract base class."""

import pytest

from rawgentic_memory.backend import MemoryBackend
from rawgentic_memory.models import (
    BackendStats,
    IngestResult,
    SearchResult,
    SessionData,
)


def _all_except(*exclude):
    """Return a dict of all ABC methods except the named ones."""
    methods = {
        "ingest": lambda self, session_data: IngestResult(),
        "search": lambda self, query, project=None, memory_type=None, limit=10: [],
        "stats": lambda self: BackendStats(),
        "reindex": lambda self, source_dirs: IngestResult(),
        "get_project_documents": lambda self, project, limit=500: [],
    }
    return {k: v for k, v in methods.items() if k not in exclude}


class TestMemoryBackendABC:
    """Validate MemoryBackend cannot be instantiated and defines the contract."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            MemoryBackend()  # type: ignore[abstract]

    def test_subclass_must_implement_ingest(self):
        Incomplete = type("Incomplete", (MemoryBackend,), _all_except("ingest"))
        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_search(self):
        Incomplete = type("Incomplete", (MemoryBackend,), _all_except("search"))
        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_stats(self):
        Incomplete = type("Incomplete", (MemoryBackend,), _all_except("stats"))
        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_reindex(self):
        Incomplete = type("Incomplete", (MemoryBackend,), _all_except("reindex"))
        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_get_project_documents(self):
        Incomplete = type("Incomplete", (MemoryBackend,), _all_except("get_project_documents"))
        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_complete_subclass_can_be_instantiated(self):
        Complete = type("Complete", (MemoryBackend,), _all_except())
        backend = Complete()
        assert isinstance(backend, MemoryBackend)
