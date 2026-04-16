"""
MempalaceAdapter — versioned wrapper around mempalace's Python API.

Bridge code calls this adapter — never mempalace directly.
Major version aligned with mempalace's major version.
"""
from dataclasses import dataclass, field
import logging
import os

logger = logging.getLogger("rawgentic_memory.adapter")


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


class MempalaceAdapter:
    CONTRACT_VERSION = 3
    MIN_VERSION = "3.3.0"
    MAX_VERSION = "4.0.0"

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
