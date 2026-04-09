# rawgentic-memorypalace

Claude Code plugin providing long-term memory via dual backends (native ChromaDB + MemPalace) with A/B comparison framework and semantic search.

## Prerequisites

- Python 3.10+
- `jq` (used by hook scripts for JSON parsing)
- `curl` (used by hook scripts for HTTP calls)

## Installation

```bash
claude plugin install rawgentic-memorypalace@rawgentic
```

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

## License

MIT
