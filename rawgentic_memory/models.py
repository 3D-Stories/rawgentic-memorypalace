"""Shared data types for the rawgentic-memorypalace memory system."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionData:
    """Input to the ingest pipeline — one session's worth of data."""

    session_id: str
    project: str
    notes: str
    source: str  # "precompact" | "stop" | "timer" | "manual"
    timestamp: str  # ISO 8601
    source_file: str = ""
    wal_entries: list[dict] = field(default_factory=list)


@dataclass
class EnrichedSegment:
    """One extracted memory segment from enrichment."""

    content: str
    memory_type: str  # decision | event | discovery | preference | artifact
    topic: str
    source_file: str = ""
    session_id: str = ""
    timestamp: str = ""
    project: str = ""


@dataclass
class SearchResult:
    """A single search result with similarity score and full metadata."""

    content: str
    project: str
    memory_type: str
    topic: str
    similarity: float
    source_file: str = ""
    session_id: str = ""
    timestamp: str = ""


@dataclass
class IngestResult:
    """Summary of an ingest operation."""

    indexed: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass
class BackendStats:
    """Backend status and statistics."""

    available: bool = False
    doc_count: int = 0
    last_ingest: str | None = None
    index_size_bytes: int = 0
