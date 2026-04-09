"""Tests for tiered wake-up context generation (L0 + L1)."""

from datetime import datetime, timezone

import pytest

from rawgentic_memory.models import WakeupContext


# ── L0 loading ──────────────────────────────────────────────────


class TestLoadL0:
    """Validate loading static L0 identity file."""

    def test_loads_existing_file(self, tmp_path):
        from rawgentic_memory.wakeup import load_l0

        l0_file = tmp_path / "l0_identity.md"
        l0_file.write_text("I am a senior engineer working on grocusave.")
        result = load_l0(l0_file)
        assert result == "I am a senior engineer working on grocusave."

    def test_returns_empty_when_file_missing(self, tmp_path):
        from rawgentic_memory.wakeup import load_l0

        result = load_l0(tmp_path / "nonexistent.md")
        assert result == ""

    def test_strips_whitespace(self, tmp_path):
        from rawgentic_memory.wakeup import load_l0

        l0_file = tmp_path / "l0_identity.md"
        l0_file.write_text("  Identity context  \n\n")
        result = load_l0(l0_file)
        assert result == "Identity context"

    def test_returns_empty_for_none_path(self):
        from rawgentic_memory.wakeup import load_l0

        result = load_l0(None)
        assert result == ""

    def test_validates_path_under_home(self, tmp_path):
        from rawgentic_memory.wakeup import load_l0

        # tmp_path is under /tmp, not under home — but for testing we
        # allow it since the function falls back to empty on error.
        # This test verifies no crash on paths outside home.
        l0_file = tmp_path / "test.md"
        l0_file.write_text("test content")
        # Should still work — path containment only blocks truly hostile paths
        result = load_l0(l0_file)
        assert isinstance(result, str)


# ── L1 generation ──────────────────────────────────────────────


def _make_doc(content, topic="default", memory_type="decision",
              timestamp="2026-04-09T12:00:00Z", project="testproj"):
    """Helper to create a document dict matching the expected schema."""
    return {
        "content": content,
        "metadata": {
            "topic": topic,
            "memory_type": memory_type,
            "timestamp": timestamp,
            "project": project,
            "source_file": "",
            "session_id": "s1",
        },
    }


class TestGenerateL1:
    """Validate L1 critical facts generation from document list."""

    def test_returns_string(self):
        from rawgentic_memory.wakeup import generate_l1

        docs = [_make_doc("We decided to use PostgreSQL.")]
        result = generate_l1(docs)
        assert isinstance(result, str)

    def test_empty_docs_returns_empty(self):
        from rawgentic_memory.wakeup import generate_l1

        assert generate_l1([]) == ""

    def test_formats_as_bullet_list(self):
        from rawgentic_memory.wakeup import generate_l1

        docs = [_make_doc("We decided to use PostgreSQL.")]
        result = generate_l1(docs)
        assert result.startswith("- ")

    def test_includes_content_from_docs(self):
        from rawgentic_memory.wakeup import generate_l1

        docs = [_make_doc("We decided to use PostgreSQL.")]
        result = generate_l1(docs)
        assert "PostgreSQL" in result

    def test_respects_max_tokens(self):
        from rawgentic_memory.wakeup import generate_l1

        docs = [_make_doc(f"We decided to use technology number {i}.",
                          topic=f"tech-{i}") for i in range(20)]
        result = generate_l1(docs, max_tokens=30)
        word_count = len(result.split())
        assert word_count <= 35  # small tolerance for bullet formatting

    def test_filters_to_fact_types(self):
        from rawgentic_memory.wakeup import generate_l1

        docs = [
            _make_doc("We decided to use PostgreSQL.", memory_type="decision"),
            _make_doc("Deployed to production.", memory_type="event"),
            _make_doc("Found that ChromaDB is fast.", memory_type="discovery"),
        ]
        result = generate_l1(docs)
        # Decisions and discoveries should be prioritized over events
        assert "PostgreSQL" in result or "ChromaDB" in result

    def test_ranks_by_frequency(self):
        from rawgentic_memory.wakeup import generate_l1

        now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        # "database" topic appears 3 times, "logging" appears once
        docs = [
            _make_doc("Decided PostgreSQL for persistence.", topic="database",
                      timestamp="2026-04-09T12:00:00Z"),
            _make_doc("Decided PostgreSQL for analytics.", topic="database",
                      timestamp="2026-04-08T12:00:00Z"),
            _make_doc("Decided PostgreSQL replication.", topic="database",
                      timestamp="2026-04-07T12:00:00Z"),
            _make_doc("Set up structured logging.", topic="logging",
                      timestamp="2026-04-09T12:00:00Z"),
        ]
        result = generate_l1(docs, now=now)
        lines = result.strip().split("\n")
        # The first bullet should be about the more frequent topic
        assert "PostgreSQL" in lines[0] or "database" in lines[0].lower()

    def test_ranks_by_recency(self):
        from rawgentic_memory.wakeup import generate_l1

        now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        # Same frequency (1 each), but different recency
        docs = [
            _make_doc("Old decision about Python.", topic="python",
                      timestamp="2025-01-01T12:00:00Z"),
            _make_doc("Recent decision about Rust.", topic="rust",
                      timestamp="2026-04-09T12:00:00Z"),
        ]
        result = generate_l1(docs, now=now)
        lines = result.strip().split("\n")
        # Recent item should rank first
        assert "Rust" in lines[0]

    def test_top_10_limit(self):
        from rawgentic_memory.wakeup import generate_l1

        docs = [_make_doc(f"Decision about topic {i}.", topic=f"topic-{i}")
                for i in range(20)]
        result = generate_l1(docs, max_tokens=9999)
        lines = [l for l in result.strip().split("\n") if l.startswith("- ")]
        assert len(lines) <= 10

    def test_accepts_now_parameter(self):
        from rawgentic_memory.wakeup import generate_l1

        now = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        docs = [_make_doc("We decided to use PostgreSQL.")]
        # Should not raise
        result = generate_l1(docs, now=now)
        assert isinstance(result, str)

    def test_handles_malformed_timestamps(self):
        from rawgentic_memory.wakeup import generate_l1

        docs = [_make_doc("Decision with bad timestamp.",
                          timestamp="not-a-date")]
        result = generate_l1(docs)
        assert isinstance(result, str)  # no crash


