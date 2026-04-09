"""Tests for the FastAPI memory server endpoints."""

import time


class TestHealthz:
    """Validate /healthz endpoint response shape and behavior."""

    def test_healthz_returns_200(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200

    def test_healthz_has_status_field(self, client):
        data = client.get("/healthz").json()
        assert data["status"] == "ok"

    def test_healthz_has_uptime_field(self, client):
        data = client.get("/healthz").json()
        assert "uptime" in data
        assert isinstance(data["uptime"], (int, float))
        assert data["uptime"] >= 0

    def test_healthz_has_backends_field(self, client):
        data = client.get("/healthz").json()
        assert "backends" in data
        assert "native" in data["backends"]
        assert "mempalace" in data["backends"]

    def test_healthz_backends_are_booleans(self, client):
        backends = client.get("/healthz").json()["backends"]
        assert isinstance(backends["native"], bool)
        assert isinstance(backends["mempalace"], bool)

    def test_healthz_backends_initially_false(self, client):
        """Backends are not implemented yet — both should report unavailable."""
        backends = client.get("/healthz").json()["backends"]
        assert backends["native"] is False
        assert backends["mempalace"] is False

    def test_healthz_responds_within_1_second(self, client):
        start = time.monotonic()
        resp = client.get("/healthz")
        elapsed = time.monotonic() - start
        assert resp.status_code == 200
        assert elapsed < 1.0, f"/healthz took {elapsed:.2f}s, must be <1s"

    def test_healthz_uptime_increases(self, client):
        data1 = client.get("/healthz").json()
        time.sleep(0.1)
        data2 = client.get("/healthz").json()
        assert data2["uptime"] >= data1["uptime"]


class TestStats:
    """Validate /stats endpoint response shape."""

    def test_stats_returns_200(self, client):
        resp = client.get("/stats")
        assert resp.status_code == 200

    def test_stats_has_backends_field(self, client):
        data = client.get("/stats").json()
        assert "backends" in data

    def test_stats_backends_have_required_fields(self, client):
        backends = client.get("/stats").json()["backends"]
        for name in ("native", "mempalace"):
            assert name in backends, f"Missing backend: {name}"
            assert "doc_count" in backends[name]
            assert "available" in backends[name]

    def test_stats_has_last_ingest_field(self, client):
        data = client.get("/stats").json()
        assert "last_ingest" in data

    def test_stats_has_index_size_bytes_field(self, client):
        data = client.get("/stats").json()
        assert "index_size_bytes" in data
        assert isinstance(data["index_size_bytes"], (int, float))

    def test_stats_initially_empty(self, client):
        """Before any backends are connected, stats should be zeroed out."""
        data = client.get("/stats").json()
        assert data["last_ingest"] is None
        assert data["index_size_bytes"] == 0
        for backend in data["backends"].values():
            assert backend["doc_count"] == 0
            assert backend["available"] is False
