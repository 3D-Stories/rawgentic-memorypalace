# MemPalace Integration Redesign

**Date:** 2026-04-14
**Status:** Design — Pending Implementation
**Author:** Brainstorm session with Claude

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
│  │ Workflows    │   │ 19+ MCP tools    │   │ Hooks:             │   │
│  │ WAL/Guards   │   │ session-start    │   │  SessionStart      │   │
│  │ Sessions     │   │ stop (every 15)  │   │  UserPromptSubmit  │   │
│  │              │   │ precompact       │   │  PostToolUse       │   │
│  │              │   │ Background mining│   │                    │   │
│  │              │   │ BM25+Closets     │   │ Adapter (v3):      │   │
│  │              │   │ Layers (L0-L3)   │   │  search()          │   │
│  │              │   │ Halls/KG/Tunnels │   │  wakeup()          │   │
│  │              │   │ Multi-agent safe │   │  fact_check()      │   │
│  │              │   │ AAAK closets     │   │  health()          │   │
│  └──────────────┘   └──────────────────┘   └────────────────────┘   │
│         │                    ▲                      │                  │
│         │                    │                      │                  │
│         │           Direct Python API               │                  │
│         │           (in-process, no HTTP)           │                  │
│         │                    │                      │                  │
│         └── no dependency ───┴──── adapter ─────────┘                  │
│                                                                       │
│                              ┌───────────────────┐                    │
│                              │  Palace Storage    │                    │
│                              │  ~/.mempalace/     │                    │
│                              │  ChromaDB+SQLite   │                    │
│                              │  Owned by mempalace│                    │
│                              └───────────────────┘                    │
└─────────────────────────────────────────────────────────────────────┘
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

    def search(
        query: str,
        project: str | None = None,
        memory_type: str | None = None,
        flag: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]

    def wakeup(
        project: str | None = None
    ) -> WakeupContext

    def fact_check(
        text: str
    ) -> list[FactIssue]

    def health() -> HealthStatus
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

    def search(self, query, project=None, memory_type=None, flag=None, limit=10):
        try:
            r = search_memories(query, self.palace_path, wing=project, n_results=limit)
            results = [self._to_search_result(h) for h in r.get('results', [])]
            if memory_type:
                results = [r for r in results if r.memory_type == memory_type]
            if flag:
                results = [r for r in results if r.flag == flag]
            return results
        except Exception as e:
            self._log_warning("search failed", e)
            return []

    def wakeup(self, project=None):
        try:
            l0 = Layer0().render()
            l1 = Layer1(palace_path=self.palace_path, wing=project).generate()
            text = f"{l0}\n\n{l1}"
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
| `rawgentic_memory/server.py` | ~300 | No HTTP server needed — direct Python calls from hooks |
| Server `/ingest` endpoint | (in server.py) | mempalace Save Hook handles it |
| Server `/reindex` endpoint | (in server.py) | mempalace CLI handles it |
| Server `/kg/*` endpoints | (in server.py) | mempalace MCP tools handle it |
| `hooks/stop` (ingest portion) | ~30 | Replaced by mempalace's stop hook |
| `hooks/user-prompt-submit` (timer ingest) | ~40 | Replaced by mempalace's stop hook |
| `hooks/session-start` (PreCompact ingest) | ~20 | Replaced by mempalace's precompact hook |
| `rawgentic/hooks/notes-size-handler.py` ingest call | ~15 | mempalace handles it |

**Total deleted: ~755 lines.**

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

Latency: ~200-400ms for cold Python subprocess, ~100ms warm (OS cache).
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

### Layer 4: Fact-Checking (Guaranteed, on writes)

```
Claude calls Edit or Write tool
    │
    ▼
PostToolUse hook fires
    │
    ▼
should_check_tool() → only Edit/Write
    │
    ▼
adapter.fact_check(content_being_written)
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

### hooks/session-start (NEW, ~30 lines)

```bash
#!/bin/bash
# SessionStart — wakeup context injection (Layer 0 + Layer 1)
source "$(dirname "$0")/lib.sh"
read_hook_input

PROJECT=$(resolve_project)
CONTEXT=$(call_adapter wakeup "$PROJECT")
[[ -z "$CONTEXT" ]] && exit 0

echo "{\"hookSpecificOutput\":{\"hookEventName\":\"SessionStart\",\"additionalContext\":$CONTEXT}}"
exit 0
```

### hooks/user-prompt-submit (NEW, ~40 lines)

```bash
#!/bin/bash
# UserPromptSubmit — smart-gated auto-recall (Layer 2)
source "$(dirname "$0")/lib.sh"
read_hook_input

