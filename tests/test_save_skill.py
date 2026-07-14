"""Tests for the /mempalace-save skill — file structure, frontmatter, and content requirements."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SKILL_DIR = PROJECT_ROOT / "skills" / "mempalace-save"
SKILL_FILE = SKILL_DIR / "SKILL.md"


class TestSaveSkillStructure:
    """Validate skills/mempalace-save/SKILL.md exists and has correct structure."""

    def test_skill_directory_exists(self):
        assert SKILL_DIR.exists(), "Missing skills/mempalace-save/ directory"

    def test_skill_file_exists(self):
        assert SKILL_FILE.exists(), "Missing skills/mempalace-save/SKILL.md"

    def test_skill_has_frontmatter(self):
        content = SKILL_FILE.read_text()
        assert content.startswith("---"), "SKILL.md must start with YAML frontmatter"
        parts = content.split("---", 2)
        assert len(parts) >= 3, "SKILL.md must have opening and closing --- delimiters"

    def test_skill_frontmatter_has_name(self):
        content = SKILL_FILE.read_text()
        frontmatter = content.split("---", 2)[1]
        assert "name:" in frontmatter, "Frontmatter must include 'name' field"
        assert "mempalace-save" in frontmatter, "Skill name must include 'mempalace-save'"

    def test_skill_references_save_mcp_tools(self):
        body = SKILL_FILE.read_text().split("---", 2)[2]
        assert "mempalace_diary_write" in body, "Skill must call mempalace_diary_write"
        assert "mempalace_add_drawer" in body, "Skill must call mempalace_add_drawer"

    def test_skill_does_not_hardcode_a_server_ip(self):
        """The skill must use the user-configured MCP server, never a bundled IP
        (the workspace source hardcoded a private VM address — regression guard)."""
        import re
        content = SKILL_FILE.read_text()
        assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", content), (
            "SKILL.md must not hardcode a server IP; MCP connection is user-configured"
        )
