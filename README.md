# rawgentic-memorypalace

**v0.10.0** · Claude Code plugin providing long-term memory powered by [MemPalace](https://github.com/milla-jovovich/mempalace). Bridges Claude Code's hook system to MemPalace's Python API via a slim HTTP gatekeeper + adapter layer, with native MemPalace hooks handling ingest.

## Benchmark numbers — the rule before you quote one

**Upstream MemPalace's headline 96.6% is `R@5`: retrieval recall at five, with no LLM in the
loop.** It asks "did the right answer appear in the top five retrieved items?" It is not an
accuracy figure and it never becomes one by being written next to somebody else's.

Anywhere this repository states that number, it states `R@5` in the same breath. Where it sits
near another system's figure, the difference in what is being measured is stated there too, not
in a footnote — because "we win by a point" is a conclusion neither number supports in either
direction. Sibyl-Memory's 95.6%, for example, is end-to-end question-answering accuracy with a
frontier model generating the answer: a retriever plus a model plus a prompt, scored as one
thing.

We have no head-to-head result, and this repository does not manufacture one. See
[the comparison](docs/planning/2026-08-07-sibyl-memory-vs-mempalace.md) and issue #75.

## Architecture (r3)

Three independent pieces cooperate:

1. **MemPalace** (upstream) — the memory engine: palace-organized storage (wings/rooms/drawers), BM25 + semantic hybrid search, four layered wake-up (L0–L3), knowledge graph, fact-checking, AAAK dialect.
2. **MemPalace MCP server** (upstream) — exposes ~29 tools (`mempalace_search`, `mempalace_diary_write`, `mempalace_add_drawer`, `mempalace_kg_query`, etc.) to any LLM client over stdio.
3. **rawgentic-memorypalace** (this plugin) — the **bridge**. Three bash hooks + slim HTTP server + versioned adapter that connect Claude Code's session events to the memory engine.

### Why a bridge?

Claude Code hooks are short-lived bash processes. They can't import mempalace directly — they need a persistent server. ChromaDB also can't safely handle multi-process writes. So the bridge runs a single-process HTTP server (`:8420`) that serializes all palace access behind a stable adapter interface (`CONTRACT_VERSION=3`, `MIN_VERSION=3.3.0`, `MAX_VERSION<4.0`).

### What mempalace handles natively (not us)

- **L0 identity** — `~/.mempalace/identity.txt` injected at every session start
- **L1 memory context** — recent memories, diary entries, and per-wing context at session start
- **19+ MCP tools** — search, diary, drawers, KG, tunnels, etc.
- **Background mining** — conversation transcript and project content ingest
- **Stop/PreCompact hooks** — auto-save session content via MCP tools

### What this bridge adds (our unique value)

| Layer | Trigger | Mechanism | Cost |
|-------|---------|-----------|------|
| Tunnel context | `SessionStart` hook | `GET /wakeup` → cross-wing topic tunnels for multi-project awareness | One HTTP call per session |
| L2 — Auto-recall | `UserPromptSubmit` hook | Smart-gated `POST /search` on substantive prompts (> 20 chars, no slash commands, stop-words filtered, debounced) | ≤ 1 HTTP call per prompt |
| L3 — Proactive MCP | LLM reasoning | Claude directly calls `mcp__mempalace__mempalace_search` / `mempalace_kg_query` mid-thought | Zero infra cost — model budget only |
| L4 — Fact-checking | `PostToolUse` on Edit/Write/MultiEdit | Throttled `POST /fact_check` against file content | ≤ 1 HTTP call per file (per-session dedup) |

### Ingest path

Unlike r1/r2, this plugin does **no custom ingestion**. The plugin's `mempalace-hook-wrapper.sh` script (at `hooks/mempalace-hook-wrapper.sh`, configured in `~/.claude/settings.json` for Stop and PreCompact events) handles it. The Stop hook injects a `systemMessage` instructing the LLM to save session content via MCP tools (`mempalace_diary_write`, `mempalace_add_drawer`, `mempalace_kg_add`). The PreCompact hook forks the session to save before compaction (blocks compaction on failure). All writes route through the adapter's `canary_write()` in tests.

## Prerequisites

- Python 3.12+ (mempalace's minimum)
- `jq` (hook JSON parsing)
- `curl` (hook HTTP calls)
- MemPalace 3.3.4+ installed. Preferred: `pipx install mempalace` (isolates in its own venv). Alternative: `pip install --user mempalace`. Upgrade: `/rawgentic-memorypalace:upgrade` (auto-detects pipx vs pip).

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
| `RECALL_SIMILARITY_THRESHOLD` | 0.45 | Min similarity score for results to inject |
| `RECALL_MAX_RESULTS` | 5 | Max results per `/search` (bounds context budget) |
| `RECALL_PROJECT_SCOPE` | 1 | Scope per-prompt recall to the bound project (0 = off); explicit searches are never scoped. Known limitation: project resolution uses the workspace-wide most-recent project, so concurrent sessions can scope to the wrong project ([#54](https://github.com/3D-Stories/rawgentic-memorypalace/issues/54)) |
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
| `GET` | `/wakeup?project=<name>` | Cross-wing tunnel context for SessionStart injection |
| `GET` | `/tunnels?wing=<name>` | Browse cross-project topic tunnels for a wing |
| `POST` | `/search` | Smart-gated auto-recall (UserPromptSubmit) |
| `POST` | `/fact_check` | Layer 4 fact-checking on writes |
| `POST` | `/canary_write` | Test-only write (gated to `wing=canary`) |
| `*` | `/ingest`, `/reindex`, `/kg/*` | `410 Gone` with migration hint — these endpoints were removed; use MCP tools directly |

The server is **read-only** for non-canary requests. All writes go through MemPalace's MCP tools (called by the LLM, not by the bridge).

## Hook events

| Hook | Event | Matcher | Timeout | Behavior |
|------|-------|---------|---------|----------|
| `session-start` | SessionStart | (all) | 10s | `curl /wakeup` → inject tunnel context as `additionalContext` (L0+L1 handled by mempalace native hook) |
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
| `/rawgentic-memorypalace:recall invalidate "<fact>"` | Mark a decision as historical (via MCP tool) |
| `/rawgentic-memorypalace:recall timeline <entity>` | View decision history for an entity (via MCP tool) |
| `/rawgentic-memorypalace:recall tunnels [wing]` | Browse cross-project topic tunnels |
| `/rawgentic-memorypalace:upgrade` | Upgrade mempalace dependency, run migration |
| `/rawgentic-memorypalace:memory-ui up/down/status` | Web frontend containers for browsing the palace |

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -v
```

Knowledge-graph health check. It never mutates the graph tables or the main
database file; reading a WAL database may still touch the `-shm`/`-wal` sidecars.

```bash
python -m rawgentic_memory.kg_health          # 0 nothing wrong, 1 drift or duplicate, 2 could not check
python -m rawgentic_memory.kg_health --json
```

Palace linter — reports room/wing skew, wing-name fragmentation, knowledge-graph
coverage and near-empty wings. Exits non-zero only on a hard problem
(fragmentation, or a SQLite integrity error), never on skew:

```bash
python -m rawgentic_memory.palace_lint
python -m rawgentic_memory.palace_lint --json --max-items 50
```

Test suite — 313 tests, from `.venv/bin/pytest tests/ -q` on 2026-08-08. Re-run
that command rather than trusting this number; it is the kind that rots:
- `tests/test_adapter.py` — 35 tests for the versioned adapter (CONTRACT_VERSION=3, tunnel context, dynamic contract)
- `tests/test_server_slim.py` — 16 tests for the 7 HTTP endpoints + 410 Gone handlers
- `tests/test_lib_sh.py` — 16 tests for bash hook helpers (smart gate, debounce, dedup)
- `tests/test_hook_output_schema.py` — 17 tests validating all 4 hook scripts against Claude Code's hook-response schema (mock HTTP server, no live palace)
- `tests/test_portable_hooks.py` — 10 tests for wrapper portability (no hardcoded paths, recursion guard, workspace auto-detection)
- `tests/test_plugin_structure.py` — 20 tests for plugin/marketplace config (version match, required fields, no MCP default)
- `tests/test_recall_skill.py` — 24 tests for the recall skill (search, invalidate, timeline subcommands)
- `tests/test_memory_ui_skill.py` — 16 tests for the memory-ui skill
- `tests/test_frontend_compose.py` — 16 tests for frontend Docker Compose config
- `tests/test_frontend_decision.py` — 12 tests for frontend deployment decisions
- `tests/test_kg_health.py` — 28 tests for the knowledge-graph drift detector (declared predicates, read-only guarantee, exit codes)
- `tests/test_palace_lint.py` — 41 tests for the palace linter (fragmentation exactness, skew, truncation reporting, status validation, exit codes)
- `tests/test_benchmark_claims.py` — 5 tests pinning the `R@5` label on every mention of the 96.6% figure
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

## Changelog

### v0.10.0 (2026-08-08)

- **The benchmark figure always carries its metric (rawgentic#75).** 96.6% is `R@5` — retrieval recall at five, no LLM in the loop — and it reads as an accuracy figure the moment it sits beside somebody else's. Every mention in tracked markdown now states `R@5` within a few lines of the number, the new **Benchmark numbers** section at the top of this README states the rule, and `tests/test_benchmark_claims.py` pins both so the label cannot rot silently. **The audit found the debt was much smaller than the issue assumed:** this README never quoted the figure at all, no skill or hook mentions it, and the two research-doc mentions were already *criticising* the number rather than claiming it. The real gap was two sentences in the comparison doc — which the new guard found, and I had wrongly assumed were fine. Path A of the issue, done; Path B (running LongMemEval end to end and publishing the kit) is untouched and still open as an option.
- Also corrected: this README's header claimed **v0.4.2** while the plugin was at v0.9.0.

### v0.9.0 (2026-08-08)

- **Palace linter (rawgentic#73).** `python -m rawgentic_memory.palace_lint [--json] [--max-items N]` reports room skew, wing skew, wing-name fragmentation, knowledge-graph coverage and near-empty wings. It **reports shape and enforces almost nothing** — skew is a judgment call, and a linter that failed the build over it would just be switched off. Two conditions are hard enough to exit non-zero: wing-name fragmentation, and a SQLite integrity error as reported by upstream. Fragmentation detection is exact equality after normalization (strip a leading `wing_`, hyphen to underscore, lowercase), never a similarity score — which is what keeps `rawgentic` and `rawgentic-next` apart while still merging `herdr-dashboard` with `herdr_dashboard`. Integrity and totals are consumed from upstream's public `tool_status()` rather than reimplemented, and knowledge-graph coverage reuses the #72 checker. Every cap reports what it withheld. **First live run: 22,110 drawers, 51 wings, 66 rooms — `documentation` 84.7%, `chorestory` 46.1%, knowledge-graph coverage 0.7%, and 3 fragmented wing names, so it exits 1 on the palace as it stands today.** Fixing what it finds is deliberately out of scope: the `documentation` room is #74/#77, and a wing rename moves other sessions' memories.

### v0.8.0 (2026-08-08)

- **Knowledge-graph drift detector (rawgentic#72).** `python -m rawgentic_memory.kg_health [--db PATH] [--json]` reports every `(subject, predicate)` holding more than one CURRENT value — the state a single-valued fact must never be in. Exit `0` nothing unambiguously wrong, `1` drift on a declared single-valued predicate **or the same fact open twice**, `2` could not check (an absent or unreadable database must never read as clean). `SINGLE_VALUED_PREDICATES` is declared data, so the set can be read and extended in one place; drift on an undeclared predicate is reported but never fails the check, and a debatable predicate is deliberately left out — a wrong entry fails the check on valid data and teaches everyone to ignore it. Every query runs in one read transaction, because the live graph has an active writer. The module never mutates the knowledge-graph tables or the main database file; SQLite may still touch the `-shm`/`-wal` sidecars when reading a WAL database, which is reader coordination state rather than palace content. The database path is percent-encoded from its filesystem bytes before it becomes a URI, so a path carrying `?mode=rwc` cannot turn the check into a writer. **First live run: 291 entities, 160 triples, 158 current, 2 expired, 144 distinct predicates, zero drift.** What did NOT ship is the refusing constraint the issue also asked for: the store is the upstream third-party `mempalace` package (pinned `>=3.3.5,<4.0`), and this server already returns 410 Gone on `/kg/*`, so every knowledge-graph write goes to upstream and never touches this code. That guard belongs upstream — see #72.

### v0.7.0 (2026-07-22)

- **`recall supersede` + the three-way KG write rule (rawgentic#64).** `/rawgentic-memorypalace:recall` gains a `supersede` subcommand — `supersede "<subject> <predicate> <old> -> <new>"` calls `mempalace_kg_supersede`, the atomic primitive for a single-valued fact that CHANGES value (a decision reversed, a model/employer swapped); it closes the old value and opens the new one at one shared boundary, so an as-of query returns only the new value. Parse errors return an expected-format message. `mempalace-save` and the project memory-authority guidance now state the three-way rule: value **CHANGED** → `kg_supersede` (one atomic boundary), fact **ENDED** → `kg_invalidate`, new **INDEPENDENT** fact → `kg_add` — never hand-roll `invalidate` + `add` for a change (it leaves the old and new value both open at the boundary). Existing `invalidate`/`timeline` routes are unchanged. (The v0.6.0 plugin bump in #63 shipped without a Changelog entry — a pre-existing gap, noted, not addressed here.)

### v0.5.0 (2026-07-14)

- **`/rawgentic-memorypalace:mempalace-save` skill — bundle session checkpointing into the plugin.** Promotes the `mempalace-save` workspace skill into the plugin as `rawgentic-memorypalace:mempalace-save`: writes an AAAK-compressed diary entry (`mempalace_diary_write`) plus verbatim drawers (`mempalace_add_drawer`) for key decisions/code/quotes, with writer-lease-busy, secrets-by-name, and privacy guardrails. The write-side companion to `/rawgentic-memorypalace:recall`. The server address is resolved from the user-configured MCP connection — never hardcoded; a regression-guard test (`tests/test_save_skill.py`) forbids a bundled IP.

### v0.4.5 (2026-07-08)

- **PreCompact degraded path (rawgentic#306) + dead fail-closed block fixed.** The PreCompact block-on-save-failure path was dead code — `SAVE_OUTPUT=$(...) || true` left `SAVE_EXIT` always 0, and a mempalace outage exits the fork 0 anyway (failure reported only in prose) — so every fork failure silently *approved with no save*. Success now requires exit 0 AND the "Saved … drawer/diary" confirmation; on failure the session transcript is copied to a local fallback (`MEMPALACE_PRECOMPACT_FALLBACK_DIR`, default `~/.mempalace-wrapper-state/precompact-fallback/`) and compaction is approved with a loud DEGRADED reason (stderr + log + reason); compaction blocks only when BOTH the mempalace save and the local fallback fail. Red-first: outage, both-fail, prose-failure, and healthy-path pin tests.

### v0.4.4 (2026-07-08)

- **Recall tuning (rawgentic#305).** Fixed a silent transport bug: the recall hook sent `X-Similarity-Threshold`/`X-Max-Results` as HTTP headers but `/search` only read the JSON body, so `RECALL_SIMILARITY_THRESHOLD` never applied and recall always filtered at 0.3. `/search` now honors those headers (body/defaults preserved for explicit callers). Default threshold raised 0.30 → 0.45. New `RECALL_PROJECT_SCOPE` knob (default on) scopes per-prompt recall to the bound project via a new `X-Project` header — normalized `-`/`_` matching, project-less (global/diary) memories stay visible; explicit searches (MCP tools, direct `/search`) unaffected. `marketplace.json` version re-synced with `plugin.json` (drift left by v0.4.3).

### v0.4.3 (2026-07-08)

- **Auto-save instruction states mempalace authority (rawgentic#304).** SessionStart/Stop hook wording now names mempalace as the authoritative long-term memory. (Changelog entry backfilled in v0.4.4 — the v0.4.3 PR omitted it and the `marketplace.json` bump.)

### v0.4.2 (2026-05-13)

- **Hook commands use exec form.** `hooks/hooks.json` now declares `args: []` on every entry so Claude Code invokes hooks directly via `execv` instead of `/bin/sh -c "string"`. Permanently eliminates the shell-quoting class of bugs (per [Claude Code v2.1.139 hooks reference](https://code.claude.com/docs/en/hooks.md)). Backward compatible — `args` is ignored on older Claude Code versions.

### v0.4.1 (2026-05-13)

- **Fix `${CLAUDE_PLUGIN_ROOT}` not expanding in hook commands.** Each command in `hooks/hooks.json` was wrapped in literal single quotes (`"'${CLAUDE_PLUGIN_ROOT}/hooks/...'"`); a recent Claude Code update changed env-var expansion behavior, and `/bin/sh -c` then tried to exec a file literally named `${CLAUDE_PLUGIN_ROOT}/hooks/...`. `SessionStart`, `UserPromptSubmit`, and `PostToolUse` were all failing with `not found`. Removed the wrapping quotes so the variable expands correctly. `marketplace.json` version synced with `plugin.json`.

### v0.4.0 (2026-05-01)

**Breaking:** `/wakeup` no longer returns L0+L1 layers. Mempalace's native SessionStart hook handles identity and memory context. Our plugin now contributes only cross-wing tunnel context at session start.

- **Upgrade mempalace** 3.3.2 → 3.3.4 (HNSW bloat fix, cross-wing tunnels, Claude Code conversation tagging, PreCompact deadlock fix, ChromaDB reopen crash fix)
- **Tunnel-only wakeup** — `wakeup()` returns cross-wing topic tunnel context instead of duplicating L0+L1. New `TunnelLink` dataclass, `find_tunnels_for_wing()` method, `_render_tunnel_context()` formatter
- **New `/tunnels` endpoint** — `GET /tunnels?wing=<name>` returns structured tunnel data for a wing
- **Dynamic MCP tool contract** — `CRITICAL_MCP_TOOLS` frozenset (6 tools) replaces hardcoded list; severity escalated to `error`; logs "mempalace exposes N MCP tools (6 critical)" at startup
- **Recall skill fix** — `invalidate` and `timeline` subcommands now route through `mempalace_kg_invalidate` / `mempalace_kg_timeline` MCP tools (previously hit 410 Gone `/kg/*` endpoints)
- **New `tunnels` recall subcommand** — `/rawgentic-memorypalace:recall tunnels [wing]` browses cross-project topic tunnels
- **SessionStart hook rewritten** — only injects tunnel context; skips entirely when no project resolved
- **Upgrade skill updated** — import verification uses 3.3.4 API paths (`palace_graph`, `fact_checker`); removes `Layer0`/`Layer1` (no longer used by adapter)

### v0.3.0 (2026-04-24)

- Initial public release (r3 architecture)
- Three-plugin split: rawgentic + mempalace MCP + bridge
- Adapter pattern with `CONTRACT_VERSION=3`, `MIN_VERSION=3.3.0`
- Four recall layers: wakeup, auto-recall, proactive MCP, fact-checking
- Slim HTTP server (~260 LOC, single-process ChromaDB gatekeeper)
- Smart-gated hooks with debounce, stop-word filtering, per-file dedup
- Save orchestration: throttled Stop hook + PreCompact fork-resume with blocking
- Skills: recall (search/invalidate/timeline), upgrade, memory-ui

## License

MIT
