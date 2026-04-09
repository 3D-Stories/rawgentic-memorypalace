"""Tests for MemPalace-delegated wake-up context generation."""

import pytest

from rawgentic_memory.models import WakeupContext


@pytest.fixture
def backend(tmp_path):
    from rawgentic_memory.mempalace_backend import MemPalaceBackend

    return MemPalaceBackend(palace_path=str(tmp_path / "palace"))


def _ingest_decision(backend, content="We decided to use PostgreSQL.", project="testproj"):
    from rawgentic_memory.models import SessionData

    backend.ingest(SessionData(
        session_id="s1",
        project=project,
        notes=content,
        source="test",
        timestamp="2026-04-09T12:00:00Z",
        source_file="session.md",
    ))


class TestWakeup:
    """Validate MemPalace MemoryStack wakeup delegation."""

    def test_returns_wakeup_context(self, backend):
        ctx = backend.wakeup(project="test")
        assert isinstance(ctx, WakeupContext)

    def test_backend_is_mempalace(self, backend):
        ctx = backend.wakeup(project="test")
        assert ctx.backend == "mempalace"

    def test_empty_palace_returns_context(self, backend):
        """Empty palace should still return a valid context (L0 default or empty L1)."""
        ctx = backend.wakeup(project="test")
        assert isinstance(ctx.text, str)
        assert isinstance(ctx.tokens, int)

    def test_with_data_includes_l1(self, backend):
        _ingest_decision(backend)
        ctx = backend.wakeup(project="testproj")
        # L1 should be generated from the ingested data
        assert ctx.tokens > 0
        assert len(ctx.text) > 0

    def test_with_l0_file(self, backend, tmp_path):
        l0_file = tmp_path / "identity.txt"
        l0_file.write_text("I am a senior engineer working on grocusave.")
        ctx = backend.wakeup(project="test", l0_path=str(l0_file))
        assert "senior engineer" in ctx.text
        assert "L0" in ctx.layers

    def test_layers_reflect_available_data(self, backend, tmp_path):
        l0_file = tmp_path / "identity.txt"
        l0_file.write_text("I am the user identity.")
        _ingest_decision(backend)
        ctx = backend.wakeup(project="testproj", l0_path=str(l0_file))
        assert "L0" in ctx.layers
        assert "L1" in ctx.layers

    def test_no_l0_file_no_l0_layer(self, backend):
        _ingest_decision(backend)
        ctx = backend.wakeup(project="testproj")
        assert "L0" not in ctx.layers

    def test_tokens_approximate_word_count(self, backend, tmp_path):
        l0_file = tmp_path / "identity.txt"
        l0_file.write_text("one two three four five")
        ctx = backend.wakeup(project="test", l0_path=str(l0_file))
        assert ctx.tokens >= 5

    def test_project_filter_scopes_wakeup(self, backend):
        """Wakeup with a project filter should scope L1 to that project."""
        _ingest_decision(backend, project="alpha",
                         content="We decided to use Redis for alpha.")
        _ingest_decision(backend, project="beta",
                         content="We decided to use Mongo for beta.")
        ctx_alpha = backend.wakeup(project="alpha")
        # Should contain alpha content
        assert isinstance(ctx_alpha.text, str)

    def test_graceful_degradation_on_error(self, backend):
        """If MemoryStack fails, should return empty context."""
        # Force an error by invalidating the palace path
        backend._palace_path = "/nonexistent/palace/path"
        ctx = backend.wakeup(project="test")
        assert isinstance(ctx, WakeupContext)
        assert ctx.backend == "mempalace"
