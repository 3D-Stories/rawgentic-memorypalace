"""Tests for MempalaceAdapter — versioned wrapper around mempalace."""
import pytest
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
        # Layer0 reads from ~/.mempalace/identity.txt, not from tmp_path, so it
        # returns default "No identity configured..." text in test isolation —
        # that's fine. The assertions below validate the method wires L0+L1 and
        # produces a non-empty token count regardless of identity content.
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        ctx = adapter.wakeup()
        assert isinstance(ctx, WakeupContext)
        assert "L0" in ctx.layers
        assert "L1" in ctx.layers
        assert ctx.tokens > 0

    def test_wakeup_returns_empty_when_mempalace_unavailable(
        self, tmp_path, monkeypatch, mock_mempalace_unavailable
    ):
        # mock_mempalace_unavailable sets sys.modules["mempalace"] = None.
        # We also null "mempalace.layers" in case a previous test has already
        # cached it — Python skips parent lookup when the submodule key exists.
        # Both entries set to None guarantee ModuleNotFoundError in wakeup()'s
        # lazy `from mempalace.layers import ...`, exercising the except branch.
        monkeypatch.setitem(__import__("sys").modules, "mempalace.layers", None)
        adapter = MempalaceAdapter(palace_path=str(tmp_path))
        ctx = adapter.wakeup()
        assert ctx.text == ""
        assert ctx.tokens == 0
        assert ctx.layers == []