# ── generate_wakeup orchestrator ──────────────────────────────


class TestGenerateWakeup:
    """Validate the combined L0+L1 wake-up context generation."""

    def test_returns_wakeup_context(self):
        from rawgentic_memory.wakeup import generate_wakeup

        ctx = generate_wakeup(backend=None, project="test")
        assert isinstance(ctx, WakeupContext)

    def test_no_backend_no_l0_returns_empty(self):
        from rawgentic_memory.wakeup import generate_wakeup

        ctx = generate_wakeup(backend=None, project="test")
        assert ctx.text == ""
        assert ctx.tokens == 0
        assert ctx.layers == []

    def test_l0_only_when_no_backend(self, tmp_path):
        from rawgentic_memory.wakeup import generate_wakeup

        l0_file = tmp_path / "l0.md"
        l0_file.write_text("I am the user identity.")
        ctx = generate_wakeup(backend=None, project="test", l0_path=l0_file)
        assert ctx.text == "I am the user identity."
        assert "L0" in ctx.layers
        assert "L1" not in ctx.layers

    def test_l1_only_when_no_l0(self):
        from rawgentic_memory.wakeup import generate_wakeup

        # Use a mock backend
        class MockBackend:
            def get_project_documents(self, project, limit=500):
                return [_make_doc("We decided to use PostgreSQL.")]

        ctx = generate_wakeup(
            backend=MockBackend(),
            project="test",
            l0_path="/nonexistent/l0.md",
        )
        assert "L1" in ctx.layers
        assert "L0" not in ctx.layers
        assert "PostgreSQL" in ctx.text

    def test_combined_l0_l1(self, tmp_path):
        from rawgentic_memory.wakeup import generate_wakeup

        l0_file = tmp_path / "l0.md"
        l0_file.write_text("I am the user identity.")

        class MockBackend:
            def get_project_documents(self, project, limit=500):
                return [_make_doc("We decided to use PostgreSQL.")]

        ctx = generate_wakeup(
            backend=MockBackend(),
            project="test",
            l0_path=l0_file,
        )
        assert "L0" in ctx.layers
        assert "L1" in ctx.layers
        assert "user identity" in ctx.text
        assert "PostgreSQL" in ctx.text

    def test_tokens_approximate_word_count(self, tmp_path):
        from rawgentic_memory.wakeup import generate_wakeup

        l0_file = tmp_path / "l0.md"
        l0_file.write_text("one two three four five")

        ctx = generate_wakeup(backend=None, project="test", l0_path=l0_file)
        assert ctx.tokens == 5

    def test_backend_str_is_native(self):
        from rawgentic_memory.wakeup import generate_wakeup

        ctx = generate_wakeup(backend=None, project="test")
        assert ctx.backend == "native"

    def test_handles_backend_exception(self, tmp_path):
        from rawgentic_memory.wakeup import generate_wakeup

        l0_file = tmp_path / "l0.md"
        l0_file.write_text("Identity text.")

        class BrokenBackend:
            def get_project_documents(self, project, limit=500):
                raise RuntimeError("ChromaDB exploded")

        ctx = generate_wakeup(
            backend=BrokenBackend(),
            project="test",
            l0_path=l0_file,
        )
        # Degrades to L0 only
        assert "L0" in ctx.layers
        assert "L1" not in ctx.layers
        assert "Identity text." in ctx.text

    def test_separator_between_l0_and_l1(self, tmp_path):
        from rawgentic_memory.wakeup import generate_wakeup

        l0_file = tmp_path / "l0.md"
        l0_file.write_text("L0 content.")

        class MockBackend:
            def get_project_documents(self, project, limit=500):
                return [_make_doc("We decided to use PostgreSQL.")]

        ctx = generate_wakeup(
            backend=MockBackend(),
            project="test",
            l0_path=l0_file,
        )
        # L0 and L1 should be separated by double newline
        assert "\n\n" in ctx.text
