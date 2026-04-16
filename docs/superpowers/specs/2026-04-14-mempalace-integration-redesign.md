# MemPalace Integration Redesign

**Date:** 2026-04-14
**Status:** Design — Pending Implementation (Revision 2 after BMAD party-mode review)
**Author:** Brainstorm session with Claude

## Revision History

| Date | Change | Reason |
|---|---|---|
| 2026-04-14 (r1) | Initial design | Brainstorm session output |
| 2026-04-14 (r2) | Reinstate HTTP server as single-process gatekeeper; reorder phases for atomic cutover; pipe JSON to stdin (no shell expansion); add behavioral contract; add canary test; throttle PostToolUse | BMAD party-mode review (Winston, Amelia, Murat, Dr. Quinn) verified ChromaDB multi-process unsafe + cold-start latency 7-10x worse than estimated |
| 2026-04-14 (r3) | Fix per-file dedup filename; fix canary multi-process write; split `ensure_server_running` from `server_is_healthy`; downgrade ChromaDB risk to "Low"; env-configurable thresholds; case-insensitive confirmation patterns; max content cap; document Claude compliance dependency; troubleshooting section; diagnostic endpoint; canary write endpoint | Reflexion critique (Requirements Validator, Solution Architect, Code Quality Reviewer) found 3 critical code bugs + 4 high-priority refinements |

## Goal

Make memory integration seamless and automatic on both ingest and recall, eliminate the lossy custom enrichment pipeline, and architect for long-term resilience against upstream mempalace changes.

## Problem Statement

The current rawgentic-memorypalace integration has three critical flaws:

1. **Lossy ingest.** The custom `enrichment.py` regex pipeline only indexes content matching 5 hardcoded patterns ("decided to", "found that", etc.). Reference material, architecture discussions, and most session content is silently dropped. This was demonstrated in the brainstorm session — a full server upgrade research document was lost because it lacked trigger phrases.

2. **Manual-only recall.** Memory must be explicitly searched via `/recall`. There is no automatic recall during a session. Wakeup context fires only at session start.

3. **Mid-session blind spots.** Even if recall existed, it only fires at session lifecycle events. When Claude is mid-brainstorm or mid-implementation and needs prior context, there is no mechanism to surface it.

## Design Principles

1. **Memory enhances; never blocks.** Failures in the memory system must not disrupt sessions.
2. **Mempalace owns memory; bridge owns automation.** The bridge plugin adds rawgentic-specific glue, not memory logic.
3. **Adapter contract isolates upstream changes.** A single module versions the mempalace API surface so upgrades don't require plugin rewrites.
4. **Reliability over elegance.** Two reliable processes beat one fragile process.
5. **Independent failure domains.** Each component must work standalone where possible.

## Architecture

### Critical Constraint: Single-Process ChromaDB Access

**Multi-process ChromaDB access is fundamentally unsafe.** Verified via source code analysis:
- ChromaDB uses DELETE journal mode, not WAL — readers blocked by writers
- HNSW index binary files have NO file locking — concurrent writes corrupt the index
- Index metadata serialization has no atomic write — concurrent writes produce corruption
- ChromaDB's internal `ReadWriteLock` is `threading.Condition` (intra-process only)
- Mempalace's claimed "file-level locking" is actually idempotent ID hashing (deduplication, not concurrency control)
- ChromaDB's official guidance: `PersistentClient` "not recommended for production use"; `HttpClient` is recommended

**This invalidates the original "no HTTP server" design.** The bridge MUST run as a single long-lived gatekeeper process that owns the ChromaDB client. Hooks communicate with it via HTTP (curl).

This also solves the cold-start latency problem (measured at ~3 seconds per cold subprocess vs ~100ms for warm HTTP curl).

### Three-Plugin Split

```
┌─────────────────────────────────────────────────────────────────────┐
│                       Claude Code Session                             │
│                                                                       │
│  ┌──────────────┐   ┌──────────────────┐   ┌────────────────────┐   │
│  │   rawgentic   │   │    mempalace     │   │ rawgentic-         │   │
│  │   (plugin)    │   │  (MCP server +   │   │ memorypalace       │   │
│  │              │   │   native hooks)  │   │ (bridge plugin)    │   │
│  │              │   │                  │   │                    │   │
│  │ Workflows    │   │ 19+ MCP tools    │   │ Hooks (curl HTTP): │   │
│  │ WAL/Guards   │   │ session-start    │   │  SessionStart      │   │
│  │ Sessions     │   │ stop (every 15)  │   │  UserPromptSubmit  │   │
│  │              │   │ precompact       │   │  PostToolUse       │   │
│  │              │   │ Background mining│   │                    │   │
│  │              │   │ BM25+Closets     │   │ HTTP server (~100 LOC)│
│  │              │   │ Layers (L0-L3)   │   │  GET  /healthz     │   │
│  │              │   │ Halls/KG/Tunnels │   │  GET  /diagnostic  │   │
│  │              │   │ AAAK closets     │   │  POST /search      │   │
│  │              │   │                  │   │  GET  /wakeup      │   │
│  │              │   │                  │   │  POST /fact_check  │   │
│  │              │   │                  │   │  POST /canary_write│   │
│  │              │   │                  │   │                    │   │
│  │              │   │                  │   │ Adapter (v3):      │   │
│  │              │   │                  │   │  search/wakeup/    │   │
│  │              │   │                  │   │  fact_check/health │   │
│  └──────────────┘   └──────────────────┘   └────────────────────┘   │
│         │                    │                      │                  │
│         │              MCP (Claude)                 │                  │
│         │                    │                      │                  │
│         │                    └─── stdio ────────────┤                  │
│         │                                           │                  │
│         │                                  ChromaDB Python API         │
│         │                                  (in-process, single client) │
│         │                                           │                  │
│         └── no dependency ────────────────── adapter│                  │
│                                                     ▼                  │
│                              ┌───────────────────────┐                 │
│                              │  Palace Storage       │ ◄── single      │
│                              │  ~/.mempalace/        │     writer at   │
│                              │  ChromaDB+SQLite      │     a time      │
│                              │  Owned by mempalace   │                 │
│                              └───────────────────────┘                 │
└─────────────────────────────────────────────────────────────────────┘

Process boundaries:
  P1: Claude Code session (the user)
  P2: mempalace MCP server (stdio, started by Claude Code)
  P3: rawgentic-memorypalace HTTP server (long-lived, lazy-start by hook)
  P4: mempalace mine (transient, optional via MEMPAL_DIR)

Concurrency strategy: P3 is READ-ONLY (search, wakeup, fact_check).
P2 owns ALL WRITES via Save Hook MCP tools. P4 runs only when no
session active. This serializes writes through a single process while
allowing the bridge to read concurrently.
```

### Independence Matrix

