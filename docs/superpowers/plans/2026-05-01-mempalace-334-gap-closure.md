# MemPalace 3.3.4 Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade mempalace 3.3.2→3.3.4, fix stale contract validation, repair broken recall skill subcommands, remove redundant L0+L1 wakeup (mempalace owns that natively), and add cross-wing tunnel context as our unique wakeup contribution.

**Architecture:** The adapter layer (`adapter.py`) wraps mempalace's Python API. The slim HTTP server exposes endpoints consumed by hooks. Skills invoke MCP tools or curl the server. Key architectural shift: mempalace's native SessionStart hook now handles L0+L1 wakeup — our plugin drops that redundancy and contributes only tunnel context at session start.

**Tech Stack:** Python 3.12, FastAPI, mempalace 3.3.4, pytest, bash hooks

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `rawgentic_memory/adapter.py` | Modify | Dynamic MCP tool probing, tunnel-only wakeup (drop L0+L1), new `TunnelLink` dataclass |
| `rawgentic_memory/server.py` | Modify | New `/tunnels` endpoint, update `/wakeup` to return only tunnel context |
| `hooks/session-start` | Modify | Only inject tunnel context (L0+L1 handled by mempalace native hook) |
| `skills/recall/SKILL.md` | Modify | Replace broken /kg/* curl with MCP tool instructions, add tunnels subcommand |
| `skills/upgrade/SKILL.md` | Modify | Update import verification list |
| `tests/test_adapter.py` | Modify | Tests for dynamic contract, tunnel-only wakeup |
| `tests/test_server_slim.py` | Modify | Test for /tunnels endpoint, updated /wakeup response |

---

## Task 1: Upgrade mempalace via pipx

**Files:** None (system-level package upgrade)

- [ ] **Step 1: Record baseline palace size**

```bash
du -sh ~/.mempalace/palace
```

Expected: ~160M (current baseline).

- [ ] **Step 2: Upgrade via pipx**

```bash
pipx upgrade mempalace
```

Expected: `upgraded package mempalace from 3.3.2 to 3.3.4`

- [ ] **Step 3: Verify new version**

```bash
mempalace --version
```

Expected: `MemPalace 3.3.4`

- [ ] **Step 4: Verify imports still work**

```bash
~/.local/share/pipx/venvs/mempalace/bin/python3 -c "
from mempalace.searcher import search_memories
from mempalace.layers import Layer0, Layer1
from mempalace.fact_checker import check_text
from mempalace.palace import get_collection
from mempalace.palace_graph import find_tunnels, follow_tunnels
print('All imports OK')
"
```

Expected: `All imports OK`

- [ ] **Step 5: Check palace size after upgrade (HNSW bloat fix)**

```bash
du -sh ~/.mempalace/palace
```

Note the before/after. The HNSW bloat fix in 3.3.4 prevents future growth; existing size may not shrink until next `mempalace mine` or `repair`.

- [ ] **Step 6: Also upgrade plugin venv**

```bash
PLUGIN_DIR=$(find ~/.claude/plugins/cache -path "*/rawgentic-memorypalace/*/rawgentic-memorypalace" -type d 2>/dev/null | head -1)
if [ -d "$PLUGIN_DIR/.venv" ]; then
    "$PLUGIN_DIR/.venv/bin/pip" install --upgrade "mempalace>=3.3.4,<4.0"
fi
```

No commit — system-level change only.

---

## Task 2: Make BEHAVIORAL_CONTRACT dynamic

The hardcoded 6-tool list drifts with every mempalace release (now 29 tools). Switch to asserting only critical tools the adapter directly calls, and log total available count.

**Files:**
- Modify: `rawgentic_memory/adapter.py:71-83` (contract definition), `:252-265` (verify method)
- Test: `tests/test_adapter.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_adapter.py`, add to `TestBehavioralContract`:

```python
    def test_critical_tools_is_subset_of_available(self):
        """Critical tools are the ones the adapter directly calls."""
        critical = MempalaceAdapter.CRITICAL_MCP_TOOLS
        assert "mempalace_search" in critical
        assert "mempalace_add_drawer" in critical
        assert "mempalace_diary_write" in critical
        assert len(critical) <= 10  # guard against re-bloating

    def test_verify_reports_tool_count(self, isolated_palace):
        """Contract verification now reports available tool count, not missing list."""
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        violations = adapter.verify_behavioral_contract()
        # With real mempalace installed, no critical tools should be missing
        critical_missing = [v for v in violations if v.field.startswith("mcp_tool:")]
        assert critical_missing == []

    def test_verify_reports_missing_critical_tool(self, isolated_palace, monkeypatch):
        """When a critical tool is missing, it's reported as an error."""
        import sys
        import mempalace
        import mempalace.mcp_server  # noqa: F401
        from unittest.mock import MagicMock
        fake_mcp = MagicMock()
        fake_mcp.TOOLS = {"mempalace_search": object()}
        monkeypatch.setitem(sys.modules, "mempalace.mcp_server", fake_mcp)
        monkeypatch.setattr(mempalace, "mcp_server", fake_mcp)
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        violations = adapter.verify_behavioral_contract()
        missing = [v for v in violations if v.field.startswith("mcp_tool:")]
        # mempalace_add_drawer and mempalace_diary_write should be flagged
        assert len(missing) >= 2
        assert all(v.severity == "error" for v in missing)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/rocky00717/rawgentic/projects/rawgentic-memorypalace && .venv/bin/python -m pytest tests/test_adapter.py::TestBehavioralContract::test_critical_tools_is_subset_of_available tests/test_adapter.py::TestBehavioralContract::test_verify_reports_tool_count tests/test_adapter.py::TestBehavioralContract::test_verify_reports_missing_critical_tool -v`

Expected: FAIL — `CRITICAL_MCP_TOOLS` doesn't exist yet, severity is "warning" not "error".

- [ ] **Step 3: Implement the change**

In `rawgentic_memory/adapter.py`, replace lines 71-83:

Old:
```python
    BEHAVIORAL_CONTRACT = {
        "expected_mcp_tools": [
            "mempalace_search",
            "mempalace_add_drawer",
            "mempalace_diary_write",
            "mempalace_kg_query",
            "mempalace_kg_add",
            "mempalace_kg_invalidate",
        ],
        "expected_save_interval": 15,
        "expected_palace_dir": "~/.mempalace/palace",
        "expected_kg_path": "~/.mempalace/knowledge_graph.sqlite3",
    }
```

New:
```python
    CRITICAL_MCP_TOOLS = frozenset({
        "mempalace_search",
        "mempalace_add_drawer",
        "mempalace_diary_write",
        "mempalace_kg_query",
        "mempalace_kg_add",
        "mempalace_kg_invalidate",
    })
    BEHAVIORAL_CONTRACT = {
        "expected_save_interval": 15,
        "expected_palace_dir": "~/.mempalace/palace",
        "expected_kg_path": "~/.mempalace/knowledge_graph.sqlite3",
    }
```

Replace lines 252-265 (the MCP tool check in `verify_behavioral_contract`):

Old:
```python
        # Check expected MCP tools are exposed by mempalace
        try:
            from mempalace import mcp_server as _mcp
            available_tools = set(getattr(_mcp, "TOOLS", {}).keys())
            for tool_name in self.BEHAVIORAL_CONTRACT.get("expected_mcp_tools", []):
                if tool_name not in available_tools:
                    violations.append(ContractViolation(
                        field=f"mcp_tool:{tool_name}",
                        expected="present",
                        actual="missing",
                        severity="warning",
                    ))
        except Exception:
            pass
```

New:
```python
        # Check critical MCP tools are exposed by mempalace
        try:
            from mempalace import mcp_server as _mcp
            available_tools = set(getattr(_mcp, "TOOLS", {}).keys())
            for tool_name in self.CRITICAL_MCP_TOOLS:
                if tool_name not in available_tools:
                    violations.append(ContractViolation(
                        field=f"mcp_tool:{tool_name}",
                        expected="present",
                        actual="missing",
                        severity="error",
                    ))
            logger.info(
                "mempalace exposes %d MCP tools (%d critical)",
                len(available_tools), len(self.CRITICAL_MCP_TOOLS),
            )
        except Exception:
            pass
```

- [ ] **Step 4: Update existing tests that reference old constant**

In `tests/test_adapter.py`, update `test_behavioral_contract_lists_expected_mcp_tools`:

```python
    def test_behavioral_contract_lists_expected_mcp_tools(self):
        tools = MempalaceAdapter.CRITICAL_MCP_TOOLS
        assert "mempalace_search" in tools
        assert "mempalace_add_drawer" in tools
        assert "mempalace_diary_write" in tools
```

Update `test_verify_detects_missing_mcp_tool` to check for `severity="error"`:

```python
    def test_verify_detects_missing_mcp_tool(self, isolated_palace, monkeypatch):
        import sys
        import mempalace
        import mempalace.mcp_server  # noqa: F401
        from unittest.mock import MagicMock
        fake_mcp = MagicMock()
        fake_mcp.TOOLS = {"mempalace_search": object()}
        monkeypatch.setitem(sys.modules, "mempalace.mcp_server", fake_mcp)
        monkeypatch.setattr(mempalace, "mcp_server", fake_mcp)
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        violations = adapter.verify_behavioral_contract()
        missing_fields = [v.field for v in violations]
        assert "mcp_tool:mempalace_add_drawer" in missing_fields
        tool_violations = [v for v in violations if v.field.startswith("mcp_tool:")]
        assert all(v.severity == "error" for v in tool_violations)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/rocky00717/rawgentic/projects/rawgentic-memorypalace && .venv/bin/python -m pytest tests/test_adapter.py::TestBehavioralContract -v`

Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add rawgentic_memory/adapter.py tests/test_adapter.py
git commit -m "refactor: make MCP tool contract dynamic, assert only critical tools"
```

---

## Task 3: Replace wakeup with tunnel-only context + remove L0/L1 redundancy

Mempalace's native SessionStart hook already injects L0+L1 context. Our plugin was duplicating that work. Strip L0+L1 from our wakeup — our unique contribution is now **tunnel context only** (cross-wing topic links that mempalace doesn't inject automatically).

**Files:**
- Modify: `rawgentic_memory/adapter.py` — new `TunnelLink` dataclass, `wakeup()` → tunnel-only, new `find_tunnels_for_wing()`
- Modify: `rawgentic_memory/server.py` — new `/tunnels` endpoint, `/wakeup` returns tunnel context only
- Modify: `hooks/session-start` — simplified, only injects tunnel context
- Test: `tests/test_adapter.py` — rewrite `TestWakeup`, add `TestTunnelWakeup`, `TestFindTunnels`
- Test: `tests/test_server_slim.py` — `/tunnels` endpoint, updated `/wakeup` assertion

- [ ] **Step 1: Write the failing adapter tests**

In `tests/test_adapter.py`, rewrite `TestWakeup` and add new test classes:

```python
from rawgentic_memory.adapter import TunnelLink


class TestWakeup:
    def test_wakeup_with_project_returns_tunnel_context(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        ctx = adapter.wakeup(project="rawgentic_memorypalace")
        assert isinstance(ctx, WakeupContext)
        # L0/L1 no longer included — mempalace native hook handles those
        assert "L0" not in ctx.layers
        assert "L1" not in ctx.layers

    def test_wakeup_without_project_returns_empty(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        ctx = adapter.wakeup(project=None)
        assert ctx.text == ""
        assert ctx.tokens == 0
        assert ctx.layers == []

    def test_wakeup_graceful_on_import_error(self, tmp_path, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules, "mempalace.palace_graph", None)
        monkeypatch.setitem(__import__("sys").modules, "mempalace", None)
        adapter = MempalaceAdapter(palace_path=str(tmp_path))
        ctx = adapter.wakeup(project="test")
        assert ctx.text == ""
        assert ctx.layers == []


class TestTunnelContext:
    def test_tunnel_link_dataclass(self):
        link = TunnelLink(
            shared_topic="documentation",
            connected_wings=["chorestory", "grocusave"],
            drawer_count=150,
        )
        assert link.shared_topic == "documentation"
        assert len(link.connected_wings) == 2
        assert link.drawer_count == 150

    def test_render_tunnel_context_with_tunnels(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        fake_tunnels = [
            {"room": "documentation", "wings": ["proj_a", "proj_b", "proj_c"], "count": 500},
            {"room": "testing", "wings": ["proj_a", "proj_d"], "count": 100},
        ]
        with patch("mempalace.palace_graph.find_tunnels", return_value=fake_tunnels):
            text = adapter._render_tunnel_context("proj_a")
        assert "Cross-project links" in text
        assert "documentation" in text
        assert "proj_b" in text
        assert "proj_a" not in text  # current wing excluded from list

    def test_render_tunnel_context_empty_when_no_tunnels(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        with patch("mempalace.palace_graph.find_tunnels", return_value=[]):
            text = adapter._render_tunnel_context("proj_a")
        assert text == ""

    def test_wakeup_includes_tunnels_layer_when_tunnels_exist(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        fake_tunnels = [
            {"room": "documentation", "wings": ["proj_a", "proj_b"], "count": 500},
        ]
        with patch("mempalace.palace_graph.find_tunnels", return_value=fake_tunnels):
            ctx = adapter.wakeup(project="proj_a")
        assert "tunnels" in ctx.layers
        assert "Cross-project links" in ctx.text
        assert ctx.tokens > 0


class TestFindTunnels:
    def test_find_tunnels_returns_list(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        tunnels = adapter.find_tunnels_for_wing("test_wing")
        assert isinstance(tunnels, list)

    def test_find_tunnels_graceful_on_error(self, tmp_path, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules, "mempalace.palace_graph", None)
        monkeypatch.setitem(__import__("sys").modules, "mempalace", None)
        adapter = MempalaceAdapter(palace_path=str(tmp_path))
        tunnels = adapter.find_tunnels_for_wing("test_wing")
        assert tunnels == []

    def test_find_tunnels_excludes_own_wing(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        fake_tunnels = [
            {"room": "docs", "wings": ["proj_a", "proj_b", "proj_c"], "count": 100},
        ]
        with patch("mempalace.palace_graph.find_tunnels", return_value=fake_tunnels):
            tunnels = adapter.find_tunnels_for_wing("proj_a")
        assert len(tunnels) == 1
        assert "proj_a" not in tunnels[0].connected_wings
        assert "proj_b" in tunnels[0].connected_wings
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/rocky00717/rawgentic/projects/rawgentic-memorypalace && .venv/bin/python -m pytest tests/test_adapter.py::TestWakeup tests/test_adapter.py::TestTunnelContext tests/test_adapter.py::TestFindTunnels -v`

Expected: FAIL — `TunnelLink` doesn't exist, wakeup still does L0+L1.

- [ ] **Step 3: Add TunnelLink dataclass**

In `rawgentic_memory/adapter.py`, after the `FactIssue` dataclass (after line 65):

```python
@dataclass
class TunnelLink:
    shared_topic: str
    connected_wings: list[str]
    drawer_count: int = 0
```

- [ ] **Step 4: Add find_tunnels_for_wing method**

In `MempalaceAdapter`, after `fact_check()` method:

```python
    def find_tunnels_for_wing(self, wing: str) -> list[TunnelLink]:
        try:
            from mempalace.palace_graph import find_tunnels
            raw = find_tunnels(wing_a=wing)
            return [
                TunnelLink(
                    shared_topic=t.get("room", ""),
                    connected_wings=[
                        w for w in t.get("wings", []) if w != wing
                    ],
                    drawer_count=t.get("count", 0),
                )
                for t in raw
                if t.get("room")
            ]
        except Exception as e:
            logger.warning("find_tunnels_for_wing failed: %s", e)
            return []
```

- [ ] **Step 5: Replace wakeup() — tunnel-only, drop L0/L1**

Replace the existing `wakeup()` method (lines 92-102):

Old:
```python
    def wakeup(self, project: str | None = None) -> WakeupContext:
        try:
            from mempalace.layers import Layer0, Layer1
            l0 = Layer0().render()
            l1 = Layer1(palace_path=self.palace_path, wing=project).generate()
            text = f"{l0}\n\n{l1}"
            # Token estimate: chars/4 ±25% — over for code-heavy, under for NL.
            return WakeupContext(text=text, tokens=len(text) // 4, layers=["L0", "L1"])
        except Exception as e:
            logger.warning("wakeup failed: %s", e)
            return WakeupContext(text="", tokens=0, layers=[])
```

New:
```python
    def wakeup(self, project: str | None = None) -> WakeupContext:
        if not project:
            return WakeupContext(text="", tokens=0, layers=[])
        tunnel_text = self._render_tunnel_context(project)
        if not tunnel_text:
            return WakeupContext(text="", tokens=0, layers=[])
        return WakeupContext(
            text=tunnel_text, tokens=len(tunnel_text) // 4, layers=["tunnels"]
        )

    def _render_tunnel_context(self, wing: str) -> str:
        tunnels = self.find_tunnels_for_wing(wing)
        if not tunnels:
            return ""
        lines = ["## Cross-project links"]
        for t in tunnels[:5]:
            others = ", ".join(t.connected_wings[:5])
            suffix = (
                f" (+{len(t.connected_wings) - 5} more)"
                if len(t.connected_wings) > 5 else ""
            )
            lines.append(
                f"- **{t.shared_topic}**: shared with {others}{suffix}"
                f" ({t.drawer_count} memories)"
            )
        return "\n".join(lines)
```

- [ ] **Step 6: Remove Layer0/Layer1 imports**

Remove the now-unused lazy imports from `wakeup()`. Check that no other method in adapter.py imports from `mempalace.layers`. If `search_memories` import at top level (line 14) is still needed, keep it. The `Layer0, Layer1` import was only in `wakeup()` and is now gone.

- [ ] **Step 7: Run adapter tests**

Run: `cd /home/rocky00717/rawgentic/projects/rawgentic-memorypalace && .venv/bin/python -m pytest tests/test_adapter.py -v`

Expected: All PASS. The old `test_wakeup_returns_l0_and_l1` test is gone, replaced by new tests.

- [ ] **Step 8: Write server /tunnels endpoint test**

In `tests/test_server_slim.py`, add:

```python
class TestTunnelsEndpoint:
    def test_tunnels_returns_json(self, client):
        resp = client.get("/tunnels?wing=test_wing")
        assert resp.status_code == 200
        data = resp.json()
        assert "tunnels" in data
        assert isinstance(data["tunnels"], list)

    def test_tunnels_without_wing_returns_422(self, client):
        resp = client.get("/tunnels")
        assert resp.status_code == 422
```

- [ ] **Step 9: Update /wakeup server test**

In `tests/test_server_slim.py`, update existing wakeup test to match new behavior (no L0/L1, returns tunnel context only):

```python
class TestWakeupEndpoint:
    def test_wakeup_no_project_returns_empty(self, client):
        resp = client.get("/wakeup")
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == ""
        assert data["layers"] == []

    def test_wakeup_with_project_returns_json(self, client):
        resp = client.get("/wakeup?project=test_project")
        assert resp.status_code == 200
        data = resp.json()
        # May be empty if no tunnels — but structure is valid
        assert "text" in data
        assert "tokens" in data
        assert "layers" in data
```

- [ ] **Step 10: Add /tunnels endpoint to server**

In `rawgentic_memory/server.py`, after the `/fact_check` endpoint (after line 139):

```python
    @app.get("/tunnels")
    async def tunnels(wing: str = Query(max_length=128)):
        links = adapter.find_tunnels_for_wing(wing)
        return JSONResponse({
            "tunnels": [
                {
                    "shared_topic": t.shared_topic,
                    "connected_wings": t.connected_wings,
                    "drawer_count": t.drawer_count,
                }
                for t in links
            ]
        })
```

- [ ] **Step 11: Update SessionStart hook — tunnel context only**

Replace `hooks/session-start` entirely:

```bash
#!/bin/bash
# Hook: SessionStart
# Tunnel-context only: L0+L1 handled by mempalace's native SessionStart hook.
# This hook adds cross-wing topic tunnels for multi-project awareness.
# Graceful degradation: exits 0 if memory server is unreachable.
# NO set -e — graceful degradation requires non-zero returns to be handled explicitly.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

# Read hook input from stdin
HOOK_INPUT=$(cat)

# Auto-detect workspace from hook input .cwd (env var overrides)
CWD=$(echo "$HOOK_INPUT" | jq -r '.cwd // empty' 2>/dev/null) || true
MEMPALACE_CLAUDE_WORKSPACE="${MEMPALACE_CLAUDE_WORKSPACE:-$CWD}"
PROJECT=$(resolve_project "$CWD")

_debug "SessionStart: project=$PROJECT cwd=$CWD"

# No project → no tunnel context to add
if [[ -z "$PROJECT" || "$PROJECT" == "unknown" ]]; then
    _debug "SessionStart: no project resolved — skipping tunnel context"
    exit 0
fi

# Ensure server is running (lazy-start allowed on session start — timeout 10s)
if ! ensure_server_running; then
    _debug "SessionStart: server not available — exiting 0"
    exit 0
fi

# URL-encode project name
PROJECT_ENCODED=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1],safe=''))" "$PROJECT" 2>/dev/null) || true
PROJECT_ENCODED="${PROJECT_ENCODED:-$PROJECT}"

# Call /wakeup — now returns tunnel context only
WAKEUP_RESPONSE=$(curl --silent --fail --connect-timeout 2 --max-time 8 \
    "${MEMORY_SERVER_URL}/wakeup?project=${PROJECT_ENCODED}" 2>/dev/null) || true

if [[ -n "$WAKEUP_RESPONSE" ]]; then
    if echo "$WAKEUP_RESPONSE" | jq empty 2>/dev/null; then
        CONTEXT=$(echo "$WAKEUP_RESPONSE" | jq -r '.text // empty' 2>/dev/null) || true
        if [[ -n "$CONTEXT" ]]; then
            _debug "SessionStart: tunnel context received"
            echo "$WAKEUP_RESPONSE" | jq '{
                hookSpecificOutput: {
                    hookEventName: "SessionStart",
                    additionalContext: (.text // "")
                }
            }'
        else
            _debug "SessionStart: no tunnel context for this project"
        fi
    else
        _debug "SessionStart: wakeup returned non-JSON — ignoring"
    fi
else
    _debug "SessionStart: no wakeup response"
fi

exit 0
```

- [ ] **Step 12: Run all tests**

Run: `cd /home/rocky00717/rawgentic/projects/rawgentic-memorypalace && .venv/bin/python -m pytest tests/ -v`

Expected: All PASS.

- [ ] **Step 13: Commit**

```bash
git add rawgentic_memory/adapter.py rawgentic_memory/server.py hooks/session-start tests/test_adapter.py tests/test_server_slim.py
git commit -m "feat: tunnel-only wakeup, drop redundant L0/L1 (mempalace native handles it)

BREAKING: /wakeup no longer returns L0+L1 layers. Mempalace's native
SessionStart hook handles identity and memory context. Our plugin now
contributes only cross-wing tunnel context at session start.

New /tunnels endpoint for explicit tunnel browsing."
```

---

## Task 4: Fix recall skill — route KG operations through MCP tools

The recall skill's `invalidate` and `timeline` subcommands curl `/kg/invalidate` and `/kg/timeline`, which return 410 Gone. Route these through mempalace MCP tools that Claude calls directly. Also add `tunnels` subcommand.

**Files:**
- Modify: `skills/recall/SKILL.md`

- [ ] **Step 1: Update subcommand dispatch (Section 1)**

In `skills/recall/SKILL.md`, replace the dispatch list (around line 30):

Old:
```markdown
- **`invalidate`** → go to **Section 5: Invalidate a Decision**
- **`timeline`** → go to **Section 6: View Timeline**
- **Anything else** → treat as a search query, continue to Step 2
```

New:
```markdown
- **`invalidate`** → go to **Section 5: Invalidate a Decision**
- **`timeline`** → go to **Section 6: View Timeline**
- **`tunnels`** → go to **Section 7: Browse Cross-Project Tunnels**
- **Anything else** → treat as a search query, continue to Step 2
```

- [ ] **Step 2: Replace Section 5 (Invalidate)**

Replace lines 143-181 with:

```markdown
### 5. Invalidate a Decision

When the first argument is `invalidate`, parse the remaining text as a KG triple to invalidate.

**Parsing the triple:** The text after `invalidate` should contain: `"<subject> decided <object>"` (with or without quotes).

- **Subject:** the first word (typically the project name)
- **Predicate:** always `"decided"` (hardcoded for v1)
- **Object:** everything after the word "decided"

Example: `/rawgentic-memorypalace:recall invalidate "chorestory decided use Zod"` → subject=`chorestory`, predicate=`decided`, object=`use Zod`

If the text doesn't contain "decided", tell the user: "Expected format: /rawgentic-memorypalace:recall invalidate \"<project> decided <description>\"" and STOP.

**Call the MCP tool directly:**

Use the `mempalace_kg_invalidate` MCP tool with these parameters:
- `subject`: the parsed subject
- `predicate`: `"decided"`
- `object`: the parsed object

**Display confirmation:**

If the tool succeeds:
```
Invalidated: **<subject>** decided **<object>**
This decision is now marked as historical and will be demoted in search results.
```

If the tool reports no matching triple:
```
No matching active decision found for: <subject> decided <object>
The triple may not exist or may already be invalidated.
```

If the MCP tool is not available (mempalace plugin not installed): tell the user "The mempalace MCP server is not connected. Ensure the mempalace plugin is installed and active." and STOP.
```

- [ ] **Step 3: Replace Section 6 (Timeline)**

Replace lines 185-end with:

```markdown
### 6. View Timeline

When the first argument is `timeline`, the second argument is the entity name.

If no entity name is provided, ask the user: "Which project or entity timeline do you want to see?" and STOP.

**Call the MCP tool directly:**

Use the `mempalace_kg_timeline` MCP tool with:
- `entity`: the entity name

**Display the timeline** in chronological order (oldest to newest):

```
## Decision Timeline: <entity>

| # | Date | Decision | Status |
|---|------|----------|--------|
| 1 | 2026-01-15 | decided: use PostgreSQL | current |
| 2 | 2026-02-20 | decided: use Zod | invalidated |
| 3 | 2026-03-01 | decided: use Valibot | current |
```

Each entry MUST show:
- **valid_from** date (formatted as YYYY-MM-DD)
- **predicate** and **object** as the decision description
- **Status:** "current" if `current: true`, "invalidated" if `current: false`

If the timeline is empty: "No decision history found for <entity>." and STOP.

If the MCP tool is not available: tell the user "The mempalace MCP server is not connected. Ensure the mempalace plugin is installed and active." and STOP.
```

- [ ] **Step 4: Add Section 7 (Browse Tunnels)**

Append after Section 6:

```markdown
---

### 7. Browse Cross-Project Tunnels

When the first argument is `tunnels`, the optional second argument is a wing (project) name.

Read the `MEMORY_SERVER_URL` from the `Memory Server Configuration` section of CLAUDE.md. Default to `http://127.0.0.1:8420`.

**Call the tunnels endpoint:**

If a wing name is provided:
```bash
curl --silent --fail --connect-timeout 2 --max-time 10 \
  "MEMORY_SERVER_URL/tunnels?wing=WING_NAME"
```

If no wing name is provided, use the current active project from the rawgentic workspace. Determine this by reading `.rawgentic_workspace.json` and finding the most recently used active project.

**Display results:**

Parse the JSON response. The response shape is:
```json
{
  "tunnels": [
    {
      "shared_topic": "documentation",
      "connected_wings": ["chorestory", "grocusave", "rawgentic"],
      "drawer_count": 18729
    }
  ]
}
```

Format as a table:

```
## Cross-Project Tunnels: <wing>

| # | Shared Topic | Connected Projects | Memories |
|---|--------------|-------------------|----------|
| 1 | documentation | chorestory, grocusave, rawgentic | 18,729 |
| 2 | testing | chorestory, nillerkgames | 342 |
```

If no tunnels found: "No cross-project topic tunnels found for <wing>." and STOP.

Handle server errors the same as Section 3. STOP after displaying.
```

- [ ] **Step 5: Commit**

```bash
git add skills/recall/SKILL.md
git commit -m "fix: route recall invalidate/timeline through MCP tools, add tunnels subcommand"
```

---

## Task 5: Update upgrade skill verification

The import check verifies APIs the adapter actually uses. Update for 3.3.4 (palace_graph APIs, correct module paths).

**Files:**
- Modify: `skills/upgrade/SKILL.md`

- [ ] **Step 1: Update the verification command**

In `skills/upgrade/SKILL.md`, replace the verification command in Step 5 (line 89):

Old:
```python
from mempalace.miner import get_collection; from mempalace.searcher import search_memories; from mempalace.layers import MemoryStack; print('All imports OK')
```

New:
```python
from mempalace.palace import get_collection; from mempalace.searcher import search_memories; from mempalace.palace_graph import find_tunnels, follow_tunnels; from mempalace.fact_checker import check_text; print('All imports OK')
```

Note: `MemoryStack` and `Layer0/Layer1` removed from verification — our adapter no longer uses them (mempalace's native hooks handle L0/L1). `palace_graph` imports added since adapter now depends on tunnel APIs.

- [ ] **Step 2: Commit**

```bash
git add skills/upgrade/SKILL.md
git commit -m "fix: update upgrade skill verification imports for 3.3.4 API"
```

---

## Task 6: Run full test suite and live verification

Final integration pass to ensure everything works together.

- [ ] **Step 1: Run full test suite**

```bash
cd /home/rocky00717/rawgentic/projects/rawgentic-memorypalace && .venv/bin/python -m pytest tests/ -v
```

Expected: All PASS.

- [ ] **Step 2: Restart memory server and verify diagnostic**

```bash
pkill -f "rawgentic_memory.server" || true
sleep 2
# Start fresh and check diagnostic
curl --silent --fail http://10.0.17.205:8420/diagnostic 2>/dev/null | python3 -m json.tool
```

If server not running, start it manually:
```bash
cd /home/rocky00717/rawgentic/projects/rawgentic-memorypalace && .venv/bin/python -m rawgentic_memory.server --port 8420 &
sleep 3
curl --silent --fail http://10.0.17.205:8420/diagnostic | python3 -m json.tool
```

Expected: `contract_violations: []`, health shows mempalace version 3.3.4.

- [ ] **Step 3: Test wakeup — tunnel context only**

```bash
curl --silent --fail "http://10.0.17.205:8420/wakeup?project=rawgentic_memorypalace" | python3 -m json.tool
```

Expected: Response includes `"layers": ["tunnels"]` and text contains "Cross-project links". NO L0 or L1 layers.

- [ ] **Step 4: Test wakeup without project — empty**

```bash
curl --silent --fail "http://10.0.17.205:8420/wakeup" | python3 -m json.tool
```

Expected: `{"text": "", "tokens": 0, "layers": []}`.

- [ ] **Step 5: Test tunnels endpoint**

```bash
curl --silent --fail "http://10.0.17.205:8420/tunnels?wing=rawgentic_memorypalace" | python3 -m json.tool
```

Expected: JSON with `tunnels` array containing at least one entry with `shared_topic: "documentation"`.

- [ ] **Step 6: Verify mempalace native wakeup still works independently**

Start a new Claude Code session and check that the wakeup output contains L0 (identity) and L1 (memory context). These should come from mempalace's native hook, not ours. Our hook should add only tunnel context (if project has tunnels).
