"""Slim FastAPI server — routes all operations through MempalaceAdapter.

Single-process gatekeeper (ChromaDB multi-process access is unsafe).
Run via: python3 -m rawgentic_memory.server --port 8420 --timeout 14400
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from rawgentic_memory.adapter import MempalaceAdapter

logger = logging.getLogger(__name__)

# Endpoints excluded from idle-timeout tracking — monitoring calls
# should not keep the server alive.
_MONITORING_PATHS = frozenset({"/healthz", "/diagnostic"})


def _parse_body(raw: bytes) -> dict:
    """Tolerant JSON parser — returns {} on malformed body instead of 500."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def build_app(
    palace_path: str | None = None,
    idle_timeout: int = 14400,
) -> FastAPI:
    """Create and configure the slim FastAPI application.

    Args:
        palace_path: Path to the mempalace palace directory.
        idle_timeout: Seconds of inactivity before auto-shutdown. 0 to disable.
    """
    adapter = MempalaceAdapter(palace_path=palace_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.adapter = adapter
        app.state.start_time = time.monotonic()
        app.state.last_activity = time.monotonic()
        app.state.idle_timeout = idle_timeout
        app.state.server = None  # set by run_server() for programmatic shutdown
        # Run behavioral contract probe at startup (non-blocking warnings)
        violations = adapter.verify_behavioral_contract()
        for v in violations:
            logger.warning("contract violation: %s — expected %s, got %s",
                           v.field, v.expected, v.actual)
        yield

    app = FastAPI(
        title="rawgentic-memorypalace",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # --- Middleware ---

    @app.middleware("http")
    async def track_activity(request: Request, call_next):
        response = await call_next(request)
        if request.url.path not in _MONITORING_PATHS:
            request.app.state.last_activity = time.monotonic()
        return response

    # --- Endpoints ---

    @app.get("/healthz")
    async def healthz():
        h = adapter.health()
        return JSONResponse(asdict(h))

    @app.post("/search")
    async def search(request: Request):
        body = _parse_body(await request.body())
        prompt = body.get("prompt", "")
        if not prompt:
            return JSONResponse({"additionalContext": ""})
        min_similarity = float(body.get("min_similarity", 0.3))
        limit = int(body.get("limit", 10))
        results = adapter.search(query=prompt, limit=limit)
        # Filter by similarity threshold
        results = [r for r in results if r.similarity >= min_similarity]
        if not results:
            return JSONResponse({"additionalContext": ""})
        # Format as structured context for hook injection
        lines: list[str] = []
        for r in results:
            header = f"[{r.memory_type or 'memory'}]"
            if r.topic:
                header += f" ({r.topic})"
            header += f" sim={r.similarity:.2f}"
            if r.project:
                header += f" project={r.project}"
            lines.append(header)
            lines.append(r.content)
            lines.append("")
        return JSONResponse({"additionalContext": "\n".join(lines).strip()})

    @app.get("/wakeup")
    async def wakeup(project: str = Query(default="", max_length=128)):
        ctx = adapter.wakeup(project=project or None)
        return JSONResponse(asdict(ctx))

    @app.post("/fact_check")
    async def fact_check(request: Request):
        body = _parse_body(await request.body())
        # Support multiple text locations: direct "text", or nested tool_input
        text = body.get("text", "")
        if not text:
            tool_input = body.get("tool_input", {})
            text = tool_input.get("content", "") or tool_input.get("new_string", "")
        if not text:
            return JSONResponse({"additionalContext": ""})
        issues = adapter.fact_check(text)
        if not issues:
            return JSONResponse({"additionalContext": ""})
        lines: list[str] = []
        for issue in issues:
            line = f"[{issue.type}]"
            if issue.entity:
                line += f" entity={issue.entity}"
            line += f" {issue.detail}"
            lines.append(line)
        return JSONResponse({"additionalContext": "\n".join(lines)})

    @app.get("/diagnostic")
    async def diagnostic():
        h = adapter.health()
        violations = adapter.verify_behavioral_contract()
        now = time.monotonic()
        uptime = now - app.state.start_time
        idle = now - app.state.last_activity
        return JSONResponse({
            "health": asdict(h),
            "contract_violations": [asdict(v) for v in violations],
            "uptime_seconds": round(uptime, 2),
            "idle_seconds": round(idle, 2),
        })

    @app.post("/canary_write")
    async def canary_write(request: Request):
        body = _parse_body(await request.body())
        wing = body.get("wing", "")
        fact = body.get("fact", "")
        if wing != "canary":
            return JSONResponse(
                {"error": "Forbidden", "detail": "canary_write is gated to canary wing only"},
                status_code=403,
            )
        if not fact:
            return JSONResponse(
                {"error": "Bad Request", "detail": "Missing 'fact' field"},
                status_code=400,
            )
        ok = adapter.canary_write(fact)
        return JSONResponse({"ok": ok})

    # --- 410 Gone: removed endpoints ---

    @app.api_route("/ingest", methods=["GET", "POST"])
    async def gone_ingest():
        return JSONResponse(
            {"error": "Removed", "detail": "Use mempalace's native Save Hook"},
            status_code=410,
        )

    @app.api_route("/reindex", methods=["GET", "POST"])
    async def gone_reindex():
        return JSONResponse(
            {"error": "Removed", "detail": "Use mempalace mine CLI directly"},
            status_code=410,
        )

    @app.api_route("/kg/{path:path}", methods=["GET", "POST"])
    async def gone_kg(path: str = ""):
        return JSONResponse(
            {"error": "Removed", "detail": "Use MCP tools directly"},
            status_code=410,
        )

    return app


# --- Server entrypoint ---

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
        "--host", type=str, default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port", type=int, default=8420,
        help="Port to bind to (default: 8420)",
    )
    parser.add_argument(
        "--timeout", type=int, default=14400,
        help="Idle timeout in seconds (default: 14400 = 4h, 0 to disable)",
    )
    return parser.parse_args(argv)


def run_server(
    host: str = "127.0.0.1",
    port: int = 8420,
    idle_timeout: int = 14400,
) -> None:
    """Start the server with idle timeout watcher."""
    import uvicorn

    app = build_app(idle_timeout=idle_timeout)
    config = uvicorn.Config(
        app,
        host=host,
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
    run_server(host=args.host, port=args.port, idle_timeout=args.timeout)
