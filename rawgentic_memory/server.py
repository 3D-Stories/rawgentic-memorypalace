"""FastAPI memory server with lazy-start support and idle timeout.

Run via: python3 -m rawgentic_memory.server --port 8420 --timeout 14400
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import asdict

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from rawgentic_memory.backend import MemoryBackend
from rawgentic_memory.models import SessionData
from rawgentic_memory.wakeup import generate_wakeup

# Endpoints excluded from idle timeout tracking — monitoring calls
# should not keep the server alive.
_MONITORING_PATHS = frozenset({"/healthz", "/stats"})


# --- Request/response models for FastAPI validation ---

class IngestRequest(BaseModel):
    session_id: str
    project: str
    notes: str
    source: str
    timestamp: str
    source_file: str = ""


class SearchRequest(BaseModel):
    query: str
    project: str | None = None
    memory_type: str | None = None
    limit: int = 10


class ReindexRequest(BaseModel):
    source_dirs: list[str]


def create_app(
    idle_timeout: int = 14400,
    backend: MemoryBackend | None = None,
    l0_path: str | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        idle_timeout: Seconds of inactivity before the server shuts down.
                      Default 14400 (4 hours). Set to 0 to disable.
        backend: Memory backend instance. If None, data endpoints return 503.
        l0_path: Path to the L0 identity file for /wakeup. If None, L0 is skipped.
    """
    app = FastAPI(title="rawgentic-memorypalace", docs_url=None, redoc_url=None)
    app.state.start_time = time.monotonic()
    app.state.last_activity = time.monotonic()
    app.state.idle_timeout = idle_timeout
    app.state.server = None  # Set by run_server() for programmatic shutdown
    app.state.backend = backend
    app.state.l0_path = l0_path

    @app.middleware("http")
    async def track_activity(request: Request, call_next):
        response = await call_next(request)
        if request.url.path not in _MONITORING_PATHS:
            request.app.state.last_activity = time.monotonic()
        return response

    @app.get("/healthz")
    async def healthz():
        uptime = time.monotonic() - app.state.start_time
        native_available = False
        if app.state.backend is not None:
            native_available = app.state.backend.stats().available
        return JSONResponse({
            "status": "ok",
            "uptime": round(uptime, 2),
            "backends": {
                "native": native_available,
                "mempalace": False,
            },
        })

    @app.get("/stats")
    async def stats():
        native_stats = {"doc_count": 0, "available": False}
        last_ingest = None
        index_size_bytes = 0
        if app.state.backend is not None:
            bs = app.state.backend.stats()
            native_stats = {"doc_count": bs.doc_count, "available": bs.available}
            last_ingest = bs.last_ingest
            index_size_bytes = bs.index_size_bytes
        return JSONResponse({
            "backends": {
                "native": native_stats,
                "mempalace": {"doc_count": 0, "available": False},
            },
            "last_ingest": last_ingest,
            "index_size_bytes": index_size_bytes,
        })

    @app.post("/ingest")
    async def ingest(req: IngestRequest):
        if app.state.backend is None:
            return JSONResponse(
                {"error": "No backend available"},
                status_code=503,
            )
        data = SessionData(
            session_id=req.session_id,
            project=req.project,
            notes=req.notes,
            source=req.source,
            timestamp=req.timestamp,
            source_file=req.source_file,
        )
        result = app.state.backend.ingest(data)
        return JSONResponse(asdict(result))

    @app.post("/search")
    async def search(req: SearchRequest):
        if app.state.backend is None:
            return JSONResponse(
                {"error": "No backend available"},
                status_code=503,
            )
        results = app.state.backend.search(
            query=req.query,
            project=req.project,
            memory_type=req.memory_type,
            limit=req.limit,
        )
        return JSONResponse({"results": [asdict(r) for r in results]})

    @app.post("/reindex")
    async def reindex(req: ReindexRequest):
        if app.state.backend is None:
            return JSONResponse(
                {"error": "No backend available"},
                status_code=503,
            )
        result = app.state.backend.reindex(req.source_dirs)
        return JSONResponse(asdict(result))

    @app.get("/wakeup")
    async def wakeup(project: str = Query(default="", max_length=128)):
        ctx = generate_wakeup(
            backend=app.state.backend,
            project=project or None,
            l0_path=app.state.l0_path,
        )
        return JSONResponse(asdict(ctx))

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
    parser.add_argument(
        "--l0-path", type=str, default=None,
        help="Path to L0 identity file for /wakeup (default: None, L0 layer skipped)",
    )
    return parser.parse_args(argv)


def run_server(
    port: int = 8420,
    idle_timeout: int = 14400,
    l0_path: str | None = None,
) -> None:
    """Start the server with idle timeout watcher."""
    import uvicorn

    app = create_app(idle_timeout=idle_timeout, l0_path=l0_path)
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
    run_server(port=args.port, idle_timeout=args.timeout, l0_path=args.l0_path)