| Installed | Works? | Experience |
|---|---|---|
| rawgentic only | Yes | Full workflows, no memory |
| mempalace only | Yes | Memory via MCP, manual search, native save hooks |
| rawgentic + mempalace (no bridge) | Yes | Both work, no automation glue |
| All three | Yes | Seamless — auto-wakeup, auto-recall, fact-checking, citations |
| Bridge without mempalace | Degrades gracefully | Hooks return empty, no errors, no disruption |

## Adapter Contract

### Interface: `MempalaceAdapter v3`

```python
class MempalaceAdapter:
    """
    Stable interface between bridge and mempalace.
    Bridge code calls this adapter — never mempalace directly.
    Major version aligned with mempalace's major version.
    """

    CONTRACT_VERSION = 3       # targets mempalace 3.x API surface
    MIN_VERSION = "3.3.0"      # closets, BM25, Background Everything
    MAX_VERSION = "4.0.0"      # exclusive upper bound

    # Behavioral contract — verified at startup, not just API signatures
    BEHAVIORAL_CONTRACT = {
        "expected_mcp_tools": [
            "mempalace_search",
            "mempalace_add_drawer",
            "mempalace_diary_write",
            "mempalace_kg_query",
            "mempalace_kg_add",
            "mempalace_kg_invalidate",
        ],
        "expected_save_interval": 15,           # mempal_save_hook.sh default
        "expected_palace_dir": "~/.mempalace/palace",
        "expected_kg_path": "~/.mempalace/knowledge_graph.sqlite3",
    }

    # Note: The signatures below are the public interface contract.
    # The implementation section adds `self` and additional internal helpers.
    # Type annotations (return types, defaults) are part of the contract —
    # changes to these fields trigger CONTRACT_VERSION bumps.

    def search(
        self,
        query: str,
        project: str | None = None,
        memory_type: str | None = None,
        flag: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]: ...

    def wakeup(
        self,
        project: str | None = None,
    ) -> WakeupContext: ...

    def fact_check(self, text: str) -> list[FactIssue]: ...

    def health(self) -> HealthStatus: ...

    def verify_behavioral_contract(self) -> list[ContractViolation]:
        """Probe mempalace at startup; report missing tools or
           changed defaults. Logged as warnings, not blocking."""
```

### Return Types

```python
@dataclass
class SearchResult:
    content: str
    memory_type: str       # decision | event | discovery | preference | artifact | emotional
    topic: str
    similarity: float      # 0.0-1.0
    project: str           # mempalace wing
    timestamp: str         # ISO 8601
    source_file: str
    flag: str | None       # DECISION | TECHNICAL | PIVOT | ORIGIN | CORE | GENESIS | SENSITIVE

@dataclass
class WakeupContext:
    text: str              # Combined L0 + L1 context
    tokens: int            # Approximate token count (~600-900)
    layers: list[str]      # ["L0", "L1"]

@dataclass
class FactIssue:
    type: str              # similar_name | relationship_mismatch | stale_fact
    detail: str            # Human-readable description
    entity: str            # Subject entity name
    span: str              # Text span that triggered the issue

@dataclass
class HealthStatus:
    available: bool
    doc_count: int
    backend: str           # "mempalace"
    version: str
```

### Contract Rules

| Rule | Detail |
|---|---|
| Adapter owns translation | If mempalace renames `search()` to `query()`, the adapter maps it. Bridge code never changes. |
| Return types are stable | Fields can be added (backward compatible), never removed within a contract version. |
| Errors become empty results | Adapter catches all mempalace exceptions and returns empty/defaults. |
| Version check on import | Adapter validates installed version meets MIN_VERSION; warns if approaching MAX_VERSION. |
| Fallback chain | Python API → CLI → empty. Each layer attempted before giving up. |

### Implementation Wrappers

```python
# adapter.py — full implementation outline
from mempalace.searcher import search_memories
from mempalace.layers import Layer0, Layer1
from mempalace.fact_checker import check_text
from mempalace.config import DEFAULT_PALACE_PATH
from mempalace.version import __version__ as mempalace_version

class MempalaceAdapter:
    CONTRACT_VERSION = 3
    MIN_VERSION = "3.3.0"
    MAX_VERSION = "4.0.0"

    def __init__(self, palace_path: str = DEFAULT_PALACE_PATH):
        self.palace_path = palace_path
        self._validate_version()

    # Per-result content cap to bound additionalContext budget.
    # 3 results * 1500 chars = 4500 chars (~1100 tokens), well within
    # Claude Code's 10,000-char additionalContext limit.
    MAX_CONTENT_CHARS_PER_RESULT = 1500

    def search(self, query, project=None, memory_type=None, flag=None, limit=10):
        try:
            raw = search_memories(query, self.palace_path, wing=project, n_results=limit)
            results = [self._to_search_result(h) for h in raw.get('results', [])]
            if memory_type:
                results = [item for item in results if item.memory_type == memory_type]
            if flag:
                results = [item for item in results if item.flag == flag]
            # Truncate long drawer content to bound injection size.
            for item in results:
                if len(item.content) > self.MAX_CONTENT_CHARS_PER_RESULT:
                    item.content = item.content[:self.MAX_CONTENT_CHARS_PER_RESULT - 20] + "... [truncated]"
            return results
        except Exception as e:
            self._log_warning("search failed", e)
            return []

    def wakeup(self, project=None):
        try:
            l0 = Layer0().render()
            l1 = Layer1(palace_path=self.palace_path, wing=project).generate()
            text = f"{l0}\n\n{l1}"
            # Token count is approximate: chars/4 is a rough heuristic that
            # over-estimates for code-heavy content and under-estimates for
            # natural language with longer words. Accuracy ±25%.
            return WakeupContext(text=text, tokens=len(text)//4, layers=["L0","L1"])
        except Exception as e:
            self._log_warning("wakeup failed", e)
            return WakeupContext(text="", tokens=0, layers=[])

    def fact_check(self, text):
        try:
            issues = check_text(text, palace_path=self.palace_path)
            return [self._to_fact_issue(i) for i in issues]
        except Exception as e:
            self._log_warning("fact_check failed", e)
            return []

    def health(self):
        try:
            from mempalace.palace import get_collection
            col = get_collection(self.palace_path, create=False)
            return HealthStatus(
                available=True,
                doc_count=col.count(),
                backend="mempalace",
                version=mempalace_version
            )
        except Exception:
            return HealthStatus(available=False, doc_count=0, backend="mempalace", version="")
```

## Ingest Design

### What Gets Deleted

