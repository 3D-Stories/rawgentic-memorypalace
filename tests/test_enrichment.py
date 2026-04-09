"""Tests for the rule-based enrichment pipeline."""

import pytest

from rawgentic_memory.enrichment import enrich, extract_topic
from rawgentic_memory.models import EnrichedSegment


class TestDecisionExtractor:
    """Validate extraction of decision-type memories."""

    def test_extracts_decided_keyword(self):
        text = "We decided to use PostgreSQL instead of SQLite for production."
        results = enrich(text, "notes.md")
        decisions = [r for r in results if r.memory_type == "decision"]
        assert len(decisions) >= 1
        assert "PostgreSQL" in decisions[0].content

    def test_extracts_chose_keyword(self):
        text = "The team chose Valibot over Zod for schema validation."
        results = enrich(text, "notes.md")
        decisions = [r for r in results if r.memory_type == "decision"]
        assert len(decisions) >= 1

    def test_extracts_went_with_keyword(self):
        text = "We went with per-project collections for better isolation."
        results = enrich(text, "notes.md")
        decisions = [r for r in results if r.memory_type == "decision"]
        assert len(decisions) >= 1

    def test_extracts_decision_heading(self):
        text = "### Decision\nUse FastAPI with uvicorn for the memory server."
        results = enrich(text, "notes.md")
        decisions = [r for r in results if r.memory_type == "decision"]
        assert len(decisions) >= 1

    def test_no_false_positive_on_unrelated_text(self):
        text = "The weather is nice today. Let's go for a walk."
        results = enrich(text, "notes.md")
        decisions = [r for r in results if r.memory_type == "decision"]
        assert len(decisions) == 0


class TestEventExtractor:
    """Validate extraction of event-type memories."""

    def test_extracts_deployed_event(self):
        text = "Deployed the new auth service to production at 3pm."
        results = enrich(text, "notes.md")
        events = [r for r in results if r.memory_type == "event"]
        assert len(events) >= 1

    def test_extracts_merged_event(self):
        text = "Merged PR #42 into main after code review."
        results = enrich(text, "notes.md")
        events = [r for r in results if r.memory_type == "event"]
        assert len(events) >= 1

    def test_extracts_error_event(self):
        text = "ERROR: Database connection failed during migration."
        results = enrich(text, "notes.md")
        events = [r for r in results if r.memory_type == "event"]
        assert len(events) >= 1

    def test_extracts_released_event(self):
        text = "Released version 2.1.0 with the new search feature."
        results = enrich(text, "notes.md")
        events = [r for r in results if r.memory_type == "event"]
        assert len(events) >= 1


class TestDiscoveryExtractor:
    """Validate extraction of discovery-type memories."""

    def test_extracts_found_that(self):
        text = "Found that ChromaDB uses SQLite under the hood for metadata."
        results = enrich(text, "notes.md")
        discoveries = [r for r in results if r.memory_type == "discovery"]
        assert len(discoveries) >= 1

    def test_extracts_learned(self):
        text = "Learned that uvicorn.Server.should_exit is the right way to stop."
        results = enrich(text, "notes.md")
        discoveries = [r for r in results if r.memory_type == "discovery"]
        assert len(discoveries) >= 1

    def test_extracts_turns_out(self):
        text = "Turns out the WAL bind guard blocks cross-project reads."
        results = enrich(text, "notes.md")
        discoveries = [r for r in results if r.memory_type == "discovery"]
        assert len(discoveries) >= 1

    def test_extracts_realized(self):
        text = "Realized that per-project collections give better isolation."
        results = enrich(text, "notes.md")
        discoveries = [r for r in results if r.memory_type == "discovery"]
        assert len(discoveries) >= 1


class TestPreferenceExtractor:
    """Validate extraction of preference-type memories."""

    def test_extracts_prefer(self):
        text = "I prefer using sync TestClient over async httpx for endpoint tests."
        results = enrich(text, "notes.md")
        prefs = [r for r in results if r.memory_type == "preference"]
        assert len(prefs) >= 1

    def test_extracts_always_use(self):
        text = "Always use server.should_exit for graceful shutdown."
        results = enrich(text, "notes.md")
        prefs = [r for r in results if r.memory_type == "preference"]
        assert len(prefs) >= 1

    def test_extracts_never(self):
        text = "Never push directly to main without a PR."
        results = enrich(text, "notes.md")
        prefs = [r for r in results if r.memory_type == "preference"]
        assert len(prefs) >= 1


class TestArtifactExtractor:
    """Validate extraction of artifact-type memories."""

    def test_extracts_file_path(self):
        text = "Created rawgentic_memory/server.py with FastAPI endpoints."
        results = enrich(text, "notes.md")
        artifacts = [r for r in results if r.memory_type == "artifact"]
        assert len(artifacts) >= 1

    def test_extracts_pr_reference(self):
        text = "Opened PR #16 for the lazy-start feature."
        results = enrich(text, "notes.md")
        artifacts = [r for r in results if r.memory_type == "artifact"]
        assert len(artifacts) >= 1

    def test_extracts_commit_sha(self):
        text = "See commit abc123def456 on the feature branch for details."
        results = enrich(text, "notes.md")
        artifacts = [r for r in results if r.memory_type == "artifact"]
        assert len(artifacts) >= 1


class TestTopicExtraction:
    """Validate topic extraction from enriched content."""

    def test_extracts_topic_from_content(self):
        topic = extract_topic("We decided to use PostgreSQL instead of SQLite.")
        assert topic  # non-empty
        assert isinstance(topic, str)

    def test_topic_is_concise(self):
        topic = extract_topic(
            "Deployed the new authentication service to production environment."
        )
        # Topic should be a short phrase, not the full sentence
        assert len(topic) <= 60

    def test_empty_input_returns_empty_topic(self):
        topic = extract_topic("")
        assert topic == ""


class TestEnrichIntegration:
    """Validate the full enrich() pipeline."""

    def test_returns_list_of_enriched_segments(self):
        text = "We decided to use ChromaDB. Deployed the server at noon."
        results = enrich(text, "session.md")
        assert isinstance(results, list)
        assert all(isinstance(r, EnrichedSegment) for r in results)

    def test_segments_have_source_file(self):
        text = "Found that regex extraction works well for session notes."
        results = enrich(text, "my_notes.md")
        for r in results:
            assert r.source_file == "my_notes.md"

    def test_segments_have_topic(self):
        text = "We decided to use per-project ChromaDB collections."
        results = enrich(text, "notes.md")
        for r in results:
            assert r.topic  # non-empty

    def test_empty_input_returns_empty_list(self):
        assert enrich("", "notes.md") == []

    def test_whitespace_only_returns_empty_list(self):
        assert enrich("   \n\n  ", "notes.md") == []

    def test_multiline_text_extracts_multiple_types(self):
        text = """We decided to use FastAPI for the server.
Found that ChromaDB 0.6.3 supports persistent storage.
Deployed the memory server to localhost:8420.
Always run tests before pushing."""
        results = enrich(text, "notes.md")
        types_found = {r.memory_type for r in results}
        assert len(types_found) >= 2, f"Expected multiple types, got {types_found}"
