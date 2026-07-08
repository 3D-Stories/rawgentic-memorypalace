"""Tests for the slim HTTP server routing through MempalaceAdapter."""
import pytest
from starlette.testclient import TestClient


@pytest.fixture
def slim_app(isolated_palace):
    """Build the slim server app pointing at the isolated palace."""
    from rawgentic_memory.server import build_app

    return build_app(palace_path=str(isolated_palace))


@pytest.fixture
def client(slim_app):
    """Synchronous test client for the slim server."""
    with TestClient(slim_app) as c:
        yield c


class TestHealthz:
    def test_healthz_returns_200(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert data["backend"] == "mempalace"
        assert "doc_count" in data

    def test_healthz_reports_version(self, client):
        resp = client.get("/healthz")
        data = resp.json()
        assert "version" in data
        assert data["version"] != ""


class TestSearch:
    def test_search_returns_additional_context(self, client):
        """POST /search with a prompt returns additionalContext string."""
        resp = client.post("/search", json={"prompt": "test query"})
        assert resp.status_code == 200
        data = resp.json()
        assert "additionalContext" in data

    def test_search_filters_by_similarity(self, client):
        """Results below min_similarity are excluded."""
        from unittest.mock import patch
        from rawgentic_memory.adapter import SearchResult

        fake = [
            SearchResult(content="high", similarity=0.9),
            SearchResult(content="low", similarity=0.1),
        ]
        with patch.object(
            client.app.state.adapter, "search", return_value=fake
        ):
            resp = client.post(
                "/search",
                json={"prompt": "q", "min_similarity": 0.5},
            )
        data = resp.json()
        # Only the high-similarity result should appear in the context
        assert "high" in data["additionalContext"]
        assert "low" not in data["additionalContext"]


class TestSearchHeaders:
    """rawgentic#305 — /search honors hook headers; body/defaults preserved."""

    def _fake(self):
        from rawgentic_memory.adapter import SearchResult
        return [
            SearchResult(content="own-high", similarity=0.9, project="my_proj"),
            SearchResult(content="own-mid", similarity=0.5, project="my_proj"),
            SearchResult(content="foreign", similarity=0.9, project="other_proj"),
            SearchResult(content="global", similarity=0.9, project=""),
        ]

    def _post(self, client, headers=None, body=None):
        from unittest.mock import patch
        with patch.object(client.app.state.adapter, "search",
                          return_value=self._fake()):
            return client.post("/search",
                               json=body or {"prompt": "q"},
                               headers=headers or {})

    def test_header_threshold_overrides_default(self, client):
        """X-Similarity-Threshold header raises the filter above 0.3."""
        data = self._post(client, headers={"X-Similarity-Threshold": "0.7"}).json()
        assert "own-high" in data["additionalContext"]
        assert "own-mid" not in data["additionalContext"]

    def test_malformed_threshold_header_falls_back(self, client):
        """Unparseable header never 500s — falls back to body/default."""
        resp = self._post(client, headers={"X-Similarity-Threshold": "banana"})
        assert resp.status_code == 200
        assert "own-mid" in resp.json()["additionalContext"]  # default 0.3 applies

    def test_project_header_scopes_results(self, client):
        """X-Project keeps own-project (normalized -/_) and project-less hits only."""
        data = self._post(client, headers={"X-Project": "my-proj"}).json()
        assert "own-high" in data["additionalContext"]
        assert "global" in data["additionalContext"]
        assert "foreign" not in data["additionalContext"]

    def test_no_headers_body_semantics_unchanged(self, client):
        """Explicit callers without headers keep body min_similarity + no scoping."""
        data = self._post(client, body={"prompt": "q", "min_similarity": 0.5}).json()
        assert "foreign" in data["additionalContext"]  # unscoped
        assert "own-mid" in data["additionalContext"]  # 0.5 boundary inclusive

    def test_max_results_header_caps_results(self, client):
        """X-Max-Results header bounds injected results."""
        data = self._post(client, headers={"X-Max-Results": "1"}).json()
        ctx = data["additionalContext"]
        assert sum(s in ctx for s in ("own-high", "own-mid", "foreign", "global")) == 1


class TestWakeup:
    def test_wakeup_no_project_returns_empty(self, client):
        resp = client.get("/wakeup")
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == ""
        assert data["layers"] == []

    def test_wakeup_with_project_returns_json(self, client):
        resp = client.get("/wakeup?project=test_project")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "tokens" in data
        assert "layers" in data


class TestTunnelsEndpoint:
    def test_tunnels_returns_json(self, client):
        resp = client.get("/tunnels?wing=test_wing")
        assert resp.status_code == 200
        data = resp.json()
        assert "tunnels" in data
        assert isinstance(data["tunnels"], list)

    def test_tunnels_without_wing_returns_422(self, client):
        resp = client.get("/tunnels")
        assert resp.status_code == 422


class TestFactCheck:
    def test_fact_check_returns_additional_context(self, client):
        """POST /fact_check with text returns additionalContext."""
        resp = client.post("/fact_check", json={"text": "some text to check"})
        assert resp.status_code == 200
        data = resp.json()
        assert "additionalContext" in data

    def test_fact_check_extracts_text_from_tool_input(self, client):
        """POST /fact_check supports tool_input.content and tool_input.new_string."""
        from unittest.mock import patch
        from rawgentic_memory.adapter import FactIssue

        fake = [FactIssue(type="similar_name", detail="did you mean X?", entity="X")]
        with patch.object(
            client.app.state.adapter, "fact_check", return_value=fake
        ) as mock_fc:
            resp = client.post(
                "/fact_check",
                json={"tool_input": {"content": "check this"}},
            )
        mock_fc.assert_called_once_with("check this")
        data = resp.json()
        assert "did you mean X?" in data["additionalContext"]


class TestDiagnostic:
    def test_diagnostic_returns_health_and_uptime(self, client):
        """GET /diagnostic returns health, contract violations, and uptime."""
        resp = client.get("/diagnostic")
        assert resp.status_code == 200
        data = resp.json()
        assert "health" in data
        assert "contract_violations" in data
        assert "uptime_seconds" in data
        assert isinstance(data["contract_violations"], list)
        assert data["uptime_seconds"] >= 0


class TestCanaryWrite:
    def test_canary_write_succeeds_for_canary_wing(self, client):
        """POST /canary_write with wing=canary calls adapter.canary_write."""
        from unittest.mock import patch

        with patch.object(
            client.app.state.adapter, "canary_write", return_value=True
        ) as mock_cw:
            resp = client.post(
                "/canary_write",
                json={"wing": "canary", "fact": "test canary fact"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        mock_cw.assert_called_once_with("test canary fact")

    def test_canary_write_rejects_non_canary_wing(self, client):
        """POST /canary_write with wing != canary returns 403."""
        resp = client.post(
            "/canary_write",
            json={"wing": "production", "fact": "should not write"},
        )
        assert resp.status_code == 403
        data = resp.json()
        assert "canary" in data["detail"].lower()


class TestRemovedEndpoints:
    def test_ingest_returns_410(self, client):
        """POST /ingest returns 410 Gone with migration hint."""
        resp = client.post("/ingest", json={"session_id": "s", "notes": "n"})
        assert resp.status_code == 410
        data = resp.json()
        assert "Save Hook" in data["detail"]

    def test_reindex_returns_410(self, client):
        """POST /reindex returns 410 Gone with migration hint."""
        resp = client.post("/reindex", json={"source_dirs": ["/tmp"]})
        assert resp.status_code == 410
        data = resp.json()
        assert "mine CLI" in data["detail"]

    def test_kg_invalidate_returns_410(self, client):
        """POST /kg/invalidate returns 410 Gone with migration hint."""
        resp = client.post(
            "/kg/invalidate",
            json={"subject": "s", "predicate": "p", "object": "o"},
        )
        assert resp.status_code == 410
        data = resp.json()
        assert "MCP tools" in data["detail"]