| Component | Lines (approx) | Reason |
|---|---|---|
| `rawgentic_memory/enrichment.py` | ~150 | Replaced by mempalace's general_extractor (110 patterns vs our 5) and Save Hook AI classification |
| `rawgentic_memory/mempalace_backend.py` | ~200 | mempalace manages its own storage |
| `rawgentic_memory/server.py` ingest path | ~120 | `/ingest` deleted; server slimmed to ~80 lines for /search /wakeup /fact_check /healthz |
| Server `/ingest` endpoint | ~40 | mempalace Save Hook handles it |
| Server `/reindex` endpoint | ~30 | mempalace CLI handles it |
| Server `/kg/*` endpoints | ~60 | mempalace MCP tools handle it |
| `rawgentic_memory/models.py` | ~80 | Types moved into adapter.py |
| `hooks/stop` (ingest portion) | ~30 | Replaced by mempalace's stop hook |
| `hooks/user-prompt-submit` (timer ingest) | ~40 | Replaced by mempalace's stop hook |
| `hooks/session-start` (PreCompact ingest) | ~20 | Replaced by mempalace's precompact hook |
| `rawgentic/hooks/notes-size-handler.py` ingest call | ~15 | mempalace handles it |

**Total deleted: ~755 lines.** The HTTP server is **kept** (slimmed from ~500 to ~80 lines) because multi-process ChromaDB access is unsafe — the server is the single-process gatekeeper.

### Critical Dependency: Ingest Reliability Depends on Claude Compliance

With the bridge no longer doing ingest, **memory population depends entirely on Claude responding to mempalace's `STOP_BLOCK_REASON` by calling MCP tools** (`mempalace_diary_write`, `mempalace_add_drawer`, `mempalace_kg_add`). If a future Claude model behavior change causes Claude to skip or under-perform these MCP calls:
- Ingest silently degrades or stops
- Recall returns empty results for new content
- The canary test catches this within one canary cycle (typically a few minutes)

Mitigations:
1. **Canary test** (continuous health signal) detects stop-of-ingest within minutes
2. **Telemetry counter** (per-session save invocations) tracked via mempalace's `hook.log`
3. **Degradation alert** surfaced to user if save count is zero across multiple sessions

This is an explicit trust boundary: the bridge trusts mempalace's hook system and Claude's MCP tool compliance. The trade-off is justified — the alternative (custom enrichment) is verifiably lossy (regex-based, drops content silently).

### What Replaces It

mempalace's native hooks + Background Everything:

```
mempalace.hooks_cli (Python module called via bash wrapper):

  hook_stop:
    - Counts human messages in transcript (skips <command-message>)
    - Every 15 messages: blocks Claude with STOP_BLOCK_REASON
    - STOP_BLOCK_REASON tells Claude to use mempalace_diary_write,
      mempalace_add_drawer, mempalace_kg_add MCP tools
    - Claude does the classification (knows context, picks right wing/hall/closet)
    - Optional: if MEMPAL_DIR is set, runs `mempalace mine` in background

  hook_precompact:
    - Always blocks with PRECOMPACT_BLOCK_REASON
    - Comprehensive save before context loss
    - If MEMPAL_DIR set, runs `mempalace mine` synchronously first

  hook_session_start:
    - Pass-through, only initializes state
    - DOES NOT inject wakeup context (left for integrators)
```

### Why This Is Better

| Aspect | Old (enrichment.py) | New (mempalace native) |
|---|---|---|
| Content coverage | 5 regex patterns | 110+ patterns + AI classification |
| Trigger phrases required | Yes (silent drop) | No |
| Configuration | Hooks, timers, thresholds | None (after install) |
| Token cost | Session notes via HTTP | Zero for hooks; Claude tokens during save |
| Deduplication | Offset-based (LRU eviction) | Content-hash based |
| Indexing | Vector only | BM25 hybrid + closets + vector |
| Content types | 5 memory types (flat) | 6 memory types + 7 halls + 7 flag types |
| Cross-project links | None | Tunnels (auto-discovered) |
| Concurrency safety | None | File-level locking |

## Recall Design

Four reinforcing layers:

### Layer 1: Wakeup Context (Guaranteed, once per session)

```
SessionStart hook fires
    │
    ▼
adapter.wakeup(project=active_project)
    │
    ▼
Returns WakeupContext (Layer0 + Layer1):
  L0: ~100 tokens — Identity from ~/.mempalace/identity.txt
  L1: ~500-800 tokens — Top-importance drawers grouped by room
    │
    ▼
Inject as additionalContext (max 10,000 chars per hook)
```

Total wakeup cost: 600-900 tokens. Fires once per session.

### Layer 2: Auto-Recall (Guaranteed, on substantive prompts)

```
UserPromptSubmit hook fires
    │
    ▼
Smart gate: should_search()?
    ├── prompt < 20 chars → skip
    ├── prompt starts with / → skip (skill invocation)
    ├── prompt matches confirmation patterns → skip
    ├── debounce: < 60s since last search → skip
    │
    └── pass → adapter.search(query=prompt, project=active_project, limit=3)
                    │
                    ▼
              Filter: similarity > 0.5
                    │
                    ▼
              Format with citation instruction
                    │
                    ▼
              Inject as additionalContext
```

Latency: ~100ms via warm HTTP server (curl). Cold Python subprocess approach was rejected after measurement showed ~3s cold start + multi-process ChromaDB unsafe (see Critical Constraint above).
Token cost: 0 for the hook itself. ~200-400 tokens for injected context when relevant.

### Layer 3: Proactive (Probabilistic, mid-reasoning)

```
Claude is mid-brainstorm/research/planning
    │
    ▼
Claude decides to search mempalace via MCP tools:
  - mempalace_search
  - mempalace_kg_query
  - mempalace_kg_timeline
  - mempalace_traverse
  - mempalace_find_tunnels
  - mempalace_check_duplicate
```

Reliability multipliers:
1. Tool descriptions encourage proactive use
2. CLAUDE.md instruction tells Claude to search during complex work
3. Workflow skills (brainstorming, implement-feature, fix-bug, refactor) bake in memory-aware steps
4. Layer 1 + Layer 2 prime the pump — Claude sees memory exists and is useful

### Layer 4: Fact-Checking (Guaranteed-with-throttle, on writes)

```
Claude calls Edit or Write tool
    │
    ▼
PostToolUse hook fires
    │
    ▼
should_check_tool() → only Edit|Write|MultiEdit
    │
    ▼
Throttle gate:
  ├── < 30s since last fact_check for this session → skip
  ├── already checked this exact file path this session → skip
  │
  └── pass through
        │
        ▼
HTTP POST /fact_check with content
        │
        ▼
Returns list[FactIssue]:
  - similar_name: typo of registered entity
  - relationship_mismatch: contradicts KG
  - stale_fact: KG marked closed in past
        │
        ▼
If issues found, inject corrections as additionalContext for next turn
```

Throttling rationale: a refactoring session touching 30 files would otherwise spawn 30 fact-check requests. Even via warm HTTP (~100ms each), cumulative latency = 3s of friction. Throttle bounds this.