PROMPT=$(echo "$HOOK_INPUT" | jq -r '.prompt // empty')
PROJECT=$(resolve_project)

should_search "$PROMPT" "$PROJECT" || exit 0

RESULTS=$(call_adapter search "$PROMPT" "$PROJECT" 3)
[[ -z "$RESULTS" ]] && exit 0

# Filter by similarity threshold
RELEVANT=$(echo "$RESULTS" | jq '[.[] | select(.similarity > 0.5)]')
[[ "$(echo "$RELEVANT" | jq 'length')" -eq 0 ]] && exit 0

CONTEXT=$(format_memory_context "$RELEVANT")
date +%s > "$STATE_DIR/last-recall-ts-$PROJECT"

echo "{\"hookSpecificOutput\":{\"hookEventName\":\"UserPromptSubmit\",\"additionalContext\":$CONTEXT}}"
exit 0
```

### hooks/post-tool-use (NEW, ~30 lines)

```bash
#!/bin/bash
# PostToolUse — fact-checking on writes (Layer 4)
source "$(dirname "$0")/lib.sh"
read_hook_input

TOOL=$(echo "$HOOK_INPUT" | jq -r '.tool_name // empty')
should_check_tool "$TOOL" || exit 0

CONTENT=$(extract_write_content "$HOOK_INPUT")
[[ -z "$CONTENT" ]] && exit 0

ISSUES=$(call_adapter fact_check "$CONTENT")
[[ -z "$ISSUES" ]] && exit 0

[[ "$(echo "$ISSUES" | jq 'length')" -eq 0 ]] && exit 0

CONTEXT=$(format_fact_issues "$ISSUES")
echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PostToolUse\",\"additionalContext\":$CONTEXT}}"
exit 0
```

### hooks/lib.sh (REWRITE, ~80 lines)

Key functions:

```bash
call_adapter() {
    # Invoke Python adapter via subprocess
    # Args: method [args...]
    # Returns: JSON output or empty
    "$PLUGIN_VENV/bin/python3" -m rawgentic_memory.adapter "$@" 2>/dev/null
}

