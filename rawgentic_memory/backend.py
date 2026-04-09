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

    @abstractmethod
    def get_project_documents(
        self, project: str, limit: int = 500,
    ) -> list[dict]:
        """Return all documents for a project as {content, metadata} dicts.

        Used by wake-up context generation for frequency/recency ranking.
        Each dict has keys ``"content"`` (str) and ``"metadata"`` (dict with
        ``topic``, ``timestamp``, ``memory_type``, ``project``,
        ``source_file``, ``session_id``).
        """