Catches contradictions at the boundary where bad code becomes real damage.

## Hook Implementation

### hooks.json

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "startup|resume",
      "hooks": [{
        "type": "command",
        "command": "$CLAUDE_PLUGIN_ROOT/hooks/session-start",
        "timeout": 10
      }]
    }],
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "$CLAUDE_PLUGIN_ROOT/hooks/user-prompt-submit",
        "timeout": 5
      }]
    }],
    "PostToolUse": [{
      "matcher": "Edit|Write|MultiEdit",
      "hooks": [{
        "type": "command",
        "command": "$CLAUDE_PLUGIN_ROOT/hooks/post-tool-use",
        "timeout": 5
      }]
    }]
  }
}
```

### Hook Communication Pattern

**All hooks pipe stdin JSON directly to the HTTP server** — never shell-expand user input. This eliminates shell quoting injection (user prompts containing `"`, `` ` ``, `$(...)`, or newlines cannot become commands).

The HTTP server parses the JSON, extracts what it needs, and returns response JSON for the hook to emit.

### hooks/session-start (NEW, ~25 lines)

```bash
#!/bin/bash
# SessionStart — wakeup context injection (Layer 0 + Layer 1)
source "$(dirname "$0")/lib.sh"

ensure_server_running || exit 0
PROJECT=$(resolve_project)

# GET /wakeup?project=<project> — server reads palace, returns L0+L1
RESPONSE=$(curl -sS --max-time 8 "http://127.0.0.1:8420/wakeup?project=$(jq -rn --arg p "$PROJECT" '$p|@uri')" 2>/dev/null)
[[ -z "$RESPONSE" ]] && exit 0

# Server returns: {"text": "...", "tokens": N}
TEXT=$(echo "$RESPONSE" | jq -r '.text // empty')
[[ -z "$TEXT" ]] && exit 0

# Build hookSpecificOutput. Use jq to safely encode text as JSON string.
echo "$RESPONSE" | jq '{
  hookSpecificOutput: {
    hookEventName: "SessionStart",
    additionalContext: .text
  }
}'
exit 0
```

### hooks/user-prompt-submit (NEW, ~35 lines)

```bash
#!/bin/bash
# UserPromptSubmit — smart-gated auto-recall (Layer 2)
# Pipes stdin JSON directly to server — NO shell expansion of user input.
source "$(dirname "$0")/lib.sh"

# Cache stdin to a variable for both gating and forwarding
HOOK_INPUT=$(cat)
PROMPT=$(echo "$HOOK_INPUT" | jq -r '.prompt // empty')
PROJECT=$(resolve_project)

# Smart gate (length, slash, confirmation patterns, debounce)
should_search "$PROMPT" "$PROJECT" || exit 0

# Health check only — DO NOT attempt server startup here.
# Startup polling can take 10s, exceeding our 5s hook timeout.
# If server isn't running, exit cleanly; session-start will start it next session.
server_is_healthy || exit 0

# POST /search with full hook input as body. Server extracts prompt,
# searches mempalace, filters by similarity > 0.5, returns:
#   {"additionalContext": "..."}  if hits found
#   {}                             if no hits
RESPONSE=$(echo "$HOOK_INPUT" | curl -sS --max-time 4 \
    -H "Content-Type: application/json" \
    --data-binary @- \
    "http://127.0.0.1:8420/search?project=$(jq -rn --arg p "$PROJECT" '$p|@uri')&min_similarity=$RECALL_SIMILARITY_THRESHOLD&limit=$RECALL_MAX_RESULTS" 2>/dev/null)

[[ -z "$RESPONSE" ]] && exit 0
CONTEXT=$(echo "$RESPONSE" | jq -r '.additionalContext // empty')
[[ -z "$CONTEXT" ]] && exit 0

date +%s > "$STATE_DIR/last-recall-ts-$PROJECT"

echo "$RESPONSE" | jq '{
  hookSpecificOutput: {
    hookEventName: "UserPromptSubmit",
    additionalContext: .additionalContext
  }
}'
exit 0
```

### hooks/post-tool-use (NEW, ~35 lines)

```bash
#!/bin/bash
# PostToolUse — fact-checking on writes (Layer 4)
# Throttled to bound cumulative latency in refactoring sessions.
source "$(dirname "$0")/lib.sh"

HOOK_INPUT=$(cat)
TOOL=$(echo "$HOOK_INPUT" | jq -r '.tool_name // empty')
[[ "$TOOL" =~ ^(Edit|Write|MultiEdit)$ ]] || exit 0

# Throttle: 30s window + per-file-path dedup within session
FILE_PATH=$(echo "$HOOK_INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')
should_fact_check "$FILE_PATH" || exit 0

# Health check only — DO NOT attempt server startup here (5s timeout budget).
server_is_healthy || exit 0

# POST /fact_check with full hook input as body. Server extracts content,
# runs fact_checker, returns:
#   {"additionalContext": "..."}  if issues found
#   {}                             if clean
RESPONSE=$(echo "$HOOK_INPUT" | curl -sS --max-time 4 \
    -H "Content-Type: application/json" \
    --data-binary @- \
    "http://127.0.0.1:8420/fact_check" 2>/dev/null)

[[ -z "$RESPONSE" ]] && exit 0
CONTEXT=$(echo "$RESPONSE" | jq -r '.additionalContext // empty')
[[ -z "$CONTEXT" ]] && exit 0

date +%s > "$STATE_DIR/last-fact-check-ts"
echo "$FILE_PATH" >> "$STATE_DIR/fact-check-paths-$CLAUDE_SESSION_ID"

echo "$RESPONSE" | jq '{
  hookSpecificOutput: {
    hookEventName: "PostToolUse",
    additionalContext: .additionalContext
  }
}'
exit 0
```

### hooks/lib.sh (~100 lines)

Key functions:

