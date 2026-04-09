# rawgentic-memorypalace -- Project Instructions

## Git Workflow

- **Never push directly to `main`.** All changes must go through a pull request.
- Create a feature branch, push it, and open a PR via `gh pr create`.

## Pre-PR Checklist

1. Run `pytest tests/ -v` -- must pass with 0 failures
2. Run lint/format checks if configured

## Testing Conventions

- **Sync tests with Starlette TestClient** -- use `from starlette.testclient import TestClient` (see `tests/conftest.py`). Do NOT use `httpx.AsyncClient` + `ASGITransport` for endpoint tests; the sync TestClient avoids async test complexity and is the established pattern for this project.
- **Hook/bash tests** use `subprocess.run()` to execute bash snippets with `lib.sh` sourced. Each test class uses a unique port to avoid cross-test pollution.

## Server Shutdown

Use `server.should_exit = True` (uvicorn's programmatic API) for graceful shutdown -- never `os.kill()` or `SIGTERM`. This is how the idle watcher (`_idle_watcher`) triggers shutdown, and how tests verify timeout behavior via a mock server object. The `app.state.server` reference is set in `run_server()`.
