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


class TestSaveSkillKgWriteRule:
    """mempalace-save documents the three-way KG write rule + a KG-write step (#64 AC2)."""

    def _read_body(self):
        return SKILL_FILE.read_text().split("---", 2)[2]

    def test_documents_all_three_kg_writes(self):
        body = self._read_body()
        assert "mempalace_kg_supersede" in body, "must name mempalace_kg_supersede (value changed)"
        assert "mempalace_kg_invalidate" in body, "must name mempalace_kg_invalidate (fact ended)"
        assert "mempalace_kg_add" in body, "must name mempalace_kg_add (new independent fact)"

    def test_three_way_rule_distinguishes_cases(self):
        body = self._read_body().lower()
        # the rule must distinguish a CHANGED value from an ENDED fact from a NEW fact
        assert "changes" in body or "changed" in body, "must cover a CHANGED single-valued fact"
        assert "ended" in body or "no longer" in body, "must cover an ENDED fact"

    def test_has_kg_write_step_for_new_and_changed_facts(self):
        body = self._read_body().lower()
        assert "kg" in body and "single-valued" in body, (
            "must add a KG-write step for new + changed single-valued facts (#64 AC2)"
        )


class TestMemoryAuthorityGuidance:
    """The three-way KG rule is stated in the project memory-authority guidance (#64 AC3)."""

    CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"

    def test_claude_md_exists(self):
        assert self.CLAUDE_MD.exists(), "project CLAUDE.md must exist"

    def test_claude_md_states_three_way_kg_rule(self):
        text = self.CLAUDE_MD.read_text()
        low = text.lower()
        assert "kg_supersede" in text, (
            "CLAUDE.md memory guidance must name kg_supersede for a changed decision (#64 AC3)"
        )
        assert "invalidate" in low, "CLAUDE.md must mention invalidate (fact ended) (#64 AC3)"
        assert "kg_add" in text or "add" in low, "CLAUDE.md must mention add (new fact) (#64 AC3)"
