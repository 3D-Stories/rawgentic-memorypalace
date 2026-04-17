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
        # Bridge hooks (read-only HTTP calls). Stop + PreCompact are handled
        # by mempalace's native hooks installed in ~/.claude/settings.json,
        # not by this plugin — hence absent here by design.
        for event in ("SessionStart", "UserPromptSubmit", "PostToolUse"):
            assert event in hooks, f"hooks.json missing event: {event}"

    def test_post_tool_use_matches_edit_write(self):
        """PostToolUse (Layer 4 fact-check) only fires on Edit/Write/MultiEdit."""
        path = PROJECT_ROOT / "hooks" / "hooks.json"
        with open(path) as f:
            data = json.load(f)
        post_tool_use = data["hooks"]["PostToolUse"]
        matchers = " ".join(
            entry.get("matcher", "") for entry in post_tool_use
        )
        for tool in ("Edit", "Write", "MultiEdit"):
            assert tool in matchers, (
                f"PostToolUse matcher missing '{tool}'"
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
        assert ">=3.3.0" in mempalace_dep, "mempalace must be pinned to >=3.3.0"
        assert "<4.0" in mempalace_dep or "<4" in mempalace_dep, (
            "mempalace must have upper bound <4.0"
        )


class TestMcpServerRegistration:
    """Validate MCP setup — plugin.json does NOT declare a plugin-level MCP default.

    MCP setup is environment-specific (pip install / pipx / SSH to central server),
    so a single plugin-level default would fail in most environments. Users configure
    MCP via `claude mcp add` after install — see README "MCP Setup" section.
    """

    def _load_plugin(self):
        path = PROJECT_ROOT / ".claude-plugin" / "plugin.json"
        with open(path) as f:
            return json.load(f)

    def test_plugin_does_not_declare_mcp_default(self):
        data = self._load_plugin()
        assert "mcpServers" not in data, (
            "plugin.json must NOT declare mcpServers — setup is user-configured "
            "per environment. See README 'MCP Setup' section."
        )

    def test_description_no_dual_backends(self):
        data = self._load_plugin()
        assert "dual" not in data["description"].lower(), (
            "Description must not reference dual backends (AC9)"
        )


class TestVersionConsistency:
    """Plugin and marketplace version strings must always match."""

    def _load_json(self, relpath: str) -> dict:
        path = PROJECT_ROOT / relpath
        with open(path) as f:
            return json.load(f)

    def test_plugin_and_marketplace_versions_match(self):
        plugin = self._load_json(".claude-plugin/plugin.json")
        marketplace = self._load_json(".claude-plugin/marketplace.json")
        plugin_ver = plugin["version"]
        marketplace_ver = marketplace["plugins"][0]["version"]
        assert plugin_ver == marketplace_ver, (
            f"Version drift: plugin.json={plugin_ver}, "
            f"marketplace.json={marketplace_ver}"
        )


class TestUpgradeSkillStructure:
    """Validate skills/upgrade/SKILL.md exists and has correct structure."""

    SKILL_DIR = PROJECT_ROOT / "skills" / "upgrade"
    SKILL_FILE = SKILL_DIR / "SKILL.md"

    def test_skill_directory_exists(self):
        assert self.SKILL_DIR.exists(), "Missing skills/upgrade/ directory"

    def test_skill_file_exists(self):
        assert self.SKILL_FILE.exists(), "Missing skills/upgrade/SKILL.md"

    def test_skill_has_frontmatter(self):
        content = self.SKILL_FILE.read_text()
        assert content.startswith("---"), "SKILL.md must start with YAML frontmatter"
        parts = content.split("---", 2)
        assert len(parts) >= 3, "SKILL.md must have opening and closing --- delimiters"

    def test_skill_frontmatter_has_name(self):
        content = self.SKILL_FILE.read_text()
        frontmatter = content.split("---", 2)[1]
        assert "name:" in frontmatter
        assert "upgrade" in frontmatter

    def test_skill_references_pip_upgrade(self):
        content = self.SKILL_FILE.read_text()
        body = content.split("---", 2)[2]
        assert "pip install --upgrade mempalace" in body

    def test_skill_warns_on_major_version(self):
        content = self.SKILL_FILE.read_text()
        body = content.split("---", 2)[2]
        assert "major" in body.lower(), "Skill must warn about major version changes"
