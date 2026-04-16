"""
MempalaceAdapter — versioned wrapper around mempalace's Python API.

Bridge code calls this adapter — never mempalace directly.
Major version aligned with mempalace's major version.
"""
from dataclasses import dataclass, field
import logging
import os

logger = logging.getLogger("rawgentic_memory.adapter")

try:
    from mempalace.searcher import search_memories
except ImportError:
    search_memories = None


@dataclass
class HealthStatus:
    available: bool
    doc_count: int
    backend: str = "mempalace"
    version: str = ""


@dataclass
class WakeupContext:
    text: str
    tokens: int
    layers: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    content: str
    memory_type: str = ""
    topic: str = ""
    similarity: float = 0.0
    project: str = ""
    timestamp: str = ""
    source_file: str = ""
    flag: str | None = None


class MempalaceAdapter:
    CONTRACT_VERSION = 3
    MIN_VERSION = "3.3.0"
    MAX_VERSION = "4.0.0"
    MAX_CONTENT_CHARS_PER_RESULT = 1500
    TRUNCATION_MARKER = "... [truncated]"
    TRUNCATION_BUDGET = MAX_CONTENT_CHARS_PER_RESULT - len(TRUNCATION_MARKER) - 5

    def __init__(self, palace_path: str | None = None):
        self.palace_path = palace_path or os.path.expanduser("~/.mempalace/palace")

    def wakeup(self, project: str | None = None) -> WakeupContext:
        try:
            from mempalace.layers import Layer0, Layer1
            l0 = Layer0().render()
            l1 = Layer1(palace_path=self.palace_path, wing=project).generate()
            text = f"{l0}\n\n{l1}"
            # Token estimate: chars/4 ±25% — over for code-heavy, under for NL.
            return WakeupContext(text=text, tokens=len(text) // 4, layers=["L0", "L1"])
        except Exception as e:
            logger.warning("wakeup failed: %s", e)
            return WakeupContext(text="", tokens=0, layers=[])

    def health(self) -> HealthStatus:
        try:
            from mempalace.palace import get_collection
            from mempalace.version import __version__ as mempalace_version
            if not os.path.isdir(self.palace_path):
                return HealthStatus(available=False, doc_count=0)
            # create=True: get_collection(create=False) raises on empty palace dirs.
            # Side-effect (mkdir + get_or_create_collection) is acceptable for health.
            col = get_collection(self.palace_path, create=True)
            return HealthStatus(
                available=True,
                doc_count=col.count(),
                version=mempalace_version,
            )
        except Exception as e:
            logger.debug("health check failed: %s", e)
            return HealthStatus(available=False, doc_count=0)

    def search(
        self,
        query: str,
        project: str | None = None,
        memory_type: str | None = None,
        flag: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        try:
            if search_memories is None:
                return self._search_via_cli(query, project=project, limit=limit)
            raw = search_memories(
                query, self.palace_path, wing=project, n_results=limit
            )
            results: list[SearchResult] = []
            for h in raw.get("results", []):
                sr = SearchResult(
                    content=h.get("text", ""),
                    memory_type=h.get("memory_type", ""),
                    topic=h.get("room", ""),
                    similarity=float(h.get("similarity", 0.0)),
                    project=h.get("wing", ""),
                    timestamp=h.get("timestamp", ""),
                    source_file=h.get("source_file", ""),
                    flag=h.get("flag"),
                )
                results.append(sr)
            if memory_type:
                results = [
                    item for item in results if item.memory_type == memory_type
                ]
            if flag:
                results = [item for item in results if item.flag == flag]
            for item in results:
                if len(item.content) > self.MAX_CONTENT_CHARS_PER_RESULT:
                    item.content = (
                        item.content[: self.TRUNCATION_BUDGET]
                        + self.TRUNCATION_MARKER
                    )
            return results
        except Exception as e:
            logger.warning("search failed: %s", e)
            return []

    def _search_via_cli(
        self,
        query: str,
        project: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """CLI fallback when Python API import failed.

        The CLI lacks --json output, so this parses structured text.
        Falls back to empty results on any parse failure.
        """
        import json as _json
        import subprocess

        try:
            cmd = [
                "mempalace",
                "search",
                query,
                "--results",
                str(limit),
            ]
            if project:
                cmd += ["--wing", project]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=3
            )
            if result.returncode != 0:
                return []
            # CLI output is human-readable text, not JSON.
            # Without --json support, this fallback is best-effort.
            # Return empty rather than attempt fragile text parsing.
            logger.debug(
                "CLI search returned text output; "
                "structured parsing not available without --json flag"
            )
            return []
        except Exception as e:
            logger.warning("CLI search fallback failed: %s", e)
            return []
