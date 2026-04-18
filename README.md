# rawgentic-memorypalace

Claude Code plugin providing long-term memory powered by [MemPalace](https://github.com/milla-jovovich/mempalace). Bridges Claude Code's hook system to MemPalace's Python API via a slim HTTP gatekeeper + adapter layer, with native MemPalace hooks handling ingest.

## Architecture (r3)

Three independent pieces cooperate:

1. **MemPalace** (upstream) — the memory engine: palace-organized storage (wings/rooms/drawers), BM25 + semantic hybrid search, four layered wake-up (L0–L3), knowledge graph, fact-checking, AAAK dialect.
2. **MemPalace MCP server** (upstream) — exposes ~29 tools (`mempalace_search`, `mempalace_diary_write`, `mempalace_add_drawer`, `mempalace_kg_query`, etc.) to any LLM client over stdio.
3. **rawgentic-memorypalace** (this plugin) — the **bridge**. Three bash hooks + slim HTTP server + versioned adapter that connect Claude Code's session events to the memory engine.

### Why a bridge?

Claude Code hooks are short-lived bash processes. They can't import mempalace directly — they need a persistent server. ChromaDB also can't safely handle multi-process writes. So the bridge runs a single-process HTTP server (`:8420`) that serializes all palace access behind a stable adapter interface (`CONTRACT_VERSION=3`, `MIN_VERSION=3.3.0`, `MAX_VERSION<4.0`).

### Four recall layers

| Layer | Trigger | Mechanism | Cost |
|-------|---------|-----------|------|
| L1 — Session wakeup | `SessionStart` hook | `GET /wakeup` → L0 identity + L1 recent context injection | One HTTP call per session |
| L2 — Auto-recall | `UserPromptSubmit` hook | Smart-gated `POST /search` on substantive prompts (> 20 chars, no slash commands, stop-words filtered, debounced) | ≤ 1 HTTP call per prompt |
| L3 — Proactive MCP | LLM reasoning | Claude directly calls `mcp__mempalace__mempalace_search` / `mempalace_kg_query` mid-thought | Zero infra cost — model budget only |
| L4 — Fact-checking | `PostToolUse` on Edit/Write/MultiEdit | Throttled `POST /fact_check` against file content | ≤ 1 HTTP call per file (per-session dedup) |

### Ingest path

Unlike r1/r2, this plugin does **no custom ingestion**. The plugin's `mempalace-hook-wrapper.sh` script (at `hooks/mempalace-hook-wrapper.sh`, configured in `~/.claude/settings.json` for Stop and PreCompact events) handles it. The Stop hook injects a `systemMessage` instructing the LLM to save session content via MCP tools (`mempalace_diary_write`, `mempalace_add_drawer`, `mempalace_kg_add`). The PreCompact hook forks the session to save before compaction (blocks compaction on failure). All writes route through the adapter's `canary_write()` in tests.

## Prerequisites

- Python 3.12+ (mempalace's minimum)
- `jq` (hook JSON parsing)
- `curl` (hook HTTP calls)
- MemPalace 3.3.0+ installed. Preferred: `pipx install mempalace` (isolates in its own venv). Alternative: `pip install --user mempalace`. Upgrade: `/rawgentic-memorypalace:upgrade` (auto-detects pipx vs pip).

## Installation

```bash
claude plugin install rawgentic-memorypalace@rawgentic-memorypalace
```

This installs the bridge (HTTP server + bash hooks). MemPalace itself and the MemPalace MCP server are **separate setup steps** — the bridge alone can't know which Python environment holds your MemPalace install, so it doesn't guess.

### MCP Setup

Pick the path that matches your deployment:

**(a) Single-workstation, `pip install --user mempalace`:**
```bash
claude mcp add -s user mempalace -- python3 -m mempalace.mcp_server
```
Works if `python3` on PATH has `mempalace` importable.

**(b) Single-workstation, `pipx install mempalace`:**
```bash
claude mcp add -s user mempalace -- ~/.local/share/pipx/venvs/mempalace/bin/python -m mempalace.mcp_server
```
pipx isolates mempalace in its own venv — point at that venv's python directly.

**(c) Central server (multiple client hosts share one palace via SSH):**
On the **server host** (e.g. 10.0.17.205), install mempalace and run the slim server bound to a LAN-reachable address (see [Central Server](#central-server) below). On each **client host**:
```bash
claude mcp add -s user mempalace -- ssh <server-host> exec ~/.local/share/pipx/venvs/mempalace/bin/python -m mempalace.mcp_server
```
MCP's stdio protocol tunnels over SSH — all palace operations execute in the server's mempalace process. Clients need SSH access but no local mempalace install.

After install, **configure your identity**:

```bash
# ~/.mempalace/identity.txt — L0 context shown at every session start
cat > ~/.mempalace/identity.txt <<EOF
I am the memory layer for <your name>, <your role>.

Active projects: ...
Conventions: ...
EOF
```

## Configuration

### Memory server URL

Default `http://127.0.0.1:8420`. Override via project `CLAUDE.md` section `Memory Server Configuration` or env var `MEMORY_SERVER_URL`.

### Tunable thresholds (all env-configurable from v1)

| Var | Default | Purpose |
|-----|---------|---------|
| `RECALL_MIN_PROMPT_CHARS` | 20 | Skip `/search` on prompts shorter than this |
| `RECALL_DEBOUNCE_SECS` | 30 | Minimum seconds between `/search` calls per project |
| `RECALL_SIMILARITY_THRESHOLD` | 0.30 | Min similarity score for results to inject |
| `RECALL_MAX_RESULTS` | 5 | Max results per `/search` (bounds context budget) |
| `FACT_CHECK_DEBOUNCE_SECS` | 60 | Minimum seconds between `/fact_check` calls |
| `MEMPALACE_CLAUDE_WORKSPACE` | auto-detected from `.cwd` | Override workspace root for session registry lookups and PreCompact fork |
| `MEMPALACE_STOP_BLOCK_INTERVAL_SECS` | 900 (15 min) | Minimum seconds between Stop hook save injections |
| `MEMPALACE_PRECOMPACT_TIMEOUT_SECS` | 180 (3 min) | Timeout for the PreCompact fork-save operation |
| `MEMPAL_DIR` | — | Directory for MemPalace's Background Everything miner |
| `MEMORY_DEBUG` | — | Set to `1` to enable hook stderr logging |
| `MEMORY_NO_AUTOSTART` | — | Set to `1` to prevent `SessionStart` from lazy-starting the server |

## Endpoints (slim server)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/healthz` | Quick health check (no palace access) |
| `GET` | `/diagnostic` | Full component health + contract violations + uptime/idle |
| `GET` | `/wakeup?project=<name>` | L0 + L1 context for SessionStart injection |
| `POST` | `/search` | Smart-gated auto-recall (UserPromptSubmit) |
| `POST` | `/fact_check` | Layer 4 fact-checking on writes |
| `POST` | `/canary_write` | Test-only write (gated to `wing=canary`) |
| `*` | `/ingest`, `/reindex`, `/kg/*` | `410 Gone` with migration hint — these endpoints were removed; use MCP tools directly |

The server is **read-only** for non-canary requests. All writes go through MemPalace's MCP tools (called by the LLM, not by the bridge).

## Hook events

| Hook | Event | Matcher | Timeout | Behavior |
|------|-------|---------|---------|----------|
| `session-start` | SessionStart | (all) | 10s | `curl /wakeup` → inject as `additionalContext` |
| `user-prompt-submit` | UserPromptSubmit | (all) | 5s | Smart-gate → `curl /search` → inject `additionalContext` on hit |
| `post-tool-use` | PostToolUse | `Edit\|Write\|MultiEdit` | 5s | Throttle + dedup → `curl /fact_check` |

Plugin wrapper hooks (configured in `~/.claude/settings.json`, shipped in `hooks/mempalace-hook-wrapper.sh`):

| Command | Event | Timeout | Behavior |
|---------|-------|---------|----------|
| `mempalace-hook-wrapper.sh stop` | Stop | 210s | Time-throttled (15 min default). When due, injects `systemMessage` instructing Claude to save via MCP. Recursion-guarded. |
| `mempalace-hook-wrapper.sh precompact` | PreCompact | 210s | Forks the session to save via MCP. Blocks compaction on failure (information loss prevention). |

All bridge hooks degrade gracefully — if the memory server is unreachable, they exit 0 with no output. The wrapper auto-detects the workspace root from hook input `.cwd` (override via `MEMPALACE_CLAUDE_WORKSPACE`).

## Skills

| Skill | Description |
|-------|-------------|
| `/rawgentic-memorypalace:recall <query>` | Semantic search over stored memories |
| `/rawgentic-memorypalace:recall invalidate "<fact>"` | Mark a decision as historical |
| `/rawgentic-memorypalace:recall timeline <entity>` | View decision history for an entity |
| `/rawgentic-memorypalace:upgrade` | Upgrade mempalace dependency, run migration |
| `/rawgentic-memorypalace:memory-ui up/down/status` | Web frontend containers for browsing the palace |

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -v
```

Test suite (171 unit tests):
- `tests/test_adapter.py` — 26 tests for the versioned adapter (CONTRACT_VERSION=3)
- `tests/test_server_slim.py` — 14 tests for the 6 HTTP endpoints + 410 Gone handlers
- `tests/test_lib_sh.py` — 16 tests for bash hook helpers (smart gate, debounce, dedup)
- `tests/test_hook_output_schema.py` — 17 tests validating all 4 hook scripts against Claude Code's hook-response schema (mock HTTP server, no live palace)
- `tests/test_portable_hooks.py` — 10 tests for wrapper portability (no hardcoded paths, recursion guard, workspace auto-detection)
- `tests/test_plugin_structure.py` — 20 tests for plugin/marketplace config (version match, required fields, no MCP default)
- `tests/test_recall_skill.py` — 24 tests for the recall skill (search, invalidate, timeline subcommands)
- `tests/test_memory_ui_skill.py` — 16 tests for the memory-ui skill
- `tests/test_frontend_compose.py` — 16 tests for frontend Docker Compose config
- `tests/test_frontend_decision.py` — 12 tests for frontend deployment decisions
- `tests/integration/` — graceful degradation, hook timeouts, version boundaries, acceptance criteria
- `tests/canary.py` — standalone continuous-health canary script

## Migration from r1/r2

This is a **breaking cutover**, not an additive update. r3 replaces:

- Custom `enrichment.py` regex pipeline → MemPalace's `general_extractor` + Save Hook
- Custom `mempalace_backend.py` wrapper → versioned `adapter.py` (CONTRACT_VERSION=3)
- ~500-line FastAPI server → slim ~260-line server (6 endpoints, read-only)
- Custom `hooks/stop` → MemPalace native `Stop` hook in `settings.json`
- `/ingest`, `/reindex`, `/kg/*` endpoints → removed (return `410 Gone`); use MCP tools directly

Data migrated automatically via `mempalace migrate` (idempotent) in the upgrade path. Old palace is backed up to `~/.mempalace.backup-<date>` before any changes.

## Central Server

For a single mempalace shared by multiple Claude Code workstations, run the bridge's slim server on one host ("server host") bound to a network-reachable address, and configure other hosts as pure clients.

### On the server host

1. Install mempalace (pipx or pip — your choice) so `mempalace` CLI is on PATH.
2. Install and configure the plugin + native hooks + local MCP (same as single-workstation setup).
3. Run the slim server bound to your LAN-reachable address. Easiest: a systemd unit.

Example `/etc/systemd/system/rawgentic-memorypalace.service`:

```ini
[Unit]
Description=rawgentic-memorypalace slim HTTP server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<your-user>
WorkingDirectory=/path/to/rawgentic-memorypalace-checkout
ExecStart=/path/to/.venv/bin/python -m rawgentic_memory.server --host 0.0.0.0 --port 8420 --timeout 0
Restart=on-failure
RestartSec=5s
StandardOutput=append:/var/log/rawgentic-memorypalace.log
StandardError=append:/var/log/rawgentic-memorypalace.log

[Install]
WantedBy=multi-user.target
```

Enable + start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rawgentic-memorypalace.service
```

Open your firewall for inbound on port 8420 (LAN only unless you want public access):
```bash
sudo ufw allow from <LAN-cidr> to any port 8420 proto tcp comment "rawgentic-memorypalace from LAN"
```

### On each client host

1. Install the plugin (`claude plugin install rawgentic-memorypalace@...`) — you do NOT need mempalace installed locally.
2. Set env vars in `~/.bashrc`:
   ```bash
   export MEMORY_SERVER_URL=http://<server-host>:8420
   export MEMORY_NO_AUTOSTART=1  # don't try to lazy-start a local server
   ```
3. Register MCP via SSH tunnel (see [MCP Setup](#mcp-setup) option c).
4. Register Stop + PreCompact hooks in `~/.claude/settings.json`. The wrapper lives in the plugin at `hooks/mempalace-hook-wrapper.sh` — find the installed path with `jq -r '.plugins["rawgentic-memorypalace@rawgentic-memorypalace"][0].installPath' ~/.claude/plugins/installed_plugins.json`:
   ```json
   {
     "hooks": {
       "Stop": [{"matcher":"*","hooks":[{"type":"command","command":"<plugin-install-path>/hooks/mempalace-hook-wrapper.sh stop","timeout":210}]}],
       "PreCompact": [{"hooks":[{"type":"command","command":"<plugin-install-path>/hooks/mempalace-hook-wrapper.sh precompact","timeout":210}]}]
     }
   }
   ```
   Alternatively, copy the wrapper to `~/.local/bin/mempalace-hook-wrapper.sh` and reference it there.
5. Passwordless SSH to the server host must be set up (hooks can't prompt for a password). The wrapper's PreCompact mode forks the session via `claude --resume`, which must run from the workspace root — set `MEMPALACE_CLAUDE_WORKSPACE` in the Stop hook command if auto-detection from `.cwd` doesn't resolve correctly.

### Architectural note

With the SSH-tunneled MCP + LAN-exposed HTTP server, **every palace operation from every client executes in the server's single mempalace process**. This sidesteps ChromaDB's multi-process unsafety — there is only one writer, by construction.

Tradeoffs:
- Added MCP call latency: SSH overhead ~50–200ms per call. Acceptable for memory operations (not hot-path).
- Single point of failure: if the server host is down, clients lose memory (hooks exit 0 silently, MCP tools return errors).
- SSH key management: clients need key-based auth to the server.

## Concurrency

All palace access goes through the single-process HTTP server (`:8420`). ChromaDB's multi-process behavior is unsafe (no HNSW file locking, DELETE journal mode) — the server acts as a gatekeeper. MemPalace's native hooks also access the palace via MCP (separate process), but only through specific write operations (`mempalace_diary_write`, `mempalace_add_drawer`) — not the high-throughput bulk ingest that caused r1/r2 corruption.

## Troubleshooting

### `mempalace MCP: ✗ Failed to connect`

The plugin does NOT declare a default MCP config (since 0.2.1) — you configure MCP explicitly for your environment. If you see "Failed to connect" in `claude mcp list`, it's probably because:

- You haven't run `claude mcp add` yet → see [MCP Setup](#mcp-setup) for the exact command per environment.
- You ran `claude mcp add` with bare `python -m mempalace.mcp_server` but your `python` doesn't have mempalace importable → switch to `python3` if that's your binary name, or use the pipx-venv path explicitly.
- You're on a client host pointing at a central server via SSH, but passwordless SSH isn't set up → configure key-based auth to the server.

### Server won't start

Check the log: `tail -50 /tmp/memorypalace-server.log`. Common causes: port 8420 in use (kill the old process), palace not initialized (`mempalace init --yes ~/.mempalace/palace`), or ChromaDB version mismatch (`mempalace migrate`).

### Recall returns no results on prompts you expect to match

- Check the similarity threshold — lower `RECALL_SIMILARITY_THRESHOLD` below 0.5 if your prompts are terse.
- Check the wing — auto-recall filters by the active rawgentic project. Search via MCP (`mempalace_search` with no wing filter) to confirm the content is in the palace.
- Check `/diagnostic` — look for `contract_violations` (version drift, missing MCP tools).

### Stop hook shows "AUTO-SAVE checkpoint" at session end

That's working as intended — the wrapper's Stop hook injects a `systemMessage` instructing Claude to save session content via MCP. It's time-throttled (default: every 15 min, controlled by `MEMPALACE_STOP_BLOCK_INTERVAL_SECS`). To disable temporarily, comment out the Stop hook in `~/.claude/settings.json`.

### "Hook JSON output validation failed" on Stop hook

The Stop hook must output top-level fields (`systemMessage`, `decision`, `reason`) — NOT `hookSpecificOutput`. If you see this error, your wrapper is outdated. Update it by copying from the plugin: `cp <plugin-path>/hooks/mempalace-hook-wrapper.sh ~/.local/bin/`.

## License

MIT
