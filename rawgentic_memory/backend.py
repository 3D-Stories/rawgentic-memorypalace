"""Abstract base class for memory backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from rawgentic_memory.models import (
    BackendStats,
    IngestResult,
    SearchResult,
    SessionData,
)


class MemoryBackend(ABC):
    """Interface that all memory backends must implement."""

    @abstractmethod
    def ingest(self, session_data: SessionData) -> IngestResult:
        """Index session data into the backend store."""

    @abstractmethod
    def search(
        self,
        query: str,
        project: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Search for memories by semantic similarity."""

    @abstractmethod
    def stats(self) -> BackendStats:
        """Return backend status and statistics."""

    @abstractmethod
    def reindex(self, source_dirs: list[str]) -> IngestResult:
        """Rebuild the index from source files."""
