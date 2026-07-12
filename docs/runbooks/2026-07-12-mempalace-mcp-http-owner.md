# MemPalace MCP single HTTP owner (writer-lock starvation fix — F3)

**Date:** 2026-07-12 · **Status:** deployed (temp), systemd install pending · **Host:** 10.0.17.205

## Problem

Multiple concurrent Claude Code sessions each spawned their own **stdio** MemPalace MCP
server (`python -m mempalace.mcp_server`). Every server grabs a process-lifetime
**writer pre-lease** (`_acquire_mcp_writer_lock`, mcp_server.py) on its first tool call —
including the mandatory on-wake `mempalace_status`. The oldest session wins the lease and
**squats it while idle**; the read-only verdict is latched with no retry, so every newer
session is permanently read-only and its mutating tools fail with JSON-RPC
`-32001 "Peer MCP writer active"` until it restarts. (Full RCA:
`claude_docs/mempalace-writer-lock-rca-20260712.md` in the workspace.)

The single-writer guard itself is **correct** — ChromaDB `PersistentClient` is not
process-safe; two processes writing the same on-disk path corrupt the HNSW index. The
defect is the *topology*: per-session writers competing for one lease.

## Decision (F3)

Run **one** persistent MemPalace MCP server in HTTP mode and point every session's MCP
client at it, instead of each session spawning its own stdio writer.

- Service: `mempalace-mcp --transport http --host 127.0.0.1 --port 8765`
  (`deploy/mempalace-mcp-http.service`).
- `MEMPALACE_MCP_IDLE_HOURS=0` — disable the idle-exit watchdog (always up).
- `MEMPALACE_MCP_ALLOW_PEER_WRITER=1` — **required** (see below).
- MCP client config (`~/.claude.json`, both the global `mcpServers.mempalace` and the
  project-scoped entry) repointed from the stdio command to
  `{"type":"http","url":"http://127.0.0.1:8765/mcp"}`.

All writes now funnel through one process; `_HTTP_REQUEST_LOCK` (mcp_server.py:4569)
serializes them, so there is exactly one Chroma writer and no per-session lease to squat.

## Why `ALLOW_PEER_WRITER=1` is required *and* safe here

Two facts, both confirmed by reading mempalace 3.5.0 source:

1. **The built-in HTTP mode alone does not work for writes.** `_MCPHTTPServer` is a
   `ThreadingHTTPServer` (mcp_server.py:4632, `daemon_threads=True`) — one worker thread
   per request. The writer pre-lease, grabbed on the first request's thread, cannot be
   re-entered on a later write thread: `mine_palace_lock`'s re-entrancy short-circuit is
   keyed on `threading.local()` (palace.py:1043 docstring + `_palace_lock_holders`). The
   later write attempts a fresh `flock(LOCK_EX|LOCK_NB)` on the same lock file (a distinct
   OFD), fails, and reports the palace as "held by PID `<self>`". Reads work; writes
   self-deadlock. Upstream issue: **MemPalace/mempalace#1998**.

2. **`ALLOW_PEER_WRITER=1` disables only the redundant process-lifetime pre-lease** — not
   the per-write `mine_palace_lock`. That per-op lock (LOCK_NB, palace.py) still fires on
   every write and still prevents concurrent Chroma writes cross-process. So for a **single
   owner** the flag is safe: no corruption risk, and it sidesteps the thread-local
   self-conflict. (The RCA's earlier dismissal of this flag assumed it disables all write
   locking — it does not.)

## Residual fragility (know this before trusting it)

The pre-lease and the per-op mutex are the *same* file lock, so one process cannot both
"hold the lease to block peers" and "acquire per-op as the owner." With the pre-lease
disabled, the owner is authoritative **only while no other mempalace writer runs against
this palace**. If a lingering **stdio** session does an on-wake `status`, it grabs the
pre-lease and fail-fasts the owner's writes until that session exits.

- **Steady state (all sessions on HTTP, zero stdio): correct and reliable.**
- **Durable robustness requires the upstream fix** (#1998: serve HTTP single-threaded, or
  make the pre-lease process-scoped). Until then: do not run stdio mempalace servers
  against this palace.
- `mempalace` is third-party (`MemPalace/mempalace`, READ-only for us). The only in-house
  durable alternative would be a fork; deferred unless the fragility bites.

## Runbook

**Install / start (durable, systemd system unit — needs sudo):**
```
sudo cp deploy/mempalace-mcp-http.service /etc/systemd/system/mempalace-mcp-http.service
sudo systemctl daemon-reload
sudo systemctl enable --now mempalace-mcp-http.service
```

**Verify writable (no `-32001`, no self-conflict):**
```
curl -s -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"mempalace_add_drawer","arguments":{"wing":"canary","room":"smoke","content":"live-check"}}}' \
  http://127.0.0.1:8765/mcp
# expect: "success": true, a drawer_id
```

**Unstick (if writes start failing with "held by PID"):** a stdio mempalace server is
holding the pre-lease. Find and stop it:
```
lslocks | grep mine_palace          # shows the holder PID
ps -o pid,cmd -p <PID>              # confirm it's a stdio `python -m mempalace.mcp_server`
kill -TERM <PID>                    # frees the flock; owner reacquires per-op on next write
```

**Rollback (revert to per-session stdio):** stop the service and restore the stdio MCP
config from backup:
```
sudo systemctl disable --now mempalace-mcp-http.service
# restore ~/.claude.json mempalace entries to {"type":"stdio","command":".../python","args":["-m","mempalace.mcp_server"]}
```

## Related

- `:8420` `rawgentic-memorypalace.service` is a **separate** slim bridge (fact-check,
  diagnostics, gated canary writes) — not the writer. Its concurrent-canary path is
  unserialized (`tests/integration/test_concurrent_writes.py` fails under simultaneous
  writes); that is a pre-existing follow-up, independent of this change.
