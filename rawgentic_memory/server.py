"""FastAPI memory server with lazy-start support and idle timeout.

Run via: python3 -m rawgentic_memory.server --port 8420 --timeout 14400
"""

import argparse
import asyncio
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Endpoints excluded from idle timeout tracking — monitoring calls
# should not keep the server alive.
_MONITORING_PATHS = frozenset({"/healthz", "/stats"})


def create_app(idle_timeout: int = 14400) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        idle_timeout: Seconds of inactivity before the server shuts down.
                      Default 14400 (4 hours). Set to 0 to disable.
    """
    app = FastAPI(title="rawgentic-memorypalace", docs_url=None, redoc_url=None)
    app.state.start_time = time.monotonic()
    app.state.last_activity = time.monotonic()
    app.state.idle_timeout = idle_timeout
    app.state.server = None  # Set by run_server() for programmatic shutdown

    @app.middleware("http")
    async def track_activity(request: Request, call_next):
        response = await call_next(request)
        if request.url.path not in _MONITORING_PATHS:
            request.app.state.last_activity = time.monotonic()
        return response

    @app.get("/healthz")
    async def healthz():
        uptime = time.monotonic() - app.state.start_time
        return JSONResponse({
            "status": "ok",
            "uptime": round(uptime, 2),
            "backends": {
                "native": False,
                "mempalace": False,
            },
        })

    @app.get("/stats")
    async def stats():
        return JSONResponse({
            "backends": {
                "native": {"doc_count": 0, "available": False},
                "mempalace": {"doc_count": 0, "available": False},
            },
            "last_ingest": None,
            "index_size_bytes": 0,
        })

    return app


async def _idle_watcher(app: FastAPI, check_interval: int = 60) -> None:
    """Background task that shuts down the server after idle timeout."""
    while True:
        await asyncio.sleep(check_interval)
        elapsed = time.monotonic() - app.state.last_activity
        if app.state.idle_timeout > 0 and elapsed >= app.state.idle_timeout:
            if app.state.server is not None:
                app.state.server.should_exit = True
            return


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rawgentic_memory.server",
        description="Memory server for rawgentic-memorypalace plugin",
    )
    parser.add_argument(
        "--port", type=int, default=8420,
        help="Port to bind to (default: 8420)",
    )
    parser.add_argument(
        "--timeout", type=int, default=14400,
        help="Idle timeout in seconds before auto-shutdown (default: 14400 = 4h, 0 to disable)",
    )
    return parser.parse_args(argv)


def run_server(port: int = 8420, idle_timeout: int = 14400) -> None:
    """Start the server with idle timeout watcher."""
    import uvicorn

    app = create_app(idle_timeout=idle_timeout)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    app.state.server = server

    async def serve_with_watcher():
        watcher = asyncio.create_task(_idle_watcher(app))
        await server.serve()
        watcher.cancel()

    asyncio.run(serve_with_watcher())


if __name__ == "__main__":
    args = _parse_args()
    run_server(port=args.port, idle_timeout=args.timeout)
