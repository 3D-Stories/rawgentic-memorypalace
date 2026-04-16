"""Tests for MempalaceAdapter — versioned wrapper around mempalace."""
import pytest
from rawgentic_memory.adapter import MempalaceAdapter, HealthStatus


class TestHealth:
    def test_health_returns_available_when_mempalace_present(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        h = adapter.health()
        assert isinstance(h, HealthStatus)
        assert h.available is True
        assert h.backend == "mempalace"
        assert h.version  # non-empty version string

    def test_health_returns_unavailable_when_palace_missing(self, tmp_path):
        nonexistent = tmp_path / "nope"
        adapter = MempalaceAdapter(palace_path=str(nonexistent))
        h = adapter.health()
        assert h.available is False
        assert h.doc_count == 0
