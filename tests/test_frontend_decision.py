"""Tests for the web frontend analysis spike decision document (Issue #12)."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DECISION_DOC = PROJECT_ROOT / "docs" / "frontend-decision.md"


class TestDecisionDocStructure:
    """Validate docs/frontend-decision.md exists and has required structure."""

    def test_docs_directory_exists(self):
        assert DECISION_DOC.parent.exists(), "Missing docs/ directory"

    def test_decision_doc_exists(self):
        assert DECISION_DOC.exists(), "Missing docs/frontend-decision.md"

    def test_has_executive_summary(self):
        content = DECISION_DOC.read_text()
        assert "# " in content, "Document must have a title heading"

    def test_has_decision_statement(self):
        """AC3: Decision must be one of the three options."""
        content = DECISION_DOC.read_text().lower()
        options = ["use as-is", "fork", "build custom"]
        assert any(opt in content for opt in options), (
            "Decision must state one of: use as-is, fork, or build custom"
        )


class TestEvaluationCriteria:
    """AC1: All five evaluation criteria must be addressed."""

    def _read(self):
        return DECISION_DOC.read_text().lower()

    def test_evaluates_code_quality(self):
        assert "code quality" in self._read(), (
            "Must evaluate code quality"
        )

    def test_evaluates_feature_completeness(self):
        assert "feature" in self._read() and "complete" in self._read(), (
            "Must evaluate feature completeness"
        )

    def test_evaluates_maintainability(self):
        assert "maintainab" in self._read(), (
            "Must evaluate maintainability"
        )

    def test_evaluates_license_compatibility(self):
        assert "license" in self._read(), (
            "Must evaluate license compatibility"
        )

    def test_evaluates_chromadb_compatibility(self):
        content = self._read()
        assert "chromadb" in content or "chroma" in content, (
            "Must evaluate ChromaDB data compatibility"
        )


class TestDecisionRationale:
    """AC2: Decision must include rationale."""

    def _read(self):
        return DECISION_DOC.read_text()

    def test_has_rationale_section(self):
        content = self._read().lower()
        assert "rationale" in content or "reason" in content or "why" in content, (
            "Decision must include rationale"
        )

    def test_references_frontend_repo(self):
        content = self._read()
        assert "memory-palace-web-frontend" in content, (
            "Must reference the evaluated repository"
        )

    def test_considers_all_three_options(self):
        """All three options must be discussed, even if not chosen."""
        content = self._read().lower()
        assert "use as-is" in content or "as-is" in content or "docker dependency" in content, (
            "Must discuss 'use as-is' option"
        )
        assert "fork" in content, "Must discuss 'fork' option"
        assert "build custom" in content or "custom" in content, (
            "Must discuss 'build custom' option"
        )
