"""Tests that validate the Claude Code plugin structure."""

import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # Python <3.11 fallback

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


class TestPyprojectDependencies:
    """Validate pyproject.toml declares mempalace dependency."""

    def _load_pyproject(self):
        path = PROJECT_ROOT / "pyproject.toml"
        with open(path, "rb") as f:
            return tomllib.load(f)

    def test_mempalace_in_dependencies(self):
        data = self._load_pyproject()
        deps = data["project"]["dependencies"]
        mempalace_deps = [d for d in deps if d.startswith("mempalace")]
        assert len(mempalace_deps) == 1, "pyproject.toml must declare mempalace dependency"

    def test_mempalace_version_pinned(self):
        data = self._load_pyproject()
        deps = data["project"]["dependencies"]
        mempalace_dep = [d for d in deps if d.startswith("mempalace")][0]
        assert ">=3.0.0" in mempalace_dep, "mempalace must be pinned to >=3.0.0"
        assert "<4.0" in mempalace_dep or "<4" in mempalace_dep, (
            "mempalace must have upper bound <4.0"
        )