```bash
# Cheap health check (no startup) — for hooks with tight timeout budgets.
# Returns 0 if server is responsive, 1 otherwise. Never blocks > 1s.
server_is_healthy() {
    local url="${MEMORY_SERVER_URL:-http://127.0.0.1:8420}"
    curl -sS --max-time 1 "$url/healthz" >/dev/null 2>&1
}

# Lazy-start the HTTP server if not running. Idempotent.
# ONLY safe to call from session-start hook (10s timeout budget).
# UserPromptSubmit and PostToolUse hooks (5s timeout) MUST use
# server_is_healthy() instead — startup polling can take up to 10s.
ensure_server_running() {
    server_is_healthy && return 0
    [[ "${MEMORY_NO_AUTOSTART:-0}" == "1" ]] && return 1

    local url="${MEMORY_SERVER_URL:-http://127.0.0.1:8420}"
    local port=$(echo "$url" | grep -oE ':[0-9]+(/|$)' | grep -oE '[0-9]+' | head -1)
    [[ -z "$port" ]] && port=8420
    local lockfile="/tmp/memorypalace-start.lock"
    (
        flock -n 9 || exit 0
        "$PLUGIN_VENV/bin/python3" -m rawgentic_memory.server \
            --port "$port" --timeout 14400 \
            >> /tmp/memorypalace-server.log 2>&1 &
        disown
    ) 9>"$lockfile"

    # Poll healthz for up to 10 seconds
    for i in $(seq 1 20); do
        sleep 0.5
        server_is_healthy && return 0
    done
    return 1
}

# All tunable thresholds — overridable via environment variables.
# Defaults are intentionally conservative; tune in production based on metrics.
RECALL_MIN_PROMPT_CHARS="${RECALL_MIN_PROMPT_CHARS:-20}"
RECALL_DEBOUNCE_SECS="${RECALL_DEBOUNCE_SECS:-60}"
RECALL_SIMILARITY_THRESHOLD="${RECALL_SIMILARITY_THRESHOLD:-0.5}"
FACT_CHECK_DEBOUNCE_SECS="${FACT_CHECK_DEBOUNCE_SECS:-30}"
RECALL_MAX_RESULTS="${RECALL_MAX_RESULTS:-3}"

# Smart gate for UserPromptSubmit. Operates on $PROMPT, never shell-expands it.
should_search() {
    local prompt="$1" project="$2"
    [[ ${#prompt} -lt $RECALL_MIN_PROMPT_CHARS ]] && return 1
    [[ "$prompt" == /* ]] && return 1
    # Case-insensitive match for confirmation patterns (bash 4+ ${var,,}).
    local lower_prompt="${prompt,,}"
    [[ "$lower_prompt" =~ ^(commit|push|yes|no|y|n|ok|done|next|looks[[:space:]]good|lgtm|sgtm|sounds[[:space:]]good|do[[:space:]]it|go|continue)$ ]] && return 1
    local now=$(date +%s)
    local last=$(cat "$STATE_DIR/last-recall-ts-$project" 2>/dev/null || echo 0)
    [[ $((now - last)) -lt $RECALL_DEBOUNCE_SECS ]] && return 1
    return 0
}

# Throttle gate for PostToolUse fact-check.
# 30s window + per-file-path dedup within session.
should_fact_check() {
    local file_path="$1"
    local now=$(date +%s)
    local last=$(cat "$STATE_DIR/last-fact-check-ts" 2>/dev/null || echo 0)
    [[ $((now - last)) -lt $FACT_CHECK_DEBOUNCE_SECS ]] && return 1

    # Per-file dedup — never fact-check the same file twice in a session
    local session_paths_file="$STATE_DIR/fact-check-paths-$CLAUDE_SESSION_ID"
    if [[ -f "$session_paths_file" ]] && grep -Fxq "$file_path" "$session_paths_file" 2>/dev/null; then
        return 1
    fi
    return 0
}

# Read active rawgentic project from workspace + session registry.
resolve_project() {
    local registry="$WORKSPACE_ROOT/claude_docs/session_registry.jsonl"
    if [[ -f "$registry" && -n "${CLAUDE_SESSION_ID:-}" ]]; then
        local proj=$(grep -F "\"$CLAUDE_SESSION_ID\"" "$registry" 2>/dev/null \
            | tail -1 | jq -r '.project // empty' 2>/dev/null)
        [[ -n "$proj" ]] && { echo "$proj"; return; }
    fi
    # Fallback: most recently used active project
    jq -r '[.projects[] | select(.active==true)] | sort_by(.lastUsed) | last | .name // empty' \
        "$WORKSPACE_ROOT/.rawgentic_workspace.json" 2>/dev/null
}
```

**Critical security property:** Functions accept the prompt/path as `$1`. The hook scripts use `[[ ${#prompt} -lt 20 ]]` and pattern matching that does NOT eval the string. The prompt is never passed to a subshell or `eval`. The actual prompt content goes from stdin → curl `--data-binary @-` → server, never through a shell command line.

## Migration Path

### Phase 0: Onboarding & Identity (Day 1, ~30 min)

```bash
# 1. Backup palace
cp -r ~/.mempalace ~/.mempalace.backup

# 2. Run mempalace onboarding (interactive or automated)
mempalace init  # Asks mode, people, projects, wings

# 3. Generate identity file from rawgentic workspace
cat > ~/.mempalace/identity.txt <<EOF
I am working with [User], a developer for 3D-Stories.
Active projects: $(jq -r '[.projects[] | select(.active) | .name] | join(", ")' ~/rawgentic/.rawgentic_workspace.json)
Preferences: TDD always, conventional commits, never push to main without PR.
Memory server runs on 10.0.17.205:8420.
EOF

# 4. Set MEMPAL_DIR for background mining
echo 'export MEMPAL_DIR=~/rawgentic/claude_docs/session_notes/' >> ~/.bashrc
```

### Phase 1: Upgrade Mempalace (Day 1, ~10 min)

```bash
cd ~/rawgentic/projects/rawgentic-memorypalace

# Update pyproject.toml: mempalace>=3.3.0,<4.0
.venv/bin/pip install --upgrade "mempalace>=3.3.0,<4.0"

# Run mempalace migration if ChromaDB version changed
.venv/bin/mempalace migrate
```

**Validation:** Existing memories still searchable via current HTTP server.

### Phase 1.5: Bulk-Mine Existing Context (Day 1, ~30 min)

```bash
# Mine workspace-wide session notes
mempalace mine ~/rawgentic/claude_docs/session_notes/ --mode general

# Per-project context
for project in ~/rawgentic/projects/*/; do
    name=$(basename "$project")
    [[ -d "$project/docs" ]] && mempalace mine "$project/docs" --wing "$name"
    [[ -f "$project/CLAUDE.md" ]] && mempalace mine "$project/CLAUDE.md" --wing "$name"
done

# Verify
mempalace status
mempalace search "EPYC server upgrade" --wing sysop
```

**Validation:** Palace has retroactive depth — past context immediately accessible.

### Phase 2: Build Adapter Module (Day 2, ~4 hours) — REORDERED

Create `rawgentic_memory/adapter.py`:
- `MempalaceAdapter` class with versioning + behavioral contract
- All four methods (`search`, `wakeup`, `fact_check`, `health`)
- `verify_behavioral_contract()` startup probe
- Error handling — no exceptions leak
- Unit tests against mempalace 3.3.0 (see Test Coverage section)

**Validation:** `python -m rawgentic_memory.adapter health` returns valid JSON; behavioral contract probe passes against installed mempalace.

### Phase 3: Trim HTTP Server (Day 2, ~3 hours) — REORDERED

