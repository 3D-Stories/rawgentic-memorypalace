"""Tests for the MemoryBackend abstract base class."""

import pytest

from rawgentic_memory.backend import MemoryBackend
from rawgentic_memory.models import (
    BackendStats,
    IngestResult,
    SearchResult,
    SessionData,
)


class TestMemoryBackendABC:
    """Validate MemoryBackend cannot be instantiated and defines the contract."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            MemoryBackend()  # type: ignore[abstract]

    def test_subclass_must_implement_ingest(self):
        class Incomplete(MemoryBackend):
            def search(self, query, project=None, memory_type=None, limit=10):
                return []

            def stats(self):
                return BackendStats()

            def reindex(self, source_dirs):
                return IngestResult()

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_search(self):
        class Incomplete(MemoryBackend):
            def ingest(self, session_data):
                return IngestResult()

            def stats(self):
                return BackendStats()

            def reindex(self, source_dirs):
                return IngestResult()

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_stats(self):
        class Incomplete(MemoryBackend):
            def ingest(self, session_data):
                return IngestResult()

            def search(self, query, project=None, memory_type=None, limit=10):
                return []

            def reindex(self, source_dirs):
                return IngestResult()

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_reindex(self):
        class Incomplete(MemoryBackend):
            def ingest(self, session_data):
                return IngestResult()

            def search(self, query, project=None, memory_type=None, limit=10):
                return []

            def stats(self):
                return BackendStats()

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_complete_subclass_can_be_instantiated(self):
        class Complete(MemoryBackend):
            def ingest(self, session_data):
                return IngestResult()

            def search(self, query, project=None, memory_type=None, limit=10):
                return []

            def stats(self):
                return BackendStats()

            def reindex(self, source_dirs):
                return IngestResult()

        backend = Complete()
        assert isinstance(backend, MemoryBackend)
