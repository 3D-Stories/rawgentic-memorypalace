"""Tests for the memory-ui skill definition (Issue #14)."""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SKILL_FILE = PROJECT_ROOT / "skills" / "memory-ui" / "SKILL.md"
COMPOSE_FILE = PROJECT_ROOT / "frontend" / "docker-compose.yml"


class TestSkillFileExists:
    """Skill file must exist at the expected path."""

    def test_skill_directory_exists(self):
        assert SKILL_FILE.parent.exists(), "Missing skills/memory-ui/ directory"

    def test_skill_file_exists(self):
        assert SKILL_FILE.exists(), "Missing skills/memory-ui/SKILL.md"


class TestSkillFrontmatter:
    """Skill must have valid YAML frontmatter with required fields."""

    def _parse_frontmatter(self):
        text = SKILL_FILE.read_text()
        match = re.search(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match, "SKILL.md must have YAML frontmatter"
        return match.group(1)

    def test_has_name_field(self):
        fm = self._parse_frontmatter()
        assert re.search(r"^name:\s*\S", fm, re.MULTILINE), (
            "Frontmatter must include 'name' field"
        )

    def test_name_is_memory_ui(self):
        fm = self._parse_frontmatter()
        match = re.search(r"^name:\s*(.+)$", fm, re.MULTILINE)
        assert match and "memory-ui" in match.group(1), (
            "Skill name must contain 'memory-ui'"
        )

    def test_has_description_field(self):
        fm = self._parse_frontmatter()
        assert re.search(r"^description:\s*\S", fm, re.MULTILINE), (
            "Frontmatter must include 'description' field"
        )

    def test_has_argument_hint(self):
        fm = self._parse_frontmatter()
        assert re.search(r"^argument-hint:\s*\S", fm, re.MULTILINE), (
            "Frontmatter must include 'argument-hint' field"
        )


class TestSubcommandCoverage:
    """Skill must document all three subcommands: up, down, status."""

    def _read_skill(self):
        return SKILL_FILE.read_text()

    def test_documents_up_subcommand(self):
        content = self._read_skill()
        assert re.search(r"(?i)\bup\b", content), (
            "Skill must document the 'up' subcommand"
        )

    def test_documents_down_subcommand(self):
        content = self._read_skill()
        assert re.search(r"(?i)\bdown\b", content), (
            "Skill must document the 'down' subcommand"
        )

    def test_documents_status_subcommand(self):
        content = self._read_skill()
        assert re.search(r"(?i)\bstatus\b", content), (
            "Skill must document the 'status' subcommand"
        )


class TestComposeReference:
    """Skill must reference the correct docker-compose file path."""

    def _read_skill(self):
        return SKILL_FILE.read_text()

    def test_references_compose_file(self):
        content = self._read_skill()
        assert "frontend/docker-compose.yml" in content, (
            "Skill must reference frontend/docker-compose.yml"
        )

    def test_compose_file_actually_exists(self):
        assert COMPOSE_FILE.exists(), (
            "frontend/docker-compose.yml must exist (created by Issue #13)"
        )


class TestURLReporting:
    """AC1: Skill must report both frontend URLs."""

    def _read_skill(self):
        return SKILL_FILE.read_text()

    def test_mentions_native_port_8098(self):
        content = self._read_skill()
        assert "8098" in content, (
            "Skill must mention port 8098 for native frontend"
        )

    def test_mentions_mempalace_port_8099(self):
        content = self._read_skill()
        assert "8099" in content, (
            "Skill must mention port 8099 for mempalace frontend"
        )


class TestDockerErrorHandling:
    """AC5: Skill must handle Docker not installed/running."""

    def _read_skill(self):
        return SKILL_FILE.read_text()

    def test_checks_docker_availability(self):
        content = self._read_skill()
        assert re.search(r"docker\s+(info|compose\s+version|--version)", content), (
            "Skill must check Docker availability before running commands"
        )

    def test_has_docker_not_found_error_message(self):
        content = self._read_skill()
        lower = content.lower()
        assert "not installed" in lower or "not found" in lower or "not available" in lower, (
            "Skill must include error message for Docker not available"
        )


class TestStatusNotRunning:
    """AC4: Status must suggest /rawgentic-memorypalace:memory-ui up when containers are not running."""

    def _read_skill(self):
        return SKILL_FILE.read_text()

    def test_suggests_up_when_not_running(self):
        content = self._read_skill()
        assert "/rawgentic-memorypalace:memory-ui up" in content, (
            "Skill must suggest '/rawgentic-memorypalace:memory-ui up' when containers are not running"
        )
