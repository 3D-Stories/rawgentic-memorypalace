# rawgentic-memorypalace -- Project Instructions

## Memory Server Configuration

```
MEMORY_SERVER_URL=http://127.0.0.1:8420
```

All skills and hooks use this URL to reach the memory server. To override (e.g., remote server), change the URL above or add a `Memory Server Configuration` section with the correct URL to your project's CLAUDE.md.

## Git Workflow

- **Never push directly to `main`.** All changes must go through a pull request.
- Create a feature branch, push it, and open a PR via `gh pr create`.

## Pre-PR Checklist

1. Run `pytest tests/ -v` -- must pass with 0 failures
2. Run lint/format checks if configured

## Testing Conventions

- **Sync tests with Starlette TestClient** -- use `from starlette.testclient import TestClient` (see `tests/conftest.py`). Do NOT use `httpx.AsyncClient` + `ASGITransport` for endpoint tests; the sync TestClient avoids async test complexity and is the established pattern for this project.
- **Hook/bash tests** use `subprocess.run()` to execute bash snippets with `lib.sh` sourced. Each test class uses a unique port to avoid cross-test pollution.

## ChromaDB Gotchas (v0.6+)

- `client.list_collections()` returns collection **name strings**, not Collection objects. Use `client.get_collection(name)` to get a usable Collection.
- Ephemeral clients share state within a process. Test fixtures must use `Settings(allow_reset=True)` and call `client.reset()` before each test to avoid cross-test pollution.

## Server Shutdown

Use `server.should_exit = True` (uvicorn's programmatic API) for graceful shutdown -- never `os.kill()` or `SIGTERM`. This is how the idle watcher (`_idle_watcher`) triggers shutdown, and how tests verify timeout behavior via a mock server object. The `app.state.server` reference is set in `run_server()`.

## Memory

When doing complex work (brainstorming, architecture, debugging, research),
search mempalace for relevant prior decisions and context before proposing
approaches. Your memories contain decisions, discoveries, and preferences
from previous sessions that should inform current work.

Use the `mempalace_search`, `mempalace_kg_query`, and `mempalace_kg_timeline`
MCP tools proactively. The bridge plugin auto-injects context for substantive
prompts (Layer 2), but mid-reasoning recall is your responsibility (Layer 3).

If you find a contradiction with a stored decision (Layer 4 fact-check
catches some automatically), surface it explicitly to the user.

**Recording a single-valued fact structurally (three-way KG rule).** When a decision or
other single-valued fact (the model in use, an employer, an address) is established or
changes, write it to the knowledge graph so point-in-time ("as-of") queries stay correct.
Pick exactly ONE primitive by what happened to the fact:

- value **CHANGED** (a decision reversed, a model/employer swapped) →
  `kg_supersede(subject, predicate, old, new)` — one atomic boundary
  (`/rawgentic-memorypalace:recall supersede "<subject> <predicate> <old> -> <new>"`);
- fact **ENDED** (no longer true, nothing replaces it) → `kg_invalidate`
  (`/rawgentic-memorypalace:recall invalidate`);
- new **INDEPENDENT / concurrent** fact → `kg_add` (recorded on `mempalace-save`).

Never hand-roll `kg_invalidate` + `kg_add` for a *changed* value — that leaves the old and
new value both open at the boundary, so an as-of query returns two. A reversed decision is a
supersede, not an invalidate-then-add.
