"""MemPalace backend bridge — thin adapter between our server and mempalace library.

Uses mempalace's palace structure (single 'mempalace_drawers' collection with
wing/room metadata) while adding our custom metadata (memory_type, session_id,
timestamp) for richer search and filtering.

Calls collection.upsert() directly rather than add_drawer() because:
1. We need upsert semantics (idempotent re-ingest after LRU offset eviction)
2. We need custom metadata fields that add_drawer() doesn't support
3. We still set wing/room/source_file in metadata for MemPalace tool compatibility
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

from rawgentic_memory.enrichment import enrich
from rawgentic_memory.models import (
    BackendStats,
    IngestResult,
    SearchResult,
    SessionData,
    WakeupContext,
)

logger = logging.getLogger(__name__)

try:
    from mempalace.miner import get_collection
    from mempalace.layers import MemoryStack
    from mempalace.config import DEFAULT_PALACE_PATH
    from mempalace.knowledge_graph import KnowledgeGraph

    MEMPALACE_AVAILABLE = True
except ImportError:
    MEMPALACE_AVAILABLE = False
    DEFAULT_PALACE_PATH = None

_KG_DECISION_PREDICATE = "decided"


def _drawer_id(wing: str, room: str, source_file: str, chunk_index: int) -> str:
    """Generate a deterministic drawer ID matching mempalace's format."""
    hash_input = source_file + str(chunk_index)
    return f"drawer_{wing}_{room}_{hashlib.md5(hash_input.encode()).hexdigest()[:16]}"