should_search() {
    # Smart gate for UserPromptSubmit
    local prompt="$1" project="$2"
    [[ ${#prompt} -lt 20 ]] && return 1
    [[ "$prompt" == /* ]] && return 1
    [[ "$prompt" =~ ^(commit|push|yes|no|y|n|ok|done|next|looks good|lgtm)$ ]] && return 1
    local now=$(date +%s)
    local last=$(cat "$STATE_DIR/last-recall-ts-$project" 2>/dev/null || echo 0)
    [[ $((now - last)) -lt 60 ]] && return 1
    return 0
}

should_check_tool() {
    local tool="$1"
    [[ "$tool" =~ ^(Edit|Write|MultiEdit)$ ]]
}

resolve_project() {
    # Read active project from rawgentic workspace
    jq -r '...' "$WORKSPACE_ROOT/.rawgentic_workspace.json"
}

format_memory_context() {
    echo "$1" | jq -r '...'  # Citation-formatted output
}

format_fact_issues() {
    echo "$1" | jq -r '...'  # Issue list with corrections
}
```

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

### Phase 2: Install Mempalace Native Hooks (Day 1, ~10 min)

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [{
      "matcher": "*",
      "hooks": [{
        "type": "command",
        "command": "/path/to/mempalace/hooks/mempal_save_hook.sh",
        "timeout": 30
      }]
    }],
    "PreCompact": [{
      "hooks": [{
        "type": "command",
        "command": "/path/to/mempalace/hooks/mempal_precompact_hook.sh",
        "timeout": 30
      }]
    }]
  }
}
```

**Validation:** Run a session, verify save hook fires every 15 messages, Claude files via MCP tools.

### Phase 3: Register Mempalace MCP Server (Day 1, ~5 min)

```bash
# Standard MCP registration
claude mcp add mempalace -- python -m mempalace.mcp_server
```

**Validation:** Claude can call `mempalace_search`, `mempalace_kg_query`, etc.

### Phase 4: Build Adapter Module (Day 2, ~4 hours)

Create `rawgentic_memory/adapter.py`:
- `MempalaceAdapter` class with versioning
- All four methods (`search`, `wakeup`, `fact_check`, `health`)
- Error handling — no exceptions leak
- CLI entry point: `python -m rawgentic_memory.adapter <method> [args...]`
- Unit tests against mempalace 3.3.0

**Validation:** `python -m rawgentic_memory.adapter health` returns valid JSON.

### Phase 5: Rewrite Hooks (Day 2, ~4 hours)

Replace existing hooks with new minimal versions:

| Old Hook | Action | New Hook |
|---|---|---|
| `hooks/session-start` | Strip ingest, route through adapter | `hooks/session-start` (wakeup only) |
| `hooks/user-prompt-submit` | Replace with auto-recall | `hooks/user-prompt-submit` (recall) |
| `hooks/stop` | Delete | (mempalace native handles) |
| `hooks/lib.sh` | Replace with adapter calls | `hooks/lib.sh` (smart_gate, format) |
| (none) | Add | `hooks/post-tool-use` (fact-checking) |

**Validation:** Session works end-to-end — wakeup, auto-recall, fact-checking.

### Phase 6: Delete Server Infrastructure (Day 3, ~2 hours)

Once hooks proven working with adapter:

```bash
git rm rawgentic_memory/server.py
git rm rawgentic_memory/mempalace_backend.py
git rm rawgentic_memory/enrichment.py
git rm rawgentic_memory/models.py
# Keep: __init__.py, adapter.py
```

Update `pyproject.toml`:
- Remove `fastapi`, `uvicorn` dependencies
- Keep `mempalace>=3.3.0,<4.0`

**Validation:** Plugin works without any HTTP server.

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
| Mempalace 3.3.0 breaking change in `search_memories()` API | Low | Adapter isolates; pin specific version if needed |
| Native save hook conflicts with rawgentic Stop hook | Medium | Test together; mempalace uses `stop_hook_active` flag |
| MCP tool registration fails | Low | Standard MCP pattern; fall back to hooks-only |
| ChromaDB migration corrupts data | Low | Backup palace dir before Phase 1; mempalace migrate is well-tested |
| Cold-start Python latency too high | Medium | If >800ms perceived, add tiny daemon as v2 optimization |
| Claude doesn't follow proactive search instructions | High | Layer 1+2 hook injection primes the pump; Layer 4 catches contradictions |
| Mempalace 4.0 breaks adapter contract | Low | Adapter major-version aligned; write v4 adapter when 4.0 ships |

## Rollback Plan

| Phase | Rollback |
|---|---|
| 0 (Onboarding) | `rm -rf ~/.mempalace; mv ~/.mempalace.backup ~/.mempalace` |
| 1 (Upgrade) | Pin back to 3.0.0 in pyproject.toml; reinstall |
| 1.5 (Bulk mine) | Drop wings via `mempalace` CLI or restore backup |
| 2 (Native hooks) | Remove from `~/.claude/settings.json` |
| 3 (MCP) | `claude mcp remove mempalace` |
| 4-7 (Code changes) | Revert via git |

Memories are safe throughout — palace storage location is unchanged.

## Success Criteria

1. Server upgrade research from this brainstorm session is searchable in mempalace within 24 hours of implementation
2. Auto-recall fires on >80% of substantive prompts without user intervention
3. Wakeup context injects within 500ms of session start
4. Fact-checking catches at least one contradiction per week of active development
5. Claude proactively uses MCP tools during brainstorming/implementation 5+ times per session (Layer 3)
6. Total bridge plugin code reduces from ~700 lines to ~250 lines
7. Plugin upgrade to mempalace 3.4.x requires zero code changes (adapter contract holds)
8. Plugin upgrade to mempalace 4.0 requires <200 lines of adapter changes only

## Out of Scope (v2 Considerations)

- Cross-wing tunnel-aware recall (search related projects when current project has thin matches)
- LLM-based closet generation via `closet_llm.py`
- Long-running adapter daemon if cold-start latency proves problematic
- MCP resource exposure when Claude Code adds support
- Multi-user palace isolation (currently single-user)
- Encrypted palace storage

## References

- mempalace v3.3.0 release: https://github.com/MemPalace/mempalace/releases/tag/v3.3.0
- mempalace hooks documentation: https://mempalaceofficial.com/guide/hooks.html
- mempalace source (develop): https://github.com/MemPalace/mempalace/tree/develop/mempalace
- Key files reviewed: `searcher.py`, `layers.py`, `fact_checker.py`, `general_extractor.py`, `hooks_cli.py`, `palace.py`, `palace_graph.py`, `dialect.py`, `dedup.py`, `onboarding.py`
- Claude Code hooks reference: hook protocol with stdin JSON, additionalContext (10k chars), exit codes (0=success, 2=blocking)
