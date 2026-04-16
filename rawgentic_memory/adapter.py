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

try:
    from mempalace.fact_checker import check_text
except ImportError:
    check_text = None


@dataclass
class ContractViolation:
    field: str
    expected: str
    actual: str
    severity: str = "warning"  # info | warning | error


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


@dataclass
class FactIssue:
    type: str  # similar_name | relationship_mismatch | stale_fact
    detail: str
    entity: str = ""
    span: str = ""


class MempalaceAdapter:
    CONTRACT_VERSION = 3
    MIN_VERSION = "3.3.0"
    MAX_VERSION = "4.0.0"
    BEHAVIORAL_CONTRACT = {
        "expected_mcp_tools": [
            "mempalace_search",
            "mempalace_add_drawer",
            "mempalace_diary_write",
            "mempalace_kg_query",
            "mempalace_kg_add",
            "mempalace_kg_invalidate",
        ],
        "expected_save_interval": 15,
        "expected_palace_dir": "~/.mempalace/palace",
        "expected_kg_path": "~/.mempalace/knowledge_graph.sqlite3",
    }
    MAX_CONTENT_CHARS_PER_RESULT = 1500
    TRUNCATION_MARKER = "... [truncated]"
    # -5: conservative pad for Unicode multi-byte chars counted differently by callers
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

    def fact_check(self, text: str) -> list[FactIssue]:
        try:
            if check_text is None:
                return []
            raw_issues = check_text(text, palace_path=self.palace_path)
            return [
                FactIssue(
                    type=i.get("type", "unknown"),
                    detail=i.get("detail", ""),
                    entity=i.get("entity", ""),
                    span=i.get("span", ""),
                )
                for i in raw_issues
            ]
        except Exception as e:
            logger.warning("fact_check failed: %s", e)
            return []

    def canary_write(self, fact: str) -> bool:
        """Test-only: write a canary fact to the 'canary' wing.
        Maintains the 'all writes go through adapter' invariant."""
        try:
            from mempalace.miner import add_drawer
            from mempalace.palace import get_collection
            col = get_collection(self.palace_path, create=True)
            add_drawer(
                col,
                wing="canary",
                room="canary",
                content=fact,
                source_file="canary.test",
                chunk_index=0,
                agent="canary_write",
            )
            return True
        except Exception as e:
            logger.warning("canary_write failed: %s", e)
            return False

    @staticmethod
    def _parse_version(vs: str) -> tuple[int, ...]:
        """Parse semver as tuple of ints. Critical: never compare versions as strings.
        '3.10.0' < '3.3.0' returns True lexically — wrong."""
        return tuple(int(x) for x in vs.split(".") if x.isdigit())

    def verify_behavioral_contract(self) -> list[ContractViolation]:
        """Probe the mempalace installation for compatibility violations.

        Returns a list of ContractViolation; empty list means all checks passed.
        Gracefully degrades: unreachable modules are caught, not crashed on.
        """
        violations: list[ContractViolation] = []
        try:
            import mempalace  # noqa: F401
        except ImportError:
            violations.append(ContractViolation(
                field="mempalace_module",
                expected="importable",
                actual="ImportError",
                severity="error",
            ))
            return violations

        # Check version bounds (tuple comparison, NOT string comparison)
        try:
            from mempalace.version import __version__ as v
            v_tuple = self._parse_version(v)
            min_tuple = self._parse_version(self.MIN_VERSION)
            max_tuple = self._parse_version(self.MAX_VERSION)
            if v_tuple < min_tuple:
                violations.append(ContractViolation(
                    field="mempalace_version",
                    expected=f">={self.MIN_VERSION}",
                    actual=v,
                    severity="error",
                ))
            if v_tuple >= max_tuple:
                violations.append(ContractViolation(
                    field="mempalace_version",
                    expected=f"<{self.MAX_VERSION}",
                    actual=v,
                    severity="warning",
                ))
        except Exception:
            pass

        # Check expected MCP tools are exposed by mempalace
        try:
            from mempalace import mcp_server as _mcp
            available_tools = set(getattr(_mcp, "TOOLS", {}).keys())
            for tool_name in self.BEHAVIORAL_CONTRACT.get("expected_mcp_tools", []):
                if tool_name not in available_tools:
                    violations.append(ContractViolation(
                        field=f"mcp_tool:{tool_name}",
                        expected="present",
                        actual="missing",
                        severity="warning",
                    ))
        except Exception:
            pass

        return violations

    def _search_via_cli(
        self,
        query: str,
        project: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """CLI fallback when Python API import failed.

        mempalace 3.3.0 CLI lacks --json output, so this is a best-effort
        stub that returns [] rather than attempting fragile text parsing.
        """
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