class MemPalaceBackend:
    """Thin bridge to mempalace library for storage, search, and wakeup."""

    def __init__(self, palace_path: str | None = None):
        if not MEMPALACE_AVAILABLE:
            raise ImportError("mempalace is not installed")

        self._palace_path = palace_path or DEFAULT_PALACE_PATH
        self._collection = get_collection(self._palace_path)
        self._available = True
        self._last_ingest: str | None = None

        # KG co-located with palace — graceful degradation if init fails
        self._kg = None
        try:
            kg_path = str(Path(self._palace_path).parent / "knowledge_graph.sqlite3")
            self._kg = KnowledgeGraph(db_path=kg_path)
        except Exception:
            logger.warning("KG initialization failed, KG features disabled", exc_info=True)

    def ingest(self, session_data: SessionData) -> IngestResult:
        """Enrich session data and store via MemPalace palace structure."""
        segments = enrich(session_data.notes, session_data.source_file)
        if not segments:
            return IngestResult(indexed=0, skipped=0, errors=0)

        ids = []
        documents = []
        metadatas = []

        for i, seg in enumerate(segments):
            seg.session_id = session_data.session_id
            seg.timestamp = session_data.timestamp
            seg.project = session_data.project
            if not seg.source_file:
                seg.source_file = session_data.source_file

            room = seg.topic if seg.topic else "general"

            drawer_id = _drawer_id(
                wing=session_data.project,
                room=room,
                source_file=seg.source_file,
                chunk_index=i,
            )
            ids.append(drawer_id)
            documents.append(seg.content)
            metadatas.append({
                # MemPalace standard fields (for MCP tool compatibility)
                "wing": session_data.project,
                "room": room,
                "source_file": seg.source_file,
                "chunk_index": i,
                "added_by": "rawgentic",
                "filed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                # Our custom fields
                "memory_type": seg.memory_type,
                "session_id": seg.session_id,
                "timestamp": seg.timestamp,
                "project": session_data.project,
                "topic": seg.topic,
            })

        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        self._last_ingest = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # KG side-channel: create triples for decision-type segments
        if self._kg is not None:
            for seg in segments:
                if seg.memory_type == "decision":
                    try:
                        self._kg.add_triple(
                            subject=session_data.project,
                            predicate=_KG_DECISION_PREDICATE,
                            obj=seg.content,
                            valid_from=session_data.timestamp,
                        )
                    except Exception:
                        logger.warning("KG triple creation failed", exc_info=True)

        return IngestResult(indexed=len(ids), skipped=0, errors=0)

    def search(
        self,
        query: str,
        project: str | None = None,
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Search palace via ChromaDB with optional post-filtering."""
        if self._collection.count() == 0:
            return []

        # Build where filter for wing (project)
        where: dict | None = None
        if project:
            where = {"wing": project}

        # Over-request when post-filtering by memory_type
        n_results = min(limit * 3, self._collection.count()) if memory_type else min(limit, self._collection.count())

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            logger.exception("ChromaDB query failed")
            return []

        if not results["ids"] or not results["ids"][0]:
            return []

        all_results: list[SearchResult] = []

        for i, doc_id in enumerate(results["ids"][0]):
            doc = results["documents"][0][i] if results["documents"] else ""
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            dist = results["distances"][0][i] if results["distances"] else 1.0

            # Convert L2 distance to 0-1 similarity
            similarity = max(0.0, 1.0 / (1.0 + abs(dist)))

            sr = SearchResult(
                content=doc,
                project=meta.get("wing", meta.get("project", "")),
                memory_type=meta.get("memory_type", ""),
                topic=meta.get("room", meta.get("topic", "")),
                similarity=round(similarity, 4),
                source_file=meta.get("source_file", ""),
                session_id=meta.get("session_id", ""),
                timestamp=meta.get("timestamp", ""),
            )

            # Post-filter by memory_type if requested
            if memory_type and sr.memory_type != memory_type:
                continue

            all_results.append(sr)

        all_results.sort(key=lambda r: r.similarity, reverse=True)
        return all_results[:limit]

    def get_project_documents(
        self, project: str, limit: int = 500,
    ) -> list[dict]:
        """Return all documents for a project (wing) as {content, metadata} dicts."""
        if self._collection.count() == 0:
            return []

        try:
            result = self._collection.get(
                where={"wing": project},
                include=["metadatas", "documents"],
                limit=min(self._collection.count(), limit),
            )
        except Exception:
            logger.exception("Failed to get project documents for %s", project)
            return []

        docs: list[dict] = []
        for i, doc_id in enumerate(result["ids"]):
            docs.append({
                "content": result["documents"][i],
                "metadata": result["metadatas"][i],
            })
        return docs

    def query_entity(self, name: str, as_of: str | None = None) -> list[dict]:
        """Query KG for all triples involving an entity."""
        if self._kg is None:
            return []
        try:
            return self._kg.query_entity(name, as_of=as_of, direction="outgoing")
        except Exception:
            logger.warning("KG query_entity failed for %s", name, exc_info=True)
            return []

    def stats(self) -> BackendStats:
        """Return backend status and document counts."""
        try:
            count = self._collection.count()
        except Exception:
            return BackendStats(available=False, doc_count=0)

        return BackendStats(
            available=self._available,
            doc_count=count,
            last_ingest=self._last_ingest,
        )

    def wakeup(self, project: str | None = None, l0_path: str | None = None) -> WakeupContext:
        """Delegate wake-up to MemPalace's MemoryStack."""
        try:
            stack = MemoryStack(
                palace_path=self._palace_path,
                identity_path=l0_path,
            )
            text = stack.wake_up(wing=project or None)
            status = stack.status()

            layers = []
            if l0_path and Path(l0_path).is_file():
                layers.append("L0")
            if status.get("total_drawers", 0) > 0:
                layers.append("L1")

            tokens = len(text.split()) if text else 0

            return WakeupContext(
                text=text,
                tokens=tokens,
                layers=layers,
                backend="mempalace",
            )
        except Exception:
            logger.warning("MemPalace wakeup failed", exc_info=True)
            return WakeupContext(text="", tokens=0, layers=[], backend="mempalace")

    def reindex(self, source_dirs: list[str]) -> IngestResult:
        """Rebuild index from source files using our enrichment pipeline."""
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
