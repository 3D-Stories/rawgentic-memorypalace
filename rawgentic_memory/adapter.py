"""
MempalaceAdapter — versioned wrapper around mempalace's Python API.

Bridge code calls this adapter — never mempalace directly.
Major version aligned with mempalace's major version.
"""
from dataclasses import dataclass
import logging
import os

logger = logging.getLogger("rawgentic_memory.adapter")


@dataclass
class HealthStatus:
    available: bool
    doc_count: int
    backend: str = "mempalace"
    version: str = ""


class MempalaceAdapter:
    CONTRACT_VERSION = 3
    MIN_VERSION = "3.3.0"
    MAX_VERSION = "4.0.0"

    def __init__(self, palace_path: str | None = None):
        self.palace_path = palace_path or os.path.expanduser("~/.mempalace/palace")

    def health(self) -> HealthStatus:
        try:
            from mempalace.palace import get_collection
            from mempalace.version import __version__ as mempalace_version
            if not os.path.isdir(self.palace_path):
                return HealthStatus(available=False, doc_count=0)
            col = get_collection(self.palace_path, create=True)
            return HealthStatus(
                available=True,
                doc_count=col.count(),
                version=mempalace_version,
            )
        except Exception as e:
            logger.debug("health check failed: %s", e)
            return HealthStatus(available=False, doc_count=0)
