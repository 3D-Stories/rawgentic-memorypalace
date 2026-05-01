"""Tests for MempalaceAdapter — versioned wrapper around mempalace."""
import pytest
from rawgentic_memory.adapter import (
    MempalaceAdapter,
    HealthStatus,
    WakeupContext,
    SearchResult,
    FactIssue,
    ContractViolation,
    TunnelLink,
)


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
    def test_wakeup_with_project_returns_tunnel_context(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        ctx = adapter.wakeup(project="rawgentic_memorypalace")
        assert isinstance(ctx, WakeupContext)
        assert "L0" not in ctx.layers
        assert "L1" not in ctx.layers

    def test_wakeup_without_project_returns_empty(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        ctx = adapter.wakeup(project=None)
        assert ctx.text == ""
        assert ctx.tokens == 0
        assert ctx.layers == []

    def test_wakeup_graceful_on_import_error(self, tmp_path, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules, "mempalace.palace_graph", None)
        monkeypatch.setitem(__import__("sys").modules, "mempalace", None)
        adapter = MempalaceAdapter(palace_path=str(tmp_path))
        ctx = adapter.wakeup(project="test")
        assert ctx.text == ""
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


class TestCanaryWrite:
    def test_canary_write_returns_true_on_success(self):
        from unittest.mock import patch, MagicMock
        adapter = MempalaceAdapter(palace_path="/tmp")
        mock_col = MagicMock()
        # Lazy imports inside canary_write() — patch at source module
        with patch("mempalace.palace.get_collection", return_value=mock_col), \
             patch("mempalace.miner.add_drawer") as mock_add:
            result = adapter.canary_write("test fact")
        assert result is True
        mock_add.assert_called_once()
        # Verify canary wing routing
        _, kwargs = mock_add.call_args
        assert kwargs.get("wing") == "canary"

    def test_canary_write_returns_false_on_exception(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        with patch("mempalace.palace.get_collection", side_effect=RuntimeError("boom")):
            result = adapter.canary_write("test fact")
        assert result is False


class TestVersionValidation:
    def test_min_version_constant(self):
        assert MempalaceAdapter.MIN_VERSION == "3.3.0"

    def test_max_version_constant(self):
        assert MempalaceAdapter.MAX_VERSION == "4.0.0"

    def test_contract_version_constant(self):
        assert MempalaceAdapter.CONTRACT_VERSION == 3


class TestBehavioralContract:
    def test_verify_returns_list(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        violations = adapter.verify_behavioral_contract()
        assert isinstance(violations, list)

    def test_verify_handles_missing_mempalace(self, mock_mempalace_unavailable, tmp_path):
        adapter = MempalaceAdapter(palace_path=str(tmp_path))
        violations = adapter.verify_behavioral_contract()
        assert any(v.field == "mempalace_module" for v in violations)

    def test_behavioral_contract_lists_expected_mcp_tools(self):
        tools = MempalaceAdapter.CRITICAL_MCP_TOOLS
        assert "mempalace_search" in tools
        assert "mempalace_add_drawer" in tools
        assert "mempalace_diary_write" in tools

    def test_verify_detects_missing_mcp_tool(self, isolated_palace, monkeypatch):
        import sys
        import mempalace
        import mempalace.mcp_server  # noqa: F401
        from unittest.mock import MagicMock
        fake_mcp = MagicMock()
        fake_mcp.TOOLS = {"mempalace_search": object()}
        monkeypatch.setitem(sys.modules, "mempalace.mcp_server", fake_mcp)
        monkeypatch.setattr(mempalace, "mcp_server", fake_mcp)
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        violations = adapter.verify_behavioral_contract()
        missing_fields = [v.field for v in violations]
        assert "mcp_tool:mempalace_add_drawer" in missing_fields
        tool_violations = [v for v in violations if v.field.startswith("mcp_tool:")]
        assert all(v.severity == "error" for v in tool_violations)

    def test_critical_tools_is_subset_of_available(self):
        """Critical tools are the ones the adapter directly calls."""
        critical = MempalaceAdapter.CRITICAL_MCP_TOOLS
        assert "mempalace_search" in critical
        assert "mempalace_add_drawer" in critical
        assert "mempalace_diary_write" in critical
        assert len(critical) <= 10

    def test_verify_reports_tool_count(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        violations = adapter.verify_behavioral_contract()
        critical_missing = [v for v in violations if v.field.startswith("mcp_tool:")]
        assert critical_missing == []

    def test_verify_reports_missing_critical_tool(self, isolated_palace, monkeypatch):
        import sys
        import mempalace
        import mempalace.mcp_server  # noqa: F401
        from unittest.mock import MagicMock
        fake_mcp = MagicMock()
        fake_mcp.TOOLS = {"mempalace_search": object()}
        monkeypatch.setitem(sys.modules, "mempalace.mcp_server", fake_mcp)
        monkeypatch.setattr(mempalace, "mcp_server", fake_mcp)
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        violations = adapter.verify_behavioral_contract()
        missing = [v for v in violations if v.field.startswith("mcp_tool:")]
        assert len(missing) >= 2
        assert all(v.severity == "error" for v in missing)


class TestVersionComparison:
    """Critical: never compare semver as Python strings.
    '3.10.0' < '3.3.0' returns True lexically — wrong."""

    def test_parse_version_returns_tuple(self):
        assert MempalaceAdapter._parse_version("3.3.0") == (3, 3, 0)
        assert MempalaceAdapter._parse_version("3.10.0") == (3, 10, 0)

    def test_tuple_comparison_correct_for_double_digit_minor(self):
        assert MempalaceAdapter._parse_version("3.10.0") > MempalaceAdapter._parse_version("3.3.0")
        assert MempalaceAdapter._parse_version("3.3.10") > MempalaceAdapter._parse_version("3.3.2")


class TestTunnelContext:
    def test_tunnel_link_dataclass(self):
        link = TunnelLink(
            shared_topic="documentation",
            connected_wings=["chorestory", "grocusave"],
            drawer_count=150,
        )
        assert link.shared_topic == "documentation"
        assert len(link.connected_wings) == 2
        assert link.drawer_count == 150

    def test_render_tunnel_context_with_tunnels(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        fake_tunnels = [
            {"room": "documentation", "wings": ["proj_a", "proj_b", "proj_c"], "count": 500},
            {"room": "testing", "wings": ["proj_a", "proj_d"], "count": 100},
        ]
        with patch("mempalace.palace_graph.find_tunnels", return_value=fake_tunnels):
            text = adapter._render_tunnel_context("proj_a")
        assert "Cross-project links" in text
        assert "documentation" in text
        assert "proj_b" in text
        assert "proj_a" not in text  # current wing excluded from list

    def test_render_tunnel_context_empty_when_no_tunnels(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        with patch("mempalace.palace_graph.find_tunnels", return_value=[]):
            text = adapter._render_tunnel_context("proj_a")
        assert text == ""

    def test_wakeup_includes_tunnels_layer_when_tunnels_exist(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        fake_tunnels = [
            {"room": "documentation", "wings": ["proj_a", "proj_b"], "count": 500},
        ]
        with patch("mempalace.palace_graph.find_tunnels", return_value=fake_tunnels):
            ctx = adapter.wakeup(project="proj_a")
        assert "tunnels" in ctx.layers
        assert "Cross-project links" in ctx.text
        assert ctx.tokens > 0


class TestFindTunnels:
    def test_find_tunnels_returns_list(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        tunnels = adapter.find_tunnels_for_wing("test_wing")
        assert isinstance(tunnels, list)

    def test_find_tunnels_graceful_on_error(self, tmp_path, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules, "mempalace.palace_graph", None)
        monkeypatch.setitem(__import__("sys").modules, "mempalace", None)
        adapter = MempalaceAdapter(palace_path=str(tmp_path))
        tunnels = adapter.find_tunnels_for_wing("test_wing")
        assert tunnels == []

    def test_find_tunnels_excludes_own_wing(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        fake_tunnels = [
            {"room": "docs", "wings": ["proj_a", "proj_b", "proj_c"], "count": 100},
        ]
        with patch("mempalace.palace_graph.find_tunnels", return_value=fake_tunnels):
            tunnels = adapter.find_tunnels_for_wing("proj_a")
        assert len(tunnels) == 1
        assert "proj_a" not in tunnels[0].connected_wings
        assert "proj_b" in tunnels[0].connected_wings
