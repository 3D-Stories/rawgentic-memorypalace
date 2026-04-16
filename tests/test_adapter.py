"""Tests for MempalaceAdapter — versioned wrapper around mempalace."""
import pytest
from rawgentic_memory.adapter import MempalaceAdapter, HealthStatus, WakeupContext, SearchResult, FactIssue


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


class TestSearch:
    def test_search_empty_palace_returns_empty_list(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        results = adapter.search("anything")
        assert results == []

    def test_search_returns_empty_on_api_exception(self):
        """search_memories raises -> catch path returns []."""
        from unittest.mock import patch

        adapter = MempalaceAdapter(palace_path="/tmp")
        with patch(
            "rawgentic_memory.adapter.search_memories",
            side_effect=RuntimeError("boom"),
        ):
            results = adapter.search("query")
        assert results == []

    def test_search_returns_empty_when_api_unavailable(self):
        """search_memories is None (import failed) -> CLI fallback.

        CLI fallback also fails (no --json) -> returns [].
        """
        from unittest.mock import patch

        adapter = MempalaceAdapter(palace_path="/tmp")
        with patch("rawgentic_memory.adapter.search_memories", None):
            results = adapter.search("query")
        assert results == []

    def test_search_filters_by_memory_type(self):
        from unittest.mock import patch

        adapter = MempalaceAdapter(palace_path="/tmp")
        fake_results = {
            "results": [
                {"text": "decision content", "wing": "p", "memory_type": "decision"},
                {"text": "event content", "wing": "p", "memory_type": "event"},
            ]
        }
        with patch(
            "rawgentic_memory.adapter.search_memories", return_value=fake_results
        ):
            results = adapter.search("q", memory_type="decision")
        assert len(results) == 1
        assert results[0].memory_type == "decision"

    def test_search_filters_by_flag(self):
        from unittest.mock import patch

        adapter = MempalaceAdapter(palace_path="/tmp")
        fake_results = {
            "results": [
                {"text": "flagged", "wing": "p", "flag": "important"},
                {"text": "unflagged", "wing": "p"},
            ]
        }
        with patch(
            "rawgentic_memory.adapter.search_memories", return_value=fake_results
        ):
            results = adapter.search("q", flag="important")
        assert len(results) == 1
        assert results[0].flag == "important"

    def test_search_truncates_long_content(self):
        from unittest.mock import patch

        adapter = MempalaceAdapter(palace_path="/tmp")
        long_text = "x" * 5000
        fake_results = {"results": [{"text": long_text, "wing": "p"}]}
        with patch(
            "rawgentic_memory.adapter.search_memories", return_value=fake_results
        ):
            results = adapter.search("q")
        assert len(results) == 1
        assert len(results[0].content) <= adapter.MAX_CONTENT_CHARS_PER_RESULT
        assert "[truncated]" in results[0].content

    def test_search_preserves_short_content(self):
        from unittest.mock import patch

        adapter = MempalaceAdapter(palace_path="/tmp")
        short_text = "short content"
        fake_results = {"results": [{"text": short_text, "wing": "p"}]}
        with patch(
            "rawgentic_memory.adapter.search_memories", return_value=fake_results
        ):
            results = adapter.search("q")
        assert len(results) == 1
        assert results[0].content == short_text

    def test_search_maps_all_fields(self):
        from unittest.mock import patch

        adapter = MempalaceAdapter(palace_path="/tmp")
        fake_results = {
            "results": [
                {
                    "text": "content here",
                    "wing": "myproject",
                    "room": "architecture",
                    "source_file": "DECISIONS.md",
                    "similarity": 0.85,
                    "memory_type": "decision",
                    "timestamp": "2025-01-15",
                    "flag": "pinned",
                }
            ]
        }
        with patch(
            "rawgentic_memory.adapter.search_memories", return_value=fake_results
        ):
            results = adapter.search("q")
        assert len(results) == 1
        r = results[0]
        assert r.content == "content here"
        assert r.project == "myproject"
        assert r.topic == "architecture"
        assert r.source_file == "DECISIONS.md"
        assert r.similarity == 0.85
        assert r.memory_type == "decision"
        assert r.timestamp == "2025-01-15"
        assert r.flag == "pinned"


class TestFactCheck:
    def test_fact_check_clean_text_returns_empty(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        issues = adapter.fact_check("This is benign text with no entity claims.")
        assert issues == []

    def test_fact_check_returns_empty_on_exception(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        with patch("rawgentic_memory.adapter.check_text", side_effect=RuntimeError("boom")):
            issues = adapter.fact_check("anything")
        assert issues == []

    def test_fact_check_maps_similar_name_format(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        fake_upstream = [{
            "type": "similar_name",
            "detail": "'Mlls' mentioned — did you mean 'Milla'? (edit distance 2)",
            "names": ["Mlls", "Milla"],
            "distance": 2,
        }]
        with patch("rawgentic_memory.adapter.check_text", return_value=fake_upstream):
            issues = adapter.fact_check("Mlls said hi")
        assert len(issues) == 1
        assert issues[0].type == "similar_name"
        assert "Mlls" in issues[0].detail
