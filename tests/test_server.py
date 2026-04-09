"""Tests for the FastAPI memory server endpoints and idle timeout."""

import asyncio
import time
from unittest.mock import MagicMock


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


class TestIdleTimeout:
    """Validate idle timeout shuts down the server after inactivity."""

    def test_idle_watcher_sets_should_exit_after_timeout(self):
        """Idle watcher should set server.should_exit when timeout expires."""
        from rawgentic_memory.server import _idle_watcher, create_app

        app = create_app(idle_timeout=1)
        mock_server = MagicMock()
        mock_server.should_exit = False
        app.state.server = mock_server
        # Push last_activity into the past so timeout is already expired
        app.state.last_activity = time.monotonic() - 2

        asyncio.run(_idle_watcher(app, check_interval=0.1))

        assert mock_server.should_exit is True

    def test_idle_watcher_does_not_exit_while_active(self):
        """Idle watcher should NOT shut down if activity is recent."""
        from rawgentic_memory.server import _idle_watcher, create_app

        app = create_app(idle_timeout=10)
        mock_server = MagicMock()
        mock_server.should_exit = False
        app.state.server = mock_server
        # Activity is fresh — timeout should not trigger
        app.state.last_activity = time.monotonic()

        async def run_watcher_briefly():
            task = asyncio.create_task(_idle_watcher(app, check_interval=0.1))
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_watcher_briefly())

        assert mock_server.should_exit is False

    def test_idle_timeout_zero_disables_shutdown(self):
        """Setting idle_timeout=0 should disable the auto-shutdown."""
        from rawgentic_memory.server import _idle_watcher, create_app

        app = create_app(idle_timeout=0)
        mock_server = MagicMock()
        mock_server.should_exit = False
        app.state.server = mock_server
        # Even with old activity, timeout=0 should never trigger
        app.state.last_activity = time.monotonic() - 100000

        async def run_watcher_briefly():
            task = asyncio.create_task(_idle_watcher(app, check_interval=0.1))
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_watcher_briefly())

        assert mock_server.should_exit is False

    def test_healthz_does_not_reset_idle_timer(self, app, client):
        """Monitoring endpoints must NOT prevent idle timeout."""
        initial_activity = app.state.last_activity
        time.sleep(0.05)
        client.get("/healthz")
        assert app.state.last_activity == initial_activity

    def test_stats_does_not_reset_idle_timer(self, app, client):
        """Monitoring endpoints must NOT prevent idle timeout."""
        initial_activity = app.state.last_activity
        time.sleep(0.05)
        client.get("/stats")
        assert app.state.last_activity == initial_activity
