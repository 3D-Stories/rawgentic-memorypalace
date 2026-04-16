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


class TestWakeup:
    def test_wakeup_returns_context(self, client):
        """GET /wakeup returns wakeup context from adapter."""
        resp = client.get("/wakeup")
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "tokens" in data
        assert "layers" in data

    def test_wakeup_with_project_param(self, client):
        """GET /wakeup?project=foo passes project to adapter."""
        from unittest.mock import patch
        from rawgentic_memory.adapter import WakeupContext

        fake = WakeupContext(text="project context", tokens=10, layers=["L0", "L1"])
        with patch.object(
            client.app.state.adapter, "wakeup", return_value=fake
        ) as mock_wakeup:
            resp = client.get("/wakeup?project=myproj")
        mock_wakeup.assert_called_once_with(project="myproj")
        data = resp.json()
        assert data["text"] == "project context"


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