Reduce `rawgentic_memory/server.py` from ~500 lines to ~100:
- Keep `GET /healthz`, `GET /wakeup`, `POST /search`, `POST /fact_check`
- **Add `GET /diagnostic`** — reports health of all components (HTTP server, mempalace MCP availability, palace doc count, last save timestamp, canary status). Output is JSON consumable by both humans and monitoring tools.
- **Add `POST /canary_write`** — test-only endpoint for canary; writes to `canary` wing only via single-process mempalace API. Rejects writes to other wings.
- Remove `POST /ingest`, `POST /reindex`, `GET /kg/*`
- All endpoints route through `adapter.py`
- Lazy-start + idle shutdown unchanged
- Server is READ-ONLY for non-canary content (writes go through mempalace MCP)

**Validation:** All endpoints respond correctly. `/ingest` returns 410 Gone (deleted). `/diagnostic` reports component health.

### Phase 4: Build New Bridge Hooks (Day 2, ~3 hours) — REORDERED

Build (don't install yet):
- `hooks/session-start` (~25 lines, curl /wakeup)
- `hooks/user-prompt-submit` (~35 lines, smart-gate + curl /search)
- `hooks/post-tool-use` (~35 lines, throttled + curl /fact_check)
- `hooks/lib.sh` (~100 lines)

Test offline against running HTTP server. No production hook impact yet.

**Validation:** All three new hooks emit valid JSON to stdout matching Claude hook protocol.

### Phase 5: ATOMIC CUTOVER (Day 3, ~30 min) — REORDERED & UNIFIED

This is a single atomic step. Do NOT execute partially.

```bash
# 1. Stop old HTTP server if running as systemd service
systemctl --user stop rawgentic-memorypalace.service 2>/dev/null
systemctl --user disable rawgentic-memorypalace.service 2>/dev/null
# Or kill the process if managed differently
pkill -f 'rawgentic_memory.server' || true

# 2. Install new hooks atomically via single hooks.json update
cp hooks/hooks.json.new hooks/hooks.json

# 3. Install mempalace native hooks (~/.claude/settings.json)
# (Manual edit or scripted)

# 4. Register mempalace MCP server
claude mcp add mempalace -- python -m mempalace.mcp_server

# 5. Verify canary test passes (see Test Coverage section)
.venv/bin/python -m rawgentic_memory.tests.canary
```

**Validation:** Canary test (write known fact → search → assert recall) passes within 60 seconds of cutover. All four bridge HTTP endpoints respond. mempalace MCP tools accessible to Claude.

**Rollback:** Revert hooks/hooks.json from git, remove mempalace native hooks from `~/.claude/settings.json`, restart old systemd service. Total rollback time: < 2 minutes.

### Phase 6: Delete Old Infrastructure (Day 3, ~1 hour)

After Phase 5 verified successful and observed for at least one full session:

```bash
git rm rawgentic_memory/mempalace_backend.py
git rm rawgentic_memory/enrichment.py
git rm rawgentic_memory/models.py  # most types move to adapter.py
# Keep: __init__.py, adapter.py, server.py (slimmed in Phase 3)
```

Update `pyproject.toml`:
- Keep `fastapi`, `uvicorn` dependencies (server still needed)
- Keep `mempalace>=3.3.0,<4.0`

**Validation:** Plugin still works after deletion. No imports of deleted modules anywhere.

### Phase 7: Update Skill Instructions (Day 3, ~2 hours)

Update rawgentic workflow skills to include memory-aware steps:

| Skill | New Step |
|---|---|
| `brainstorming` | "Step 1: Search mempalace for prior decisions on related topics" |
| `implement-feature` | "Step 2: Search mempalace for known gotchas and architecture context" |
| `fix-bug` | "Step 1: Search mempalace for related bug history" |
| `refactor` | "Step 1: Search mempalace for prior decisions about this area" |

**Validation:** Layer 3 reliability improves — Claude proactively searches in workflows.

### Phase 8: Documentation (Day 3, ~2 hours)

Add to project CLAUDE.md:

```markdown
## Memory

When doing complex work (brainstorming, architecture, debugging, research),
search mempalace for relevant prior decisions and context before proposing
approaches. Your memories contain decisions, discoveries, and preferences
from previous sessions that should inform current work.
```

Update plugin README with:
- New three-plugin architecture diagram
- Adapter contract documentation
- Hook lifecycle explanation
- Migration guide for existing users

### Operational Hygiene (Ongoing)

Add to a periodic cron or manual checklist:

```bash
# Weekly: dedup near-duplicates
mempalace dedup --threshold 0.15

# Monthly: full status review
mempalace status

# As needed: update identity file when projects change
```

## Risk Matrix

| Risk | Likelihood | Mitigation |
|---|---|---|
| Multi-process ChromaDB corruption | **Low** (residual risk: stale HNSW reads during write) | HTTP server gatekeeper (READ-only) + mempalace MCP owns writes; verified via integration test. Residual: HNSW binary index has no file locking — concurrent reads during HNSW rebuild could return stale (not corrupt) results. Practical impact minimal since writes are brief (~ms) and infrequent (every 15 messages). |
| Mempalace 3.3.0 breaking change in `search_memories()` API | Low | Adapter isolates; pin specific version if needed |
| Native save hook conflicts with rawgentic Stop hook | Medium | Test together; mempalace uses `stop_hook_active` flag; Stop hooks run in parallel (verified) |
| MCP tool registration fails | Low | Standard MCP pattern; fall back to hooks-only |
| ChromaDB migration corrupts data | Low | Backup palace dir before Phase 1; mempalace migrate is well-tested |
| Cold-start Python latency too high | **Eliminated** | HTTP server stays warm; ~100ms hook latency confirmed |
| Claude doesn't follow proactive search instructions | High | Layer 1+2 hook injection primes the pump; Layer 4 catches contradictions; skill instructions bake in proactive search |
| Mempalace 4.0 breaks adapter contract | Low | Adapter major-version aligned; write v4 adapter when 4.0 ships |
| Mempalace 3.4 changes MCP tool names | Medium | `verify_behavioral_contract()` startup probe detects and warns |
| Silent ingest failure (data loss) | Medium | Canary test runs continuously; surfaces failures to user immediately |
| Bash hook shell injection from user prompts | **Eliminated** | All user content piped via stdin → `curl --data-binary @-`; never shell-expanded |
| PostToolUse fact-check creates edit-loop friction | Medium | 30s debounce + per-file dedup throttling |
| Phase ordering creates intermediate broken state | **Eliminated** | Phases reordered; Phase 5 is single atomic cutover |

## Rollback Plan

| Phase | Rollback |
|---|---|
| 0 (Onboarding) | `rm -rf ~/.mempalace; mv ~/.mempalace.backup ~/.mempalace` |
| 1 (Upgrade) | Pin back to 3.0.0 in pyproject.toml; reinstall |
| 1.5 (Bulk mine) | Drop wings via `mempalace` CLI or restore backup |
| 2 (Adapter) | Revert via git — adapter not yet wired into anything |
| 3 (HTTP server trim) | Revert via git; restart old server |
| 4 (Build hooks) | Revert via git — hooks not yet installed |
| **5 (ATOMIC CUTOVER)** | **Revert hooks/hooks.json from git; remove mempalace native hooks from `~/.claude/settings.json`; `claude mcp remove mempalace`; restart old systemd service. Total: < 2 minutes.** |
| 6 (Delete old) | Revert via git |
| 7 (Skills) | Revert via git |
| 8 (Docs) | Revert via git |

Memories are safe throughout — palace storage location is unchanged.

## Test Coverage

Testing is non-negotiable. The system handles memory critical to the agentic coding process — silent failures cause weeks-of-context loss before discovery.

### Unit Tests (CI-blocking)

**`adapter.py` test matrix:**

| Test | Asserts |
|---|---|
| `test_search_returns_empty_when_mempalace_missing` | Adapter returns `[]` when `import mempalace` fails |
| `test_search_filters_by_memory_type` | Only matching memory types in result |
| `test_search_filters_by_flag` | Only matching flags in result |
| `test_search_no_exception_on_chromadb_error` | Error → empty result, never raise |
| `test_wakeup_returns_empty_context_on_exception` | `WakeupContext(text="", tokens=0, layers=[])` on failure |
| `test_wakeup_includes_l0_and_l1` | Successful return has both layers |
| `test_fact_check_maps_upstream_format` | Mempalace `check_text()` output → `FactIssue[]` |
| `test_fact_check_returns_empty_for_clean_text` | No issues → `[]`, not None |
| `test_health_returns_unavailable_when_collection_missing` | `HealthStatus(available=False)` |
| `test_version_validation_rejects_below_min` | < 3.3.0 logs warning |
| `test_version_validation_rejects_above_max` | >= 4.0.0 logs warning |
| `test_behavioral_contract_detects_missing_mcp_tool` | Returns `ContractViolation[]` if expected tool absent |

**`server.py` test matrix:**

| Test | Asserts |
|---|---|
| `test_healthz_returns_200_when_mempalace_available` | Standard health probe |
| `test_search_endpoint_returns_additionalContext_format` | Response shape matches hook expectation |
| `test_search_filters_by_min_similarity` | Below threshold → empty |
| `test_wakeup_endpoint_includes_token_count` | Response has `text`, `tokens`, `layers` |
| `test_fact_check_endpoint_returns_empty_when_clean` | No issues → `{}` |
| `test_ingest_endpoint_returns_410` | Removed endpoint returns 410 Gone |

**`lib.sh` test matrix (bash test framework — bats or similar):**

| Test | Asserts |
|---|---|
| `test_should_search_skips_short_prompt` | `< 20 chars` returns 1 |
| `test_should_search_skips_slash_command` | `/foo` returns 1 |
| `test_should_search_skips_confirmation` | `yes`, `lgtm`, etc. return 1 |
| `test_should_search_respects_debounce` | `< 60s` since last → returns 1 |
| `test_should_fact_check_respects_per_file_dedup` | Same path twice → second returns 1 |
| `test_resolve_project_walks_up_to_workspace_root` | Works from project sub-directory |
| `test_resolve_project_uses_session_registry_first` | Registry hit overrides lastUsed |

### Integration Tests (CI-blocking)

**Five non-negotiable integration tests:**

1. **End-to-end canary test** — write known fact via Save Hook MCP simulation, verify recall via adapter
2. **Concurrent write protection** — two processes attempt simultaneous writes, assert no corruption
3. **Graceful degradation** — uninstall mempalace, run all hooks, assert empty responses + zero errors + session unblocked
4. **Hook timeout compliance** — all three hooks complete within declared timeouts (10s, 5s, 5s) under cold-start conditions
5. **Adapter version boundary** — install mempalace 3.2.x and 4.0.x test versions, assert appropriate warnings

### Canary Test (Continuous Health Signal)

This runs in CI AND as a runtime health check:

```python
# tests/canary.py
# CRITICAL: Canary writes go through the HTTP server (single writer).
# Direct ChromaDB writes from a separate process violate the single-process
# gatekeeper architecture and could corrupt the palace.
import json
import time
import fcntl
import os
import requests

CANARY_FACT = f"CANARY_{int(time.time())}: blue elephants prefer Tuesdays"
CANARY_LOCK = "/tmp/memorypalace-canary.lock"
SERVER_URL = os.environ.get("MEMORY_SERVER_URL", "http://127.0.0.1:8420")

def acquire_canary_lock():
    """Prevent canary from running concurrently with active sessions.
    The HTTP server holds an inverse lock when serving live traffic;
    this lock guarantees serialized canary execution."""
    lock_fd = open(CANARY_LOCK, 'w')
    try:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_fd
    except BlockingIOError:
        print("CANARY SKIP — another canary is running")
        exit(0)

def write_canary():
    """Write canary via HTTP server (single-writer-safe)."""
    r = requests.post(f"{SERVER_URL}/canary_write",
        json={"fact": CANARY_FACT, "wing": "canary"},
        timeout=8)
    r.raise_for_status()

def verify_canary_recall(timeout=30):
    """Search for canary, assert it's findable."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.post(f"{SERVER_URL}/search",
            json={"prompt": "blue elephants Tuesday"},
            params={"min_similarity": 0.3, "limit": 5},
            timeout=4)
        results = r.json().get("results", [])
        if any(CANARY_FACT in res["content"] for res in results):
            return True
        time.sleep(2)
    return False

if __name__ == "__main__":
    lock = acquire_canary_lock()
    try:
        write_canary()
        if verify_canary_recall():
            print("CANARY PASS")
            exit(0)
        else:
            print("CANARY FAIL — memory pipeline broken")
            exit(1)
    finally:
        lock.close()
        os.unlink(CANARY_LOCK)
```

The HTTP server exposes a `POST /canary_write` test-only endpoint that writes via mempalace's MCP tool simulation, preserving the single-writer guarantee. The endpoint is gated to only accept writes to the `canary` wing.

Run after every save hook trigger in production. Surface failures to user immediately.

### Test Infrastructure

- **Mock mempalace imports** — `conftest.py` fixtures using `unittest.mock` to simulate mempalace API at version boundaries
- **Process-isolated ChromaDB** — each test gets its own temp palace via `tmp_path` fixture
- **Pin embeddings** — use deterministic embedding model in tests to avoid borderline similarity flips
- **Mock the clock** — `freezegun` or similar for debounce testing
- **No real mempalace process** — bash hook tests stub `curl` to return canned responses

### Flaky Test Patterns to Avoid

| Pattern | Mitigation |
|---|---|
| Time-dependent debounce | Mock `date +%s` via wrapper |
| Embedding-dependent thresholds | Pin embedding model + fixture data |
| Cold-start latency assertions | Don't assert wall-clock latency in CI; use trace counters |
| Concurrent write tests | Use synchronization primitives (latch) to force timing, not `sleep` |

## Success Criteria

### Acceptance Criteria (CI-blocking)

These MUST pass before merge:

1. **Server upgrade research recall** — content from this brainstorm is searchable in mempalace within 24 hours of implementation (canary-style validation)
2. **Wakeup latency** — wakeup context injects within 500ms of session start (warm HTTP server)
3. **Code reduction** — total bridge plugin code is ≤ 350 lines (adjusted from 250 since HTTP server stays)
4. **Canary test passes** in CI on every commit
5. **Concurrent write test passes** — two processes can attempt simultaneous palace access without corruption
6. **Graceful degradation passes** — uninstalling mempalace doesn't break sessions

### Operational Metrics (Post-Deploy, Not CI)

These are tracked via instrumentation, not CI:

7. **Auto-recall fire rate** — fires on > 80% of substantive prompts (instrumented via per-layer counters)
8. **Layer 3 proactive usage** — Claude calls MCP tools 5+ times per session (telemetry, not enforceable)
9. **Fact-checking catches** — at least one contradiction per week of active development (rate, not deterministic)

### Conditional (Future)

These are testable only when those versions ship:

10. **Mempalace 3.4.x compatibility** — adapter requires zero code changes
11. **Mempalace 4.0 migration** — requires < 200 lines of adapter changes only

## Stop Hook Timing (Verified Behavior)

Verified via Claude Code documentation research:

- Stop hook fires **after all tool calls in the turn complete** — does NOT interrupt mid-tool-use ✓
- Long tool calls (3-min test suites) cause timing skew — message count overshoots before save fires
- `decision: "block"` forces Claude to take another turn responding to the reason
- Multiple Stop hooks (e.g., rawgentic WAL + mempalace save) run **in parallel** — order not guaranteed
- `stop_hook_active` flag prevents loops on consecutive blocks

**User-facing impact:** Every 15 messages, Claude pauses ~2-5 seconds to file memories via MCP tools. In a 60-message session, that's ~4 forced pauses. Document this behavior. Expose `SAVE_INTERVAL` (mempalace already supports this in `mempal_save_hook.sh`) so users can tune.

## Out of Scope (v2 Considerations)

- Cross-wing tunnel-aware recall (search related projects when current project has thin matches)
- LLM-based closet generation via `closet_llm.py`
- Query expansion / intent extraction for Layer 2 (mempalace's BM25 + closet layer covers ~80% of cases; defer until operational metrics show insufficient recall)
- Memory pruning / importance decay for scale (>50k entries)
- MCP resource exposure when Claude Code adds support
- Multi-user palace isolation (currently single-user)
- Encrypted palace storage
- ~~Tunable smart-gate thresholds via config~~ — **moved to v1**: env vars `RECALL_MIN_PROMPT_CHARS`, `RECALL_DEBOUNCE_SECS`, `RECALL_SIMILARITY_THRESHOLD`, `FACT_CHECK_DEBOUNCE_SECS`, `RECALL_MAX_RESULTS` are configurable from day one

## Troubleshooting

The system has 3+ processes (Claude session, mempalace MCP, bridge HTTP server) plus optional `mempalace mine` background runs. When something goes wrong, the diagnostic flow:

### Symptom: No memory context appearing at session start

1. Check bridge server health: `curl http://127.0.0.1:8420/diagnostic | jq`
2. Check session-start hook ran: `grep "SESSION START" ~/.mempalace/hook_state/hook.log`
3. Check wakeup endpoint returns content: `curl 'http://127.0.0.1:8420/wakeup?project=PROJECT'`
4. If `text` is empty, palace may be empty: `mempalace status`
5. Verify identity file exists: `cat ~/.mempalace/identity.txt`

### Symptom: Auto-recall not firing on substantive prompts

1. Check hook is configured: `cat ~/.claude/settings.json | jq '.hooks.UserPromptSubmit'`
2. Check smart-gate isn't blocking — log debug to stderr
3. Check debounce: `cat $STATE_DIR/last-recall-ts-PROJECT` (subtract from `date +%s`)
4. Lower similarity threshold temporarily: `RECALL_SIMILARITY_THRESHOLD=0.3 claude ...`

### Symptom: Memory not being saved (Save Hook silent)

1. Check mempalace's hook log: `tail -50 ~/.mempalace/hook_state/hook.log`
2. Check Claude is responding to STOP_BLOCK_REASON: look for `mempalace_diary_write` or `mempalace_add_drawer` calls in transcript
3. Run canary: `python -m tests.canary` — if PASS, recall pipeline works but ingest is broken; if FAIL, both broken
4. Verify mempalace MCP is registered: `claude mcp list | grep mempalace`

### Symptom: Hooks timing out

1. Check server is healthy: `curl --max-time 1 http://127.0.0.1:8420/healthz`
2. If server not running and you're hitting `user-prompt-submit` — that hook intentionally does NOT start the server. Send a new prompt or restart Claude to trigger session-start lazy-start.
3. Check for stuck mempalace process: `ps aux | grep mempalace`

### Symptom: ChromaDB errors in server log

1. Check `tail -100 /tmp/memorypalace-server.log`
2. If "database is locked" — concurrent write conflict; should auto-retry, but check for runaway `mempalace mine` process
3. If "no such collection" — palace was reset; re-run Phase 1.5 (bulk mine)
4. Run `mempalace migrate` if schema versions don't match

### Quick Health Check Command

```bash
# One-shot health probe — exits 0 if all green, 1 with details if not
curl -sS http://127.0.0.1:8420/diagnostic | jq -e '
  .components.server.healthy and
  .components.mempalace.available and
  .components.palace.doc_count > 0 and
  (.components.last_save_minutes_ago // 9999) < 60
' || echo "DEGRADED — see /diagnostic for details"
```

## References

- mempalace v3.3.0 release: https://github.com/MemPalace/mempalace/releases/tag/v3.3.0
- mempalace hooks documentation: https://mempalaceofficial.com/guide/hooks.html
- mempalace source (develop): https://github.com/MemPalace/mempalace/tree/develop/mempalace
- Key files reviewed: `searcher.py`, `layers.py`, `fact_checker.py`, `general_extractor.py`, `hooks_cli.py`, `palace.py`, `palace_graph.py`, `dialect.py`, `dedup.py`, `onboarding.py`
- Claude Code hooks reference: hook protocol with stdin JSON, additionalContext (10k chars), exit codes (0=success, 2=blocking)
