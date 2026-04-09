"""Tests for the /recall skill — file structure, frontmatter, and content requirements."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SKILL_DIR = PROJECT_ROOT / "skills" / "recall"
SKILL_FILE = SKILL_DIR / "SKILL.md"


class TestRecallSkillStructure:
    """Validate skills/recall/SKILL.md exists and has correct structure."""

    def test_skill_directory_exists(self):
        assert SKILL_DIR.exists(), "Missing skills/recall/ directory"

    def test_skill_file_exists(self):
        assert SKILL_FILE.exists(), "Missing skills/recall/SKILL.md"

    def test_skill_has_frontmatter(self):
        content = SKILL_FILE.read_text()
        assert content.startswith("---"), "SKILL.md must start with YAML frontmatter"
        # Must have closing frontmatter delimiter
        parts = content.split("---", 2)
        assert len(parts) >= 3, "SKILL.md must have opening and closing --- delimiters"

    def test_skill_frontmatter_has_name(self):
        content = SKILL_FILE.read_text()
        frontmatter = content.split("---", 2)[1]
        assert "name:" in frontmatter, "Frontmatter must include 'name' field"
        assert "recall" in frontmatter, "Skill name must include 'recall'"

    def test_skill_frontmatter_has_description(self):
        content = SKILL_FILE.read_text()
        frontmatter = content.split("---", 2)[1]
        assert "description:" in frontmatter, "Frontmatter must include 'description' field"

    def test_skill_frontmatter_has_argument_hint(self):
        content = SKILL_FILE.read_text()
        frontmatter = content.split("---", 2)[1]
        assert "argument-hint:" in frontmatter, (
            "Frontmatter must include 'argument-hint' for user guidance"
        )


class TestRecallSkillContent:
    """Validate SKILL.md contains required instructions for all ACs."""

    def _read_body(self):
        content = SKILL_FILE.read_text()
        return content.split("---", 2)[2]

    def test_references_search_endpoint(self):
        body = self._read_body()
        assert "/search" in body, "Skill must reference /search endpoint"

    def test_references_server_url(self):
        body = self._read_body()
        assert "MEMORY_SERVER_URL" in body or "8420" in body, (
            "Skill must reference the memory server URL or default port"
        )

    def test_references_project_filter(self):
        body = self._read_body()
        assert "--project" in body, (
            "Skill must document --project flag for filtering (AC2)"
        )

    def test_handles_unreachable_server(self):
        body = self._read_body()
        assert "not running" in body.lower() or "unreachable" in body.lower() or "not reachable" in body.lower(), (
            "Skill must handle server unreachable case (AC3)"
        )

    def test_shows_project_in_results(self):
        body = self._read_body()
        assert "project" in body.lower(), (
            "Skill must instruct showing project per result (AC4)"
        )

    def test_shows_similarity_in_results(self):
        body = self._read_body()
        assert "similarity" in body.lower(), (
            "Skill must instruct showing similarity score (AC1)"
        )

    def test_shows_memory_type_in_results(self):
        body = self._read_body()
        assert "memory_type" in body.lower(), (
            "Skill must instruct showing memory_type (AC1)"
        )

    def test_uses_curl_for_http_calls(self):
        body = self._read_body()
        assert "curl" in body, (
            "Skill must use curl for HTTP calls (consistent with hooks pattern)"
        )

    def test_distinguishes_connection_refused_from_http_error(self):
        body = self._read_body()
        assert "exit code 7" in body.lower() or "connection refused" in body.lower(), (
            "Skill must distinguish connection refused from HTTP errors"
        )
        assert "503" in body or "http error" in body.lower() or "unhealthy" in body.lower(), (
            "Skill must handle HTTP error case (e.g. 503 backend unavailable)"
        )
