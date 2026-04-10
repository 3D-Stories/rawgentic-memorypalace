# rawgentic-memorypalace

Claude Code plugin providing long-term memory powered by [MemPalace](https://github.com/milla-jovovich/mempalace) with intelligent ingestion triggers, semantic search, and wake-up context.

## Architecture

rawgentic-memorypalace is the **operational chassis** around MemPalace's **memory engine**:

- **MemPalace** handles: palace-organized storage (wings/rooms/drawers), semantic search, layered wake-up (L0+L1), and knowledge graphs
- **rawgentic-memorypalace** adds: three ingestion triggers (PreCompact, timer, Stop), offset-based incremental dedup, lazy-start server lifecycle, `/recall` skill, `/upgrade` skill, and `/memory-ui` skill for web frontend management

**Two integration paths coexist:**
- Claude Code hooks (HTTP) → Our FastAPI server → MemPalace library API
- Claude Code tools (MCP) → MemPalace MCP server → MemPalace library API

## Prerequisites

- Python 3.10+
- `jq` (used by hook scripts for JSON parsing)
- `curl` (used by hook scripts for HTTP calls)

## Installation

```bash
claude plugin install rawgentic-memorypalace@rawgentic
```

This installs `mempalace>=3.0.0,<4.0` as a declared dependency.

## Configuration

The memory server URL defaults to `http://127.0.0.1:8420`. Override via:

```bash
export MEMORY_SERVER_URL="http://127.0.0.1:8420"
```

### Debug Logging

Enable verbose hook logging to stderr:

```bash
export MEMORY_DEBUG=1
```

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest
```

## Hook Events

| Hook | Event | Behavior |
|------|-------|----------|
| session-start | SessionStart (startup/resume) | Fetches wake-up context from `/wakeup` |
| session-start | SessionStart (compact) | Triggers async ingest via `/ingest` (PreCompact) |
| user-prompt-submit | UserPromptSubmit | Triggers background ingest if 2h elapsed |
| stop | Stop | Synchronous final flush via `/ingest` |

All hooks degrade gracefully — if the memory server is unreachable, they exit silently without affecting the Claude Code session.

## Skills

| Skill | Description |
|-------|-------------|
| `/recall <query>` | Semantic search over stored memories |
| `/recall invalidate "<subject> decided <object>"` | Mark a decision as historical |
| `/recall timeline <entity>` | View decision history for an entity |
| `/upgrade` | Upgrade the mempalace dependency to latest version |
| `/memory-ui up` | Start web frontend containers |
| `/memory-ui down` | Stop web frontend containers |
| `/memory-ui status` | Show container state, ports, and uptime |

## Web Frontend

Two instances of [memory-palace-web-frontend](https://github.com/tomsalphaclawbot/memory-palace-web-frontend) for visually browsing each backend's ChromaDB data:

| Instance | URL | Data Source |
|----------|-----|-------------|
| Native backend browser | http://localhost:8098 | Native ChromaDB |
| MemPalace backend browser | http://localhost:8099 | MemPalace palace |

### Quick start

```bash
cd ~/.claude/plugins/cache/rawgentic-memorypalace/rawgentic-memorypalace/0.1.0/frontend
cp .env.example .env          # edit NATIVE_CHROMADB_PATH to match your data
docker compose up -d --build   # first run builds the image (~2 min)
```

Or use the skill: `/memory-ui up`

See `docs/frontend-decision.md` for the architecture decision record.

## Data Migration

If you have existing data from an earlier native ChromaDB backend, rebuild the index using the `/reindex` endpoint:

```bash
curl -X POST http://127.0.0.1:8420/reindex \
  -H "Content-Type: application/json" \
  -d '{"source_dirs": ["/path/to/your/session_notes"]}'
```

This re-enriches all source files and stores them in MemPalace's palace structure.

## Concurrency Note

Our HTTP server and MemPalace's MCP server both access the palace directory. ChromaDB uses SQLite file locks with a 10-second timeout. Low write frequency makes contention unlikely, but concurrent writes from both processes could occasionally cause `sqlite3.OperationalError: database is locked`.

## License

MIT
