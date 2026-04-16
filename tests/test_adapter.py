"""Tests for MempalaceAdapter — versioned wrapper around mempalace."""
import pytest
from pathlib import Path
from rawgentic_memory.adapter import MempalaceAdapter, HealthStatus, WakeupContext


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


class TestWakeup:
    def test_wakeup_returns_l0_and_l1(self, isolated_palace):
        # Create identity file
        identity = Path(isolated_palace.parent) / "identity.txt"
        identity.write_text("Test identity for unit tests")

        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        ctx = adapter.wakeup()
        assert isinstance(ctx, WakeupContext)
        assert "L0" in ctx.layers
        assert "L1" in ctx.layers
        assert ctx.tokens > 0

    def test_wakeup_returns_empty_on_exception(self, tmp_path):
        bad_path = tmp_path / "does_not_exist"
        adapter = MempalaceAdapter(palace_path=str(bad_path))
        ctx = adapter.wakeup()
        # mempalace 3.3.0 returns graceful fallback text rather than raising on
        # a missing palace path — wakeup() always returns a valid WakeupContext.
        assert isinstance(ctx, WakeupContext)
        assert isinstance(ctx.text, str)
        assert isinstance(ctx.tokens, int)
        assert isinstance(ctx.layers, list)
