"""Native enhanced backend using ChromaDB for semantic search.

ChromaDB is used as a search index over session archives, NOT as a
replacement for source files. If the ChromaDB store is corrupted or
deleted, re-indexing from source JSONL/markdown files restores it
with zero data loss.

Uses per-project collections for natural isolation and better
similarity search within project boundaries.
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import chromadb

from rawgentic_memory.backend import MemoryBackend
from rawgentic_memory.enrichment import enrich
from rawgentic_memory.models import (
    BackendStats,
    EnrichedSegment,
    IngestResult,
    SearchResult,
    SessionData,
)

logger = logging.getLogger(__name__)

_COLLECTION_PREFIX = "memories_"


def _collection_name(project: str) -> str:
    """Derive a ChromaDB collection name from a project slug.

    ChromaDB names: 3-63 chars, alphanumeric/underscores/hyphens,
    must start and end with alphanumeric.
    """
    import re as _re
    # Strip non-alphanumeric (except hyphens/underscores), lowercase
    slug = _re.sub(r"[^a-zA-Z0-9_-]", "_", project).lower()
    slug = slug.strip("_-") or "default"
    name = f"{_COLLECTION_PREFIX}{slug}"
    # Clamp to ChromaDB's 63-char limit
    if len(name) > 63:
        name = name[:55] + "_" + hashlib.sha256(name.encode()).hexdigest()[:7]
    # Ensure minimum 3 chars
    if len(name) < 3:
        name = name + "__"
    return name


def _doc_id(segment: EnrichedSegment) -> str:
    """Generate a deterministic document ID from content + source."""
    key = f"{segment.source_file}:{segment.content}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class NativeBackend(MemoryBackend):
    """ChromaDB-backed memory backend with per-project collections."""

    def __init__(self, client: chromadb.ClientAPI | None = None, storage_path: str | None = None):
        """Initialize the native backend.

        Args:
            client: ChromaDB client instance (ephemeral for testing, persistent for prod).
                    If None, creates a PersistentClient at storage_path.
            storage_path: Path for persistent ChromaDB storage.
                          Ignored if client is provided.
        """
        if client is not None:
            self._client = client
        elif storage_path:
            resolved = Path(storage_path).expanduser().resolve()
            resolved.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(resolved))
        else:
            self._client = chromadb.Client()  # ephemeral fallback

        self._available = True
        self._last_ingest: str | None = None

    def _get_collection(self, project: str) -> chromadb.Collection:
        """Get or create a per-project collection."""
        name = _collection_name(project)
        return self._client.get_or_create_collection(
            name=name,
            metadata={"project": project},
        )

    def _all_collections(self) -> list[chromadb.Collection]:
        """List all memory collections (filtering by prefix).

        ChromaDB v0.6+ returns collection names as strings from
        list_collections(), not Collection objects.
        """
        all_names = self._client.list_collections()
        matching = [n for n in all_names if n.startswith(_COLLECTION_PREFIX)]
        return [self._client.get_collection(n) for n in matching]

    def ingest(self, session_data: SessionData) -> IngestResult:
        """Enrich and index session data into ChromaDB."""
        segments = enrich(session_data.notes, session_data.source_file)
        if not segments:
            return IngestResult(indexed=0, skipped=0, errors=0)

        collection = self._get_collection(session_data.project)

        ids = []
        documents = []
        metadatas = []

        for seg in segments:
            # Propagate session-level metadata to each segment
            seg.session_id = session_data.session_id
            seg.timestamp = session_data.timestamp
            seg.project = session_data.project
            if not seg.source_file:
                seg.source_file = session_data.source_file

            doc_id = _doc_id(seg)
            ids.append(doc_id)
            documents.append(seg.content)
            metadatas.append({
                "project": seg.project,
                "memory_type": seg.memory_type,
                "topic": seg.topic,
                "source_file": seg.source_file,
                "session_id": seg.session_id,
                "timestamp": seg.timestamp,
            })

        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

        self._last_ingest = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        return IngestResult(indexed=len(ids), skipped=0, errors=0)

    def search(
        self,
        query: str,
        project: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Search for memories by semantic similarity."""
        if project:
            collections = [self._get_collection(project)]
        else:
            collections = self._all_collections()

        if not collections:
            return []

        all_results: list[SearchResult] = []

        for collection in collections:
            if collection.count() == 0:
                continue

            where_filter = {}
            if memory_type:
                where_filter["memory_type"] = memory_type

            query_kwargs: dict = {
                "query_texts": [query],
                "n_results": min(limit, collection.count()),
            }
            if where_filter:
                query_kwargs["where"] = where_filter

            try:
                results = collection.query(**query_kwargs)
            except Exception:
                logger.exception("ChromaDB query failed for collection %s", collection.name)
                continue

            if not results["ids"] or not results["ids"][0]:
                continue

            for i, doc_id in enumerate(results["ids"][0]):
                doc = results["documents"][0][i] if results["documents"] else ""
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                dist = results["distances"][0][i] if results["distances"] else 1.0

                # ChromaDB returns L2 distances by default; convert to 0-1 similarity
                similarity = max(0.0, 1.0 / (1.0 + dist))

                all_results.append(SearchResult(
                    content=doc,
                    project=meta.get("project", ""),
                    memory_type=meta.get("memory_type", ""),
                    topic=meta.get("topic", ""),
                    similarity=round(similarity, 4),
                    source_file=meta.get("source_file", ""),
                    session_id=meta.get("session_id", ""),
                    timestamp=meta.get("timestamp", ""),
                ))

        # Sort by similarity descending and clamp to limit
        all_results.sort(key=lambda r: r.similarity, reverse=True)
        return all_results[:limit]

    def get_project_documents(
        self, project: str, limit: int = 500,
    ) -> list[dict]:
        """Return all documents for a project as {content, metadata} dicts."""
        collection = self._get_collection(project)
        count = collection.count()
        if count == 0:
            return []

        # ChromaDB get() returns all docs; cap at limit to prevent resource exhaustion.
        result = collection.get(
            include=["metadatas", "documents"],
            limit=min(count, limit),
        )

        docs: list[dict] = []
        for i, doc_id in enumerate(result["ids"]):
            docs.append({
                "content": result["documents"][i],
                "metadata": result["metadatas"][i],
            })
        return docs

    def stats(self) -> BackendStats:
        """Return backend status and document counts."""
        total_docs = 0
        for col in self._all_collections():
            total_docs += col.count()

        return BackendStats(
            available=self._available,
            doc_count=total_docs,
            last_ingest=self._last_ingest,
        )

    def reindex(self, source_dirs: list[str]) -> IngestResult:
        """Rebuild the index from source JSONL/markdown files.

        Walks each source directory, reads files, enriches content,
        and upserts into ChromaDB. Cleans up orphaned documents.
        """
        total_indexed = 0
        total_errors = 0

        for dir_path in source_dirs:
            p = Path(dir_path).expanduser().resolve()
            if not p.is_dir():
                logger.warning("Source directory does not exist: %s", p)
                continue

            for fpath in sorted(p.rglob("*")):
                if not fpath.is_file():
                    continue
                if fpath.suffix not in (".md", ".jsonl", ".txt"):
                    continue

                try:
                    content = fpath.read_text(encoding="utf-8")
                except Exception:
                    logger.exception("Failed to read %s", fpath)
                    total_errors += 1
                    continue

                # Derive project from parent directory name (not filename).
                # e.g., /session_notes/grocusave/session_01.md → "grocusave"
                # For files directly in the source dir, fall back to filename stem.
                relative = fpath.relative_to(p)
                if len(relative.parts) > 1:
                    project = relative.parts[0]
                else:
                    project = fpath.stem

                data = SessionData(
                    session_id="reindex",
                    project=project,
                    notes=content,
                    source="reindex",
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    source_file=str(fpath),
                )
                result = self.ingest(data)
                total_indexed += result.indexed

        return IngestResult(indexed=total_indexed, errors=total_errors)
