"""Tests that validate the Claude Code plugin structure."""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


class TestPluginJson:
    """Validate .claude-plugin/plugin.json has required fields."""

    def test_plugin_json_exists(self):
        path = PROJECT_ROOT / ".claude-plugin" / "plugin.json"
        assert path.exists(), "Missing .claude-plugin/plugin.json"

    def test_plugin_json_is_valid_json(self):
        path = PROJECT_ROOT / ".claude-plugin" / "plugin.json"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_plugin_json_has_required_fields(self):
        path = PROJECT_ROOT / ".claude-plugin" / "plugin.json"
        with open(path) as f:
            data = json.load(f)
        for field in ("name", "version", "description"):
            assert field in data, f"plugin.json missing required field: {field}"
            assert data[field], f"plugin.json field '{field}' is empty"

    def test_plugin_json_name_matches_project(self):
        path = PROJECT_ROOT / ".claude-plugin" / "plugin.json"
        with open(path) as f:
            data = json.load(f)
        assert data["name"] == "rawgentic-memorypalace"


class TestHooksJson:
    """Validate hooks/hooks.json defines required hook events."""

    def test_hooks_json_exists(self):
        path = PROJECT_ROOT / "hooks" / "hooks.json"
        assert path.exists(), "Missing hooks/hooks.json"

    def test_hooks_json_is_valid_json(self):
        path = PROJECT_ROOT / "hooks" / "hooks.json"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_hooks_json_has_hooks_key(self):
        path = PROJECT_ROOT / "hooks" / "hooks.json"
        with open(path) as f:
            data = json.load(f)
        assert "hooks" in data, "hooks.json missing 'hooks' key"

    def test_hooks_json_defines_required_events(self):
        path = PROJECT_ROOT / "hooks" / "hooks.json"
        with open(path) as f:
            data = json.load(f)
        hooks = data["hooks"]
        for event in ("SessionStart", "UserPromptSubmit", "Stop"):
            assert event in hooks, f"hooks.json missing event: {event}"

    def test_session_start_covers_compact(self):
        """SessionStart matcher must include 'compact' for PreCompact behavior."""
        path = PROJECT_ROOT / "hooks" / "hooks.json"
        with open(path) as f:
            data = json.load(f)
        session_start = data["hooks"]["SessionStart"]
        matchers = " ".join(
            entry.get("matcher", "") for entry in session_start
        )
        assert "compact" in matchers, (
            "SessionStart must have a matcher that includes 'compact' for PreCompact"
        )
