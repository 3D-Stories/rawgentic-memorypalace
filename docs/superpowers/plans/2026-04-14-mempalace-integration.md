# MemPalace Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the lossy custom enrichment pipeline with mempalace 3.3.0's native ingest + four-layer recall, mediated by a thin HTTP gatekeeper and a versioned adapter contract.

**Architecture:** Three-plugin split (rawgentic + mempalace MCP + bridge). Bridge runs a slim READ-only HTTP server (~100 LOC) that wraps mempalace's Python API via an adapter pattern. Three bash hooks (`SessionStart`, `UserPromptSubmit`, `PostToolUse`) call HTTP via curl. Mempalace's own native hooks handle ingest by blocking Claude every 15 messages to file via MCP tools.

**Tech Stack:** Python 3.12, FastAPI + uvicorn (slimmed), bash 4+, jq, curl, pytest with Starlette TestClient, mempalace>=3.3.0,<4.0, ChromaDB 0.6+

**Spec:** `docs/superpowers/specs/2026-04-14-mempalace-integration-redesign.md` (r3)

---

## File Structure

### Files to Create

| Path | Purpose | Lines |
|---|---|---|
| `rawgentic_memory/adapter.py` | Versioned wrapper around mempalace Python API | ~200 |
| `hooks/post-tool-use` | Layer 4 fact-check hook | ~35 |
| `tests/test_adapter.py` | Adapter unit tests (12 tests) | ~250 |
| `tests/test_lib_sh.py` | Bash hook test suite (Python wraps bash) | ~150 |
| `tests/canary.py` | Continuous health canary | ~60 |
| `tests/integration/test_concurrent_writes.py` | Verify concurrent access safety | ~80 |
| `tests/integration/test_graceful_degradation.py` | Verify uninstall = no breakage | ~60 |
| `tests/integration/test_hook_timeouts.py` | Verify hook timeout compliance | ~100 |

### Files to Modify

| Path | Change |
|---|---|
| `rawgentic_memory/server.py` | Slim from ~500 to ~100 lines; remove `/ingest`, `/reindex`, `/kg/*`; add `/diagnostic`, `/canary_write`; route through adapter |
| `hooks/session-start` | Strip ingest; wakeup-only via curl `/wakeup` |
| `hooks/user-prompt-submit` | Replace with smart-gated auto-recall via curl `/search` |
| `hooks/lib.sh` | Rewrite — env-configurable thresholds, smart_gate, server_is_healthy, ensure_server_running |
| `hooks/hooks.json` | Add PostToolUse registration; matchers updated |
| `pyproject.toml` | Bump `mempalace>=3.3.0,<4.0`; keep `fastapi`, `uvicorn` |
| `tests/conftest.py` | Add fixtures for mocking mempalace, isolated palace, frozen clock |

### Files to Delete (Phase J only — after atomic cutover verified)

| Path | Why |
|---|---|
| `hooks/stop` | mempalace's stop hook handles this |
| `rawgentic_memory/enrichment.py` | Replaced by mempalace general_extractor + Save Hook |
| `rawgentic_memory/mempalace_backend.py` | Adapter replaces wrapper logic |
| `rawgentic_memory/models.py` | Types move into adapter.py |
| `tests/test_enrichment.py` | Tests deleted code |
| `tests/test_mempalace_backend.py` | Tests deleted code |
| `tests/test_kg_endpoints.py` | Tests removed endpoints |
| `tests/test_reindex.py` | Tests removed endpoint |

### External Files Modified

| Path | Change |
|---|---|
| `~/.claude/settings.json` | Add mempalace native Stop + PreCompact hooks; register mempalace MCP server |
| `~/.mempalace/identity.txt` | Generate from rawgentic workspace identity |
| Project CLAUDE.md | Add "Memory" instruction section |
| Rawgentic skills (4) | Add memory-search step to brainstorming, implement-feature, fix-bug, refactor |

---

## Phase A — Pre-flight & Setup

### Task 0: Backup palace and verify branch state

**Files:**
- Read: existing palace at `~/.mempalace/`

- [ ] **Step 1: Verify on feature branch**

Run: `git branch --show-current`
Expected: `feature/mempalace-integration-redesign`

- [ ] **Step 2: Backup the palace**

Run: `cp -r ~/.mempalace ~/.mempalace.backup-$(date +%Y%m%d)`
Expected: backup directory created with current date

- [ ] **Step 3: Verify backup is complete**

Run: `du -sh ~/.mempalace ~/.mempalace.backup-*`
Expected: sizes match

- [ ] **Step 4: Snapshot pre-migration state**

Run:
```bash
.venv/bin/mempalace status > /tmp/pre-migration-status.txt 2>&1
cat /tmp/pre-migration-status.txt
```
Expected: drawer count and wing list snapshot saved

- [ ] **Step 5: Commit pre-migration snapshot to branch**

```bash
mkdir -p docs/migration
cp /tmp/pre-migration-status.txt docs/migration/pre-migration-status.txt
git add docs/migration/pre-migration-status.txt
git commit -m "chore: snapshot pre-migration palace status"
```

---

## Phase B — Onboarding & Identity

### Task 1: Create identity file from rawgentic workspace

**Files:**
- Create: `~/.mempalace/identity.txt`
- Read: `~/rawgentic/.rawgentic_workspace.json`

- [ ] **Step 1: Verify workspace file readable**

Run: `jq '.projects | length' ~/rawgentic/.rawgentic_workspace.json`
Expected: integer count of projects (>= 19)

- [ ] **Step 2: Generate identity file**

```bash
ACTIVE_PROJECTS=$(jq -r '[.projects[] | select(.active==true) | .name] | join(", ")' ~/rawgentic/.rawgentic_workspace.json)

cat > ~/.mempalace/identity.txt <<EOF
I am the memory layer for Chris, a developer at 3D-Stories.

Active projects: $ACTIVE_PROJECTS

Conventions:
- TDD always (RED-GREEN-REFACTOR, no exceptions)
- Conventional commits
- Never push to main without PR
- Run full CI locally before opening a PR (lint + format:check + tests + check)
- Verify ALL CI runs (unit + integration) pass before merge
- Memory server runs on 10.0.17.205:8420

Workflow: rawgentic SDLC skills (implement-feature, fix-bug, refactor, etc.)
plus mempalace memory layer with auto-recall and fact-checking.
EOF
```

- [ ] **Step 3: Verify identity file**

Run: `head -5 ~/.mempalace/identity.txt`
Expected: First line shows "I am the memory layer for Chris..."

- [ ] **Step 4: Verify L0 picks it up**

Run: `.venv/bin/python3 -c "from mempalace.layers import Layer0; print(Layer0().render()[:100])"`
Expected: Output starts with "I am the memory layer for Chris"

### Task 2: Set MEMPAL_DIR environment variable

**Files:**
- Modify: `~/.bashrc` (append)

- [ ] **Step 1: Check if MEMPAL_DIR already set**

Run: `grep MEMPAL_DIR ~/.bashrc || echo "not set"`
Expected: "not set"

- [ ] **Step 2: Append to .bashrc**

```bash
echo '' >> ~/.bashrc
echo '# mempalace background mining of session notes' >> ~/.bashrc
echo 'export MEMPAL_DIR=$HOME/rawgentic/claude_docs/session_notes/' >> ~/.bashrc
```

- [ ] **Step 3: Source and verify**

Run: `source ~/.bashrc && echo "MEMPAL_DIR=$MEMPAL_DIR"`
Expected: `MEMPAL_DIR=/home/rocky00717/rawgentic/claude_docs/session_notes/`

---

## Phase C — Upgrade Mempalace

### Task 3: Upgrade mempalace to 3.3.0

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Update pyproject.toml dependency**

Edit `pyproject.toml`:
```toml
dependencies = [
    "fastapi>=0.100.0",
    "uvicorn>=0.20.0",
    "mempalace>=3.3.0,<4.0",
]
```

- [ ] **Step 2: Run pip upgrade**

Run: `.venv/bin/pip install --upgrade "mempalace>=3.3.0,<4.0"`
Expected: Successfully installed mempalace-3.3.x (or higher)

- [ ] **Step 3: Verify version**

Run: `.venv/bin/pip show mempalace | grep Version`
Expected: `Version: 3.3.x` where x >= 0

- [ ] **Step 4: Run mempalace migrate (idempotent)**

Run: `.venv/bin/mempalace migrate 2>&1 | tail -20`
Expected: Migration succeeds or "already up to date"

- [ ] **Step 5: Verify palace still searchable**

Run: `.venv/bin/mempalace search "rawgentic" --limit 1 2>&1 | head -5`
Expected: At least one result, no errors

- [ ] **Step 6: Commit dependency bump**

```bash
git add pyproject.toml
git commit -m "feat(deps): upgrade mempalace to >=3.3.0,<4.0

Required for: BM25 hybrid search, closet layer, fact_checker,
Background Everything, layers (L0-L4), tunnels, halls."
```

### Task 4: Bulk-mine existing session notes

**Files:**
- Read: `~/rawgentic/claude_docs/session_notes/*.md`

- [ ] **Step 1: Inventory session notes**

Run: `ls ~/rawgentic/claude_docs/session_notes/*.md | wc -l`
Expected: integer count of session note files

- [ ] **Step 2: Run mempalace mine**

Run: `.venv/bin/mempalace mine ~/rawgentic/claude_docs/session_notes/ --mode general 2>&1 | tail -10`
Expected: "Mined N drawers" or similar success output

- [ ] **Step 3: Verify mining succeeded**

Run: `.venv/bin/mempalace status 2>&1 | head -10`
Expected: Drawer count increased from pre-migration snapshot

### Task 5: Bulk-mine per-project context

**Files:**
- Read: each `~/rawgentic/projects/*/docs/` and `CLAUDE.md`

- [ ] **Step 1: Mine each project**

```bash
for project_dir in ~/rawgentic/projects/*/; do
    name=$(basename "$project_dir")
    if [[ -d "$project_dir/docs" ]]; then
        echo "Mining docs for $name..."
        .venv/bin/mempalace mine "$project_dir/docs" --wing "$name" 2>&1 | tail -3
    fi
    if [[ -f "$project_dir/CLAUDE.md" ]]; then
        echo "Mining CLAUDE.md for $name..."
        .venv/bin/mempalace mine "$project_dir/CLAUDE.md" --wing "$name" 2>&1 | tail -3
    fi
done
```
Expected: Each project produces "Mined N drawers" output

- [ ] **Step 2: Verify wings created**

Run: `.venv/bin/mempalace status 2>&1`
Expected: Wing list includes project names like "sysop", "grocusave", "chorestory", etc.

- [ ] **Step 3: Test recall against known fact**

Run: `.venv/bin/mempalace search "EPYC server upgrade" --wing sysop --limit 3 2>&1`
Expected: Result mentioning Dell R7525 or EPYC 7452

- [ ] **Step 4: Snapshot post-bulk-mine state**

```bash
.venv/bin/mempalace status > docs/migration/post-bulk-mine-status.txt 2>&1
git add docs/migration/post-bulk-mine-status.txt
git commit -m "chore: snapshot post-bulk-mine palace status"
```

---

## Phase D — Build Adapter

### Task 6: Adapter test fixtures (TDD prep)

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Read existing conftest**

Run: `cat tests/conftest.py`

- [ ] **Step 2: Add adapter fixtures**

Append to `tests/conftest.py`:
```python
import os
import shutil
import tempfile
from pathlib import Path
import pytest


@pytest.fixture
def isolated_palace(tmp_path, monkeypatch):
    """Provide an isolated mempalace palace per test."""
    palace_dir = tmp_path / "palace"
    palace_dir.mkdir()
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(palace_dir))
    return palace_dir


@pytest.fixture
def mock_mempalace_unavailable(monkeypatch):
    """Simulate mempalace not being installed."""
    import sys
    real_mempalace = sys.modules.get("mempalace")
    monkeypatch.setitem(sys.modules, "mempalace", None)
    yield
    if real_mempalace is not None:
        monkeypatch.setitem(sys.modules, "mempalace", real_mempalace)


@pytest.fixture
def frozen_clock(monkeypatch):
    """Freeze time.time() to a known value for debounce tests."""
    frozen = [1700000000.0]
    monkeypatch.setattr("time.time", lambda: frozen[0])
    return frozen


@pytest.fixture
def adapter(isolated_palace):
    """Adapter instance pointing at isolated palace."""
    from rawgentic_memory.adapter import MempalaceAdapter
    return MempalaceAdapter(palace_path=str(isolated_palace))
```

- [ ] **Step 3: Verify fixtures importable**

Run: `.venv/bin/python -c "import sys; sys.path.insert(0, 'tests'); from conftest import isolated_palace, adapter"`
Expected: No import errors

- [ ] **Step 4: Commit fixtures**

```bash
git add tests/conftest.py
git commit -m "test: add adapter test fixtures (isolated palace, frozen clock, mock unavailable)"
```

### Task 7: Adapter `health()` method

**Files:**
- Create: `rawgentic_memory/adapter.py`
- Create: `tests/test_adapter.py`

- [ ] **Step 1: Write failing test for health() when mempalace available**

Create `tests/test_adapter.py`:
```python
"""Tests for MempalaceAdapter — versioned wrapper around mempalace."""
import pytest
from rawgentic_memory.adapter import MempalaceAdapter, HealthStatus


class TestHealth:
    def test_health_returns_available_when_mempalace_present(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        h = adapter.health()
        assert isinstance(h, HealthStatus)
        assert h.available is True
        assert h.backend == "mempalace"
        assert h.version  # non-empty version string

    def test_health_returns_unavailable_when_palace_missing(self, tmp_path):
        nonexistent = tmp_path / "nope"
        adapter = MempalaceAdapter(palace_path=str(nonexistent))
        h = adapter.health()
        assert h.available is False
        assert h.doc_count == 0
```

- [ ] **Step 2: Run test, verify it fails (no adapter module yet)**

Run: `.venv/bin/python -m pytest tests/test_adapter.py::TestHealth -v 2>&1 | tail -10`
Expected: ImportError or ModuleNotFoundError for `rawgentic_memory.adapter`

- [ ] **Step 3: Create adapter.py with minimal health() implementation**

Create `rawgentic_memory/adapter.py`:
```python
"""
MempalaceAdapter — versioned wrapper around mempalace's Python API.

Bridge code calls this adapter — never mempalace directly.
Major version aligned with mempalace's major version.
"""
from dataclasses import dataclass, field
from pathlib import Path
import logging
import os

logger = logging.getLogger("rawgentic_memory.adapter")


@dataclass
class HealthStatus:
    available: bool
    doc_count: int
    backend: str = "mempalace"
    version: str = ""


class MempalaceAdapter:
    CONTRACT_VERSION = 3
    MIN_VERSION = "3.3.0"
    MAX_VERSION = "4.0.0"

    def __init__(self, palace_path: str | None = None):
        self.palace_path = palace_path or os.path.expanduser("~/.mempalace/palace")

    def health(self) -> HealthStatus:
        try:
            from mempalace.palace import get_collection
            from mempalace.version import __version__ as mempalace_version
            col = get_collection(self.palace_path, create=False)
            return HealthStatus(
                available=True,
                doc_count=col.count(),
                version=mempalace_version,
            )
        except Exception as e:
            logger.debug("health check failed: %s", e)
            return HealthStatus(available=False, doc_count=0)
```

- [ ] **Step 4: Run test, verify it passes**

Run: `.venv/bin/python -m pytest tests/test_adapter.py::TestHealth -v 2>&1 | tail -10`
Expected: Both tests PASS

- [ ] **Step 5: Commit**

```bash
git add rawgentic_memory/adapter.py tests/test_adapter.py
git commit -m "feat(adapter): add MempalaceAdapter.health() with HealthStatus dataclass"
```

### Task 8: Adapter `wakeup()` method

**Files:**
- Modify: `rawgentic_memory/adapter.py`
- Modify: `tests/test_adapter.py`

- [ ] **Step 1: Add WakeupContext dataclass to adapter.py**

Append to `rawgentic_memory/adapter.py`:
```python
@dataclass
class WakeupContext:
    text: str
    tokens: int
    layers: list[str] = field(default_factory=list)
```

- [ ] **Step 2: Write failing test for wakeup()**

Append to `tests/test_adapter.py`:
```python
class TestWakeup:
    def test_wakeup_returns_l0_and_l1(self, isolated_palace):
        # Create identity file
        identity = Path(isolated_palace.parent) / "identity.txt"
        identity.write_text("Test identity for unit tests")

        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        ctx = adapter.wakeup()
        assert isinstance(ctx, WakeupContext)
        assert "L0" in ctx.layers
        assert "L1" in ctx.layers
        assert ctx.tokens > 0

    def test_wakeup_returns_empty_on_exception(self, tmp_path):
        bad_path = tmp_path / "does_not_exist"
        adapter = MempalaceAdapter(palace_path=str(bad_path))
        ctx = adapter.wakeup()
        # Even on failure, returns valid empty context
        assert isinstance(ctx, WakeupContext)
        assert ctx.tokens == 0 or ctx.text == ""
```

- [ ] **Step 3: Run test, verify it fails**

Run: `.venv/bin/python -m pytest tests/test_adapter.py::TestWakeup -v 2>&1 | tail -10`
Expected: AttributeError — `wakeup` not defined

- [ ] **Step 4: Implement wakeup() method**

Add to `MempalaceAdapter` class in `rawgentic_memory/adapter.py`:
```python
    def wakeup(self, project: str | None = None) -> WakeupContext:
        try:
            from mempalace.layers import Layer0, Layer1
            l0 = Layer0().render()
            l1 = Layer1(palace_path=self.palace_path, wing=project).generate()
            text = f"{l0}\n\n{l1}"
            # Token estimate is approximate (chars/4 ±25%) — over for code-heavy,
            # under for natural language.
            return WakeupContext(text=text, tokens=len(text) // 4, layers=["L0", "L1"])
        except Exception as e:
            logger.warning("wakeup failed: %s", e)
            return WakeupContext(text="", tokens=0, layers=[])
```

Add `from mempalace.layers import Layer0, Layer1` at the top of the file (or keep lazy-imported).

- [ ] **Step 5: Run test, verify it passes**

Run: `.venv/bin/python -m pytest tests/test_adapter.py::TestWakeup -v 2>&1 | tail -10`
Expected: Both tests PASS

- [ ] **Step 6: Commit**

```bash
git add rawgentic_memory/adapter.py tests/test_adapter.py
git commit -m "feat(adapter): add wakeup() method using mempalace Layer0+Layer1"
```

### Task 9: Adapter `search()` method with content cap and filters

**Files:**
- Modify: `rawgentic_memory/adapter.py`
- Modify: `tests/test_adapter.py`

- [ ] **Step 1: Add SearchResult dataclass**

Add to `rawgentic_memory/adapter.py`:
```python
@dataclass
class SearchResult:
    content: str
    memory_type: str = ""
    topic: str = ""
    similarity: float = 0.0
    project: str = ""
    timestamp: str = ""
    source_file: str = ""
    flag: str | None = None
```

- [ ] **Step 2: Write failing tests for search()**

Append to `tests/test_adapter.py`:
```python
class TestSearch:
    def test_search_empty_palace_returns_empty_list(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        results = adapter.search("anything")
        assert results == []

    def test_search_returns_empty_on_exception(self, mock_mempalace_unavailable):
        adapter = MempalaceAdapter(palace_path="/nonexistent")
        results = adapter.search("query")
        assert results == []

    def test_search_filters_by_memory_type(self):
        from unittest.mock import patch, MagicMock
        adapter = MempalaceAdapter(palace_path="/tmp")
        fake_results = {
            "results": [
                {"text": "decision content", "wing": "p", "memory_type": "decision"},
                {"text": "event content", "wing": "p", "memory_type": "event"},
            ]
        }
        with patch("rawgentic_memory.adapter.search_memories", return_value=fake_results):
            results = adapter.search("q", memory_type="decision")
        assert len(results) == 1
        assert results[0].memory_type == "decision"

    def test_search_truncates_long_content(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        long_text = "x" * 5000
        fake_results = {"results": [{"text": long_text, "wing": "p"}]}
        with patch("rawgentic_memory.adapter.search_memories", return_value=fake_results):
            results = adapter.search("q")
        assert len(results) == 1
        assert len(results[0].content) <= adapter.MAX_CONTENT_CHARS_PER_RESULT
        assert "[truncated]" in results[0].content
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `.venv/bin/python -m pytest tests/test_adapter.py::TestSearch -v 2>&1 | tail -15`
Expected: AttributeError — `search` not defined; ImportError on `search_memories`

- [ ] **Step 4: Implement search() with the wrapper function**

Add to `rawgentic_memory/adapter.py` near the top (module-level for mockability):
```python
try:
    from mempalace.searcher import search_memories
except ImportError:
    search_memories = None
```

Add to `MempalaceAdapter` class:
```python
    MAX_CONTENT_CHARS_PER_RESULT = 1500

    def search(
        self,
        query: str,
        project: str | None = None,
        memory_type: str | None = None,
        flag: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        try:
            if search_memories is None:
                return []
            raw = search_memories(query, self.palace_path, wing=project, n_results=limit)
            results: list[SearchResult] = []
            for h in raw.get("results", []):
                sr = SearchResult(
                    content=h.get("text", ""),
                    memory_type=h.get("memory_type", ""),
                    topic=h.get("room", ""),
                    similarity=float(h.get("similarity", 0.0)),
                    project=h.get("wing", ""),
                    timestamp=h.get("timestamp", ""),
                    source_file=h.get("source_file", ""),
                    flag=h.get("flag"),
                )
                results.append(sr)
            if memory_type:
                results = [item for item in results if item.memory_type == memory_type]
            if flag:
                results = [item for item in results if item.flag == flag]
            for item in results:
                if len(item.content) > self.MAX_CONTENT_CHARS_PER_RESULT:
                    item.content = item.content[:self.MAX_CONTENT_CHARS_PER_RESULT - 20] + "... [truncated]"
            return results
        except Exception as e:
            logger.warning("search failed: %s", e)
            return []
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `.venv/bin/python -m pytest tests/test_adapter.py::TestSearch -v 2>&1 | tail -15`
Expected: All four tests PASS

- [ ] **Step 6: Commit**

```bash
git add rawgentic_memory/adapter.py tests/test_adapter.py
git commit -m "feat(adapter): add search() with type/flag filters and content truncation"
```

### Task 10: Adapter `fact_check()` method

**Files:**
- Modify: `rawgentic_memory/adapter.py`
- Modify: `tests/test_adapter.py`

- [ ] **Step 1: Add FactIssue dataclass**

Add to `rawgentic_memory/adapter.py`:
```python
@dataclass
class FactIssue:
    type: str  # similar_name | relationship_mismatch | stale_fact
    detail: str
    entity: str = ""
    span: str = ""
```

- [ ] **Step 2: Write failing test**

Append to `tests/test_adapter.py`:
```python
class TestFactCheck:
    def test_fact_check_clean_text_returns_empty(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        issues = adapter.fact_check("This is benign text with no entity claims.")
        assert issues == []

    def test_fact_check_returns_empty_on_exception(self, tmp_path):
        adapter = MempalaceAdapter(palace_path=str(tmp_path / "missing"))
        issues = adapter.fact_check("anything")
        assert issues == []

    def test_fact_check_maps_similar_name_format(self):
        from unittest.mock import patch
        adapter = MempalaceAdapter(palace_path="/tmp")
        fake_upstream = [{
            "type": "similar_name",
            "detail": "'Mlls' mentioned — did you mean 'Milla'? (edit distance 2)",
            "names": ["Mlls", "Milla"],
            "distance": 2,
        }]
        with patch("rawgentic_memory.adapter.check_text", return_value=fake_upstream):
            issues = adapter.fact_check("Mlls said hi")
        assert len(issues) == 1
        assert issues[0].type == "similar_name"
        assert "Mlls" in issues[0].detail
```

- [ ] **Step 3: Run test, verify it fails**

Run: `.venv/bin/python -m pytest tests/test_adapter.py::TestFactCheck -v 2>&1 | tail -10`
Expected: AttributeError on `fact_check` or ImportError

- [ ] **Step 4: Implement fact_check()**

Add to `rawgentic_memory/adapter.py` near the top:
```python
try:
    from mempalace.fact_checker import check_text
except ImportError:
    check_text = None
```

Add to `MempalaceAdapter` class:
```python
    def fact_check(self, text: str) -> list[FactIssue]:
        try:
            if check_text is None:
                return []
            raw_issues = check_text(text, palace_path=self.palace_path)
            return [
                FactIssue(
                    type=i.get("type", "unknown"),
                    detail=i.get("detail", ""),
                    entity=i.get("entity", ""),
                    span=i.get("span", ""),
                )
                for i in raw_issues
            ]
        except Exception as e:
            logger.warning("fact_check failed: %s", e)
            return []
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `.venv/bin/python -m pytest tests/test_adapter.py::TestFactCheck -v 2>&1 | tail -10`
Expected: All three tests PASS

- [ ] **Step 6: Commit**

```bash
git add rawgentic_memory/adapter.py tests/test_adapter.py
git commit -m "feat(adapter): add fact_check() wrapping mempalace.fact_checker"
```

### Task 11: Adapter version validation + behavioral contract probe

**Files:**
- Modify: `rawgentic_memory/adapter.py`
- Modify: `tests/test_adapter.py`

- [ ] **Step 1: Add ContractViolation dataclass and BEHAVIORAL_CONTRACT**

Add to `rawgentic_memory/adapter.py`:
```python
@dataclass
class ContractViolation:
    field: str
    expected: str
    actual: str
    severity: str = "warning"  # info | warning | error
```

Add to `MempalaceAdapter` class:
```python
    BEHAVIORAL_CONTRACT = {
        "expected_save_interval": 15,
        "expected_palace_dir": "~/.mempalace/palace",
        "expected_kg_path": "~/.mempalace/knowledge_graph.sqlite3",
    }
```

- [ ] **Step 2: Write failing test**

Append to `tests/test_adapter.py`:
```python
class TestVersionValidation:
    def test_min_version_constant(self):
        assert MempalaceAdapter.MIN_VERSION == "3.3.0"

    def test_max_version_constant(self):
        assert MempalaceAdapter.MAX_VERSION == "4.0.0"

    def test_contract_version_constant(self):
        assert MempalaceAdapter.CONTRACT_VERSION == 3


class TestBehavioralContract:
    def test_verify_returns_list(self, isolated_palace):
        adapter = MempalaceAdapter(palace_path=str(isolated_palace))
        violations = adapter.verify_behavioral_contract()
        assert isinstance(violations, list)

    def test_verify_handles_missing_mempalace(self, mock_mempalace_unavailable, tmp_path):
        adapter = MempalaceAdapter(palace_path=str(tmp_path))
        violations = adapter.verify_behavioral_contract()
        # Returns at least one violation when mempalace is missing
        assert any(v.field == "mempalace_module" for v in violations)
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `.venv/bin/python -m pytest tests/test_adapter.py -k "Version or Behavioral" -v 2>&1 | tail -15`
Expected: First three pass on constants; behavioral contract tests FAIL on missing method

- [ ] **Step 4: Implement verify_behavioral_contract()**

Add to `MempalaceAdapter`:
```python
    def verify_behavioral_contract(self) -> list[ContractViolation]:
        violations: list[ContractViolation] = []
        try:
            import mempalace  # noqa: F401
        except ImportError:
            violations.append(ContractViolation(
                field="mempalace_module",
                expected="importable",
                actual="ImportError",
                severity="error",
            ))
            return violations

        # Check version bounds
        try:
            from mempalace.version import __version__ as v
            if v < self.MIN_VERSION:
                violations.append(ContractViolation(
                    field="mempalace_version",
                    expected=f">={self.MIN_VERSION}",
                    actual=v,
                    severity="error",
                ))
            if v >= self.MAX_VERSION:
                violations.append(ContractViolation(
                    field="mempalace_version",
                    expected=f"<{self.MAX_VERSION}",
                    actual=v,
                    severity="warning",
                ))
        except Exception:
            pass
        return violations
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `.venv/bin/python -m pytest tests/test_adapter.py -k "Version or Behavioral" -v 2>&1 | tail -15`
Expected: All five tests PASS

- [ ] **Step 6: Commit**

```bash
git add rawgentic_memory/adapter.py tests/test_adapter.py
git commit -m "feat(adapter): add version validation + behavioral contract probe"
```

### Task 12: Run full adapter test suite

- [ ] **Step 1: Run all adapter tests**

Run: `.venv/bin/python -m pytest tests/test_adapter.py -v 2>&1 | tail -25`
Expected: All ~12 tests PASS

- [ ] **Step 2: Check coverage of adapter module**

Run: `.venv/bin/python -m pytest tests/test_adapter.py --cov=rawgentic_memory.adapter --cov-report=term-missing 2>&1 | tail -10`
Expected: Coverage > 80%

---

## Phase E — Trim HTTP Server

### Task 13: Test for `/healthz` endpoint

**Files:**
- Create: `tests/test_server_slim.py`

- [ ] **Step 1: Write test using Starlette TestClient**

Create `tests/test_server_slim.py`:
```python
"""Tests for the slimmed HTTP server (post-trim)."""
import pytest
from starlette.testclient import TestClient


@pytest.fixture
def slim_app(isolated_palace, monkeypatch):
    monkeypatch.setenv("MEMPALACE_PALACE_PATH", str(isolated_palace))
    from rawgentic_memory.server import build_app
    return build_app(palace_path=str(isolated_palace))


@pytest.fixture
def client(slim_app):
    return TestClient(slim_app)


class TestHealthz:
    def test_healthz_returns_200(self, client):
        r = client.get("/healthz")
        assert r.status_code == 200

    def test_healthz_returns_status(self, client):
        r = client.get("/healthz")
        body = r.json()
        assert "available" in body
        assert "backend" in body
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestHealthz -v 2>&1 | tail -10`
Expected: ImportError or AttributeError — `build_app` not exported

### Task 14: Implement slim server with `/healthz`

**Files:**
- Modify: `rawgentic_memory/server.py` (significant rewrite)

- [ ] **Step 1: Backup the existing server.py**

Run: `cp rawgentic_memory/server.py rawgentic_memory/server.py.old-backup`

- [ ] **Step 2: Replace server.py with slim version**

Replace `rawgentic_memory/server.py` with:
```python
"""Slim HTTP server — single-process gatekeeper for ChromaDB.

Endpoints:
  GET  /healthz       — health check (cheap)
  GET  /diagnostic    — full component health (humans + monitoring)
  POST /search        — auto-recall (read-only)
  GET  /wakeup        — session-start context (read-only)
  POST /fact_check    — Layer 4 fact-checking (read-only)
  POST /canary_write  — test-only canary endpoint (write to canary wing only)

All endpoints route through the adapter. Server is single-process
because ChromaDB multi-process access is unsafe.
"""
import argparse
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
import uvicorn

from rawgentic_memory.adapter import MempalaceAdapter

logger = logging.getLogger("rawgentic_memory.server")


def build_app(palace_path: str | None = None, idle_timeout: int = 14400) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.adapter = MempalaceAdapter(palace_path=palace_path)
        app.state.last_activity = time.monotonic()
        app.state.idle_timeout = idle_timeout
        violations = app.state.adapter.verify_behavioral_contract()
        for v in violations:
            logger.warning("Contract violation: %s expected=%s actual=%s", v.field, v.expected, v.actual)
        yield

    app = FastAPI(lifespan=lifespan)

    NON_ACTIVITY_PATHS = {"/healthz", "/diagnostic"}

    @app.middleware("http")
    async def track_activity(request: Request, call_next):
        if request.url.path not in NON_ACTIVITY_PATHS:
            request.app.state.last_activity = time.monotonic()
        return await call_next(request)

    @app.get("/healthz")
    async def healthz():
        h = app.state.adapter.health()
        return asdict(h)

    return app


def run_server(port: int = 8420, palace_path: str | None = None, timeout: int = 14400):
    app = build_app(palace_path=palace_path, idle_timeout=timeout)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)
    app.state.server = server
    server.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--palace", type=str, default=None)
    parser.add_argument("--timeout", type=int, default=14400)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_server(port=args.port, palace_path=args.palace, timeout=args.timeout)
```

- [ ] **Step 3: Run test, verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestHealthz -v 2>&1 | tail -10`
Expected: Both tests PASS

- [ ] **Step 4: Commit**

```bash
git add rawgentic_memory/server.py rawgentic_memory/server.py.old-backup tests/test_server_slim.py
git commit -m "feat(server): slim server with /healthz, lifespan, adapter init"
```

### Task 15: Add `/search` endpoint

**Files:**
- Modify: `rawgentic_memory/server.py`
- Modify: `tests/test_server_slim.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_server_slim.py`:
```python
class TestSearch:
    def test_search_empty_palace_returns_empty_results(self, client):
        r = client.post("/search", json={"prompt": "anything"})
        assert r.status_code == 200
        body = r.json()
        assert body["results"] == []
        assert body["additionalContext"] == ""

    def test_search_filters_by_min_similarity(self, client, monkeypatch):
        from unittest.mock import MagicMock
        from rawgentic_memory.adapter import SearchResult
        fake_results = [
            SearchResult(content="hit A", similarity=0.8, project="p"),
            SearchResult(content="hit B", similarity=0.4, project="p"),
        ]
        client.app.state.adapter.search = MagicMock(return_value=fake_results)
        r = client.post("/search?min_similarity=0.5", json={"prompt": "q"})
        body = r.json()
        # Only the 0.8 result survives the 0.5 threshold
        assert len(body["results"]) == 1
        assert body["results"][0]["similarity"] == 0.8
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestSearch -v 2>&1 | tail -10`
Expected: 404 not found

- [ ] **Step 3: Add /search endpoint to server.py**

Inside `build_app()` in `rawgentic_memory/server.py`, after the `/healthz` endpoint:
```python
    @app.post("/search")
    async def search(request: Request, project: str | None = None,
                     min_similarity: float = 0.0, limit: int = 3):
        body = await request.json()
        query = body.get("prompt", "")
        if not query:
            return {"results": [], "additionalContext": ""}
        results = app.state.adapter.search(query=query, project=project, limit=limit)
        if min_similarity > 0:
            results = [r for r in results if r.similarity >= min_similarity]
        # Build additionalContext for hook injection
        if results:
            ctx_lines = [
                "Memory context from previous sessions (cite when these inform your response):",
                "",
            ]
            for r in results:
                date = r.timestamp[:10] if r.timestamp else "?"
                ctx_lines.append(
                    f"[{r.memory_type}] ({r.project}, {date}, sim={r.similarity:.2f})\n  {r.content}"
                )
            additional_context = "\n\n".join(ctx_lines)
        else:
            additional_context = ""
        return {
            "results": [asdict(r) for r in results],
            "additionalContext": additional_context,
        }
```

- [ ] **Step 4: Run test, verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestSearch -v 2>&1 | tail -10`
Expected: Both tests PASS

- [ ] **Step 5: Commit**

```bash
git add rawgentic_memory/server.py tests/test_server_slim.py
git commit -m "feat(server): add /search endpoint with similarity threshold + context formatting"
```

### Task 16: Add `/wakeup` endpoint

**Files:**
- Modify: `rawgentic_memory/server.py`
- Modify: `tests/test_server_slim.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_server_slim.py`:
```python
class TestWakeup:
    def test_wakeup_returns_text_and_tokens(self, client, isolated_palace):
        # Need an identity file
        identity = isolated_palace.parent / "identity.txt"
        identity.write_text("Test identity")

        r = client.get("/wakeup")
        assert r.status_code == 200
        body = r.json()
        assert "text" in body
        assert "tokens" in body
        assert "layers" in body

    def test_wakeup_with_project(self, client):
        r = client.get("/wakeup?project=sysop")
        assert r.status_code == 200
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestWakeup -v 2>&1 | tail -10`
Expected: 404 not found

- [ ] **Step 3: Add /wakeup endpoint**

Inside `build_app()`:
```python
    @app.get("/wakeup")
    async def wakeup(project: str | None = None):
        ctx = app.state.adapter.wakeup(project=project)
        return asdict(ctx)
```

- [ ] **Step 4: Run test, verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestWakeup -v 2>&1 | tail -10`
Expected: Both tests PASS

- [ ] **Step 5: Commit**

```bash
git add rawgentic_memory/server.py tests/test_server_slim.py
git commit -m "feat(server): add /wakeup endpoint"
```

### Task 17: Add `/fact_check` endpoint

**Files:**
- Modify: `rawgentic_memory/server.py`
- Modify: `tests/test_server_slim.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_server_slim.py`:
```python
class TestFactCheck:
    def test_fact_check_clean_returns_empty(self, client):
        r = client.post("/fact_check", json={"text": "no entity claims here"})
        assert r.status_code == 200
        body = r.json()
        assert body["issues"] == []
        assert body["additionalContext"] == ""

    def test_fact_check_extracts_text_from_tool_input(self, client):
        # Hooks pass full hook input; server extracts content
        hook_input = {"tool_input": {"content": "no entity claims"}}
        r = client.post("/fact_check", json=hook_input)
        assert r.status_code == 200
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestFactCheck -v 2>&1 | tail -10`
Expected: 404

- [ ] **Step 3: Add /fact_check endpoint**

Inside `build_app()`:
```python
    @app.post("/fact_check")
    async def fact_check(request: Request):
        body = await request.json()
        text = (
            body.get("text")
            or body.get("tool_input", {}).get("content")
            or body.get("tool_input", {}).get("new_string")
            or ""
        )
        if not text:
            return {"issues": [], "additionalContext": ""}
        issues = app.state.adapter.fact_check(text)
        if issues:
            ctx_lines = ["Fact-check found potential issues with this content:"]
            for i in issues:
                ctx_lines.append(f"- [{i.type}] {i.detail}")
            additional_context = "\n".join(ctx_lines)
        else:
            additional_context = ""
        return {
            "issues": [asdict(i) for i in issues],
            "additionalContext": additional_context,
        }
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestFactCheck -v 2>&1 | tail -10`
Expected: Both PASS

- [ ] **Step 5: Commit**

```bash
git add rawgentic_memory/server.py tests/test_server_slim.py
git commit -m "feat(server): add /fact_check endpoint"
```

### Task 18: Add `/diagnostic` endpoint

**Files:**
- Modify: `rawgentic_memory/server.py`
- Modify: `tests/test_server_slim.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_server_slim.py`:
```python
class TestDiagnostic:
    def test_diagnostic_returns_components(self, client):
        r = client.get("/diagnostic")
        assert r.status_code == 200
        body = r.json()
        assert "components" in body
        assert "server" in body["components"]
        assert "mempalace" in body["components"]
        assert "palace" in body["components"]
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestDiagnostic -v 2>&1 | tail -10`
Expected: 404

- [ ] **Step 3: Add /diagnostic endpoint**

Inside `build_app()`:
```python
    @app.get("/diagnostic")
    async def diagnostic():
        h = app.state.adapter.health()
        violations = app.state.adapter.verify_behavioral_contract()
        return {
            "components": {
                "server": {"healthy": True, "uptime_secs": int(time.monotonic() - app.state.last_activity)},
                "mempalace": {"available": h.available, "version": h.version},
                "palace": {"doc_count": h.doc_count},
            },
            "contract_violations": [asdict(v) for v in violations],
        }
```

- [ ] **Step 4: Run test**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestDiagnostic -v 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add rawgentic_memory/server.py tests/test_server_slim.py
git commit -m "feat(server): add /diagnostic endpoint reporting component health"
```

### Task 19: Add `/canary_write` endpoint (test-only, gated to canary wing)

**Files:**
- Modify: `rawgentic_memory/server.py`
- Modify: `tests/test_server_slim.py`

- [ ] **Step 1: Write failing tests for canary_write**

Append to `tests/test_server_slim.py`:
```python
class TestCanaryWrite:
    def test_canary_write_accepts_canary_wing(self, client):
        r = client.post("/canary_write", json={"fact": "test fact", "wing": "canary"})
        assert r.status_code == 200

    def test_canary_write_rejects_non_canary_wing(self, client):
        r = client.post("/canary_write", json={"fact": "test fact", "wing": "production"})
        assert r.status_code == 403
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestCanaryWrite -v 2>&1 | tail -10`
Expected: 404

- [ ] **Step 3: Add /canary_write endpoint**

Inside `build_app()`:
```python
    @app.post("/canary_write")
    async def canary_write(request: Request):
        body = await request.json()
        wing = body.get("wing", "")
        if wing != "canary":
            raise HTTPException(403, detail="canary_write only accepts wing=canary")
        fact = body.get("fact", "")
        if not fact:
            raise HTTPException(400, detail="missing fact")
        try:
            from mempalace.miner import add_drawer
            add_drawer(fact, wing="canary", source_file="canary.test")
            return {"status": "ok", "wing": "canary"}
        except Exception as e:
            logger.exception("canary_write failed")
            raise HTTPException(500, detail=str(e))
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestCanaryWrite -v 2>&1 | tail -10`
Expected: Both PASS

- [ ] **Step 5: Commit**

```bash
git add rawgentic_memory/server.py tests/test_server_slim.py
git commit -m "feat(server): add /canary_write endpoint (gated to canary wing)"
```

### Task 20: Verify removed endpoints return 410

**Files:**
- Modify: `tests/test_server_slim.py`

- [ ] **Step 1: Test that /ingest is gone**

Append to `tests/test_server_slim.py`:
```python
class TestRemovedEndpoints:
    def test_ingest_endpoint_not_found(self, client):
        r = client.post("/ingest", json={})
        # Either 404 (not registered) or 410 (gone)
        assert r.status_code in (404, 410)

    def test_reindex_endpoint_not_found(self, client):
        r = client.post("/reindex", json={})
        assert r.status_code in (404, 410)

    def test_kg_invalidate_not_found(self, client):
        r = client.post("/kg/invalidate", json={})
        assert r.status_code in (404, 410)
```

- [ ] **Step 2: Run tests, expect to pass already (we removed by rewriting)**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py::TestRemovedEndpoints -v 2>&1 | tail -10`
Expected: All three PASS (endpoints don't exist in slim server)

- [ ] **Step 3: Commit verification tests**

```bash
git add tests/test_server_slim.py
git commit -m "test: verify deleted endpoints (/ingest, /reindex, /kg/*) return 404"
```

### Task 21: Run full server test suite

- [ ] **Step 1: Run all slim server tests**

Run: `.venv/bin/python -m pytest tests/test_server_slim.py -v 2>&1 | tail -25`
Expected: All ~13 tests PASS

---

## Phase F — Build Hooks

### Task 22: Rewrite `hooks/lib.sh`

**Files:**
- Modify: `hooks/lib.sh` (full rewrite)

- [ ] **Step 1: Backup existing lib.sh**

Run: `cp hooks/lib.sh hooks/lib.sh.old-backup`

- [ ] **Step 2: Write the new lib.sh**

Replace `hooks/lib.sh`:
```bash
#!/bin/bash
# rawgentic-memorypalace bridge — shared hook helpers
# All thresholds env-configurable; defaults are conservative.

# === Tunable thresholds ===
RECALL_MIN_PROMPT_CHARS="${RECALL_MIN_PROMPT_CHARS:-20}"
RECALL_DEBOUNCE_SECS="${RECALL_DEBOUNCE_SECS:-60}"
RECALL_SIMILARITY_THRESHOLD="${RECALL_SIMILARITY_THRESHOLD:-0.5}"
FACT_CHECK_DEBOUNCE_SECS="${FACT_CHECK_DEBOUNCE_SECS:-30}"
RECALL_MAX_RESULTS="${RECALL_MAX_RESULTS:-3}"

# === Paths ===
MEMORY_SERVER_URL="${MEMORY_SERVER_URL:-http://127.0.0.1:8420}"
STATE_DIR="${MEMORY_STATE_DIR:-/tmp/memorypalace-state}"
PLUGIN_VENV="${PLUGIN_VENV:-${CLAUDE_PLUGIN_ROOT}/.venv}"
WORKSPACE_ROOT="${WORKSPACE_ROOT:-$HOME/rawgentic}"

mkdir -p "$STATE_DIR" 2>/dev/null

# === Health check (no startup) — fast, safe in 5s-timeout hooks ===
server_is_healthy() {
    curl -sS --max-time 1 "$MEMORY_SERVER_URL/healthz" >/dev/null 2>&1
}

# === Lazy-start — ONLY safe in 10s+ timeout hooks (session-start) ===
ensure_server_running() {
    server_is_healthy && return 0
    [[ "${MEMORY_NO_AUTOSTART:-0}" == "1" ]] && return 1

    local port=$(echo "$MEMORY_SERVER_URL" | grep -oE ':[0-9]+(/|$)' | grep -oE '[0-9]+' | head -1)
    [[ -z "$port" ]] && port=8420
    local lockfile="/tmp/memorypalace-start.lock"
    (
        flock -n 9 || exit 0
        "$PLUGIN_VENV/bin/python3" -m rawgentic_memory.server \
            --port "$port" --timeout 14400 \
            >> /tmp/memorypalace-server.log 2>&1 &
        disown
    ) 9>"$lockfile"

    for _ in $(seq 1 20); do
        sleep 0.5
        server_is_healthy && return 0
    done
    return 1
}

# === Smart gate for UserPromptSubmit ===
should_search() {
    local prompt="$1" project="$2"
    [[ ${#prompt} -lt $RECALL_MIN_PROMPT_CHARS ]] && return 1
    [[ "$prompt" == /* ]] && return 1
    local lower_prompt="${prompt,,}"
    [[ "$lower_prompt" =~ ^(commit|push|yes|no|y|n|ok|done|next|looks[[:space:]]good|lgtm|sgtm|sounds[[:space:]]good|do[[:space:]]it|go|continue)$ ]] && return 1
    local now=$(date +%s)
    local last=$(cat "$STATE_DIR/last-recall-ts-$project" 2>/dev/null || echo 0)
    [[ $((now - last)) -lt $RECALL_DEBOUNCE_SECS ]] && return 1
    return 0
}

# === Throttle gate for PostToolUse fact-check ===
should_fact_check() {
    local file_path="$1"
    [[ -z "$file_path" ]] && return 1
    local now=$(date +%s)
    local last=$(cat "$STATE_DIR/last-fact-check-ts" 2>/dev/null || echo 0)
    [[ $((now - last)) -lt $FACT_CHECK_DEBOUNCE_SECS ]] && return 1
    local session_paths_file="$STATE_DIR/fact-check-paths-$CLAUDE_SESSION_ID"
    if [[ -f "$session_paths_file" ]] && grep -Fxq "$file_path" "$session_paths_file" 2>/dev/null; then
        return 1
    fi
    return 0
}

# === Resolve active rawgentic project ===
resolve_project() {
    local registry="$WORKSPACE_ROOT/claude_docs/session_registry.jsonl"
    if [[ -f "$registry" && -n "${CLAUDE_SESSION_ID:-}" ]]; then
        local proj=$(grep -F "\"$CLAUDE_SESSION_ID\"" "$registry" 2>/dev/null \
            | tail -1 | jq -r '.project // empty' 2>/dev/null)
        [[ -n "$proj" ]] && { echo "$proj"; return; }
    fi
    jq -r '[.projects[] | select(.active==true)] | sort_by(.lastUsed) | last | .name // empty' \
        "$WORKSPACE_ROOT/.rawgentic_workspace.json" 2>/dev/null
}
```

- [ ] **Step 3: Make executable**

Run: `chmod +x hooks/lib.sh`

- [ ] **Step 4: Smoke test the lib functions**

Run:
```bash
source hooks/lib.sh
# Smart gate tests
echo -n "short prompt skip: "; should_search "short" "test" && echo "FAIL (should reject)" || echo "OK"
echo -n "long prompt accept: "; should_search "this is a longer prompt for testing" "test" && echo "OK" || echo "FAIL (should accept)"
echo -n "slash skip: "; should_search "/commit foo bar baz qux" "test" && echo "FAIL (should reject)" || echo "OK"
echo -n "case-insensitive lgtm skip: "; should_search "LGTM" "test" && echo "FAIL (should reject)" || echo "OK"
```
Expected: All four print "OK"

- [ ] **Step 5: Commit**

```bash
git add hooks/lib.sh hooks/lib.sh.old-backup
git commit -m "feat(hooks): rewrite lib.sh with env-configurable thresholds and smart gates"
```

### Task 23: Rewrite `hooks/session-start`

**Files:**
- Modify: `hooks/session-start`

- [ ] **Step 1: Backup existing**

Run: `cp hooks/session-start hooks/session-start.old-backup`

- [ ] **Step 2: Write new session-start hook**

Replace `hooks/session-start`:
```bash
#!/bin/bash
# SessionStart — wakeup context injection (Layer 0 + Layer 1)
# Allowed to lazy-start server (10s timeout budget).
set -e
source "$(dirname "$0")/lib.sh"

ensure_server_running || exit 0
PROJECT=$(resolve_project)

# URL-encode project name
ENCODED_PROJECT=$(jq -rn --arg p "${PROJECT:-}" '$p|@uri')
RESPONSE=$(curl -sS --max-time 8 "$MEMORY_SERVER_URL/wakeup?project=$ENCODED_PROJECT" 2>/dev/null)
[[ -z "$RESPONSE" ]] && exit 0

TEXT=$(echo "$RESPONSE" | jq -r '.text // empty')
[[ -z "$TEXT" ]] && exit 0

echo "$RESPONSE" | jq '{
  hookSpecificOutput: {
    hookEventName: "SessionStart",
    additionalContext: .text
  }
}'
exit 0
```

- [ ] **Step 3: Make executable**

Run: `chmod +x hooks/session-start`

- [ ] **Step 4: Smoke test**

Run:
```bash
echo '{"cwd":"/tmp","session_id":"test123","source":"startup"}' | hooks/session-start | jq .
```
Expected: Either valid JSON with hookSpecificOutput OR empty (if server not running) — no errors

- [ ] **Step 5: Commit**

```bash
git add hooks/session-start hooks/session-start.old-backup
git commit -m "feat(hooks): rewrite session-start to wakeup-only via curl /wakeup"
```

### Task 24: Rewrite `hooks/user-prompt-submit`

**Files:**
- Modify: `hooks/user-prompt-submit`

- [ ] **Step 1: Backup existing**

Run: `cp hooks/user-prompt-submit hooks/user-prompt-submit.old-backup`

- [ ] **Step 2: Write new user-prompt-submit hook**

Replace `hooks/user-prompt-submit`:
```bash
#!/bin/bash
# UserPromptSubmit — smart-gated auto-recall (Layer 2)
# Tight 5s timeout — health check only, no server startup.
set -e
source "$(dirname "$0")/lib.sh"

HOOK_INPUT=$(cat)
PROMPT=$(echo "$HOOK_INPUT" | jq -r '.prompt // empty')
PROJECT=$(resolve_project)

should_search "$PROMPT" "$PROJECT" || exit 0
server_is_healthy || exit 0

ENCODED_PROJECT=$(jq -rn --arg p "${PROJECT:-}" '$p|@uri')
RESPONSE=$(echo "$HOOK_INPUT" | curl -sS --max-time 4 \
    -H "Content-Type: application/json" \
    --data-binary @- \
    "$MEMORY_SERVER_URL/search?project=$ENCODED_PROJECT&min_similarity=$RECALL_SIMILARITY_THRESHOLD&limit=$RECALL_MAX_RESULTS" 2>/dev/null)

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

- [ ] **Step 3: Make executable**

Run: `chmod +x hooks/user-prompt-submit`

- [ ] **Step 4: Smoke test with short prompt (should skip)**

Run:
```bash
echo '{"cwd":"/tmp","session_id":"test123","prompt":"yes"}' | hooks/user-prompt-submit
echo "exit: $?"
```
Expected: No output, exit 0 (smart-gated out)

- [ ] **Step 5: Smoke test with substantive prompt**

Run:
```bash
echo '{"cwd":"/tmp","session_id":"test123","prompt":"how do I configure the deploy script for production"}' | hooks/user-prompt-submit
echo "exit: $?"
```
Expected: Either valid JSON with additionalContext OR empty (if server not running or no matches) — no errors

- [ ] **Step 6: Commit**

```bash
git add hooks/user-prompt-submit hooks/user-prompt-submit.old-backup
git commit -m "feat(hooks): rewrite user-prompt-submit as smart-gated auto-recall via curl /search"
```

### Task 25: Create `hooks/post-tool-use`

**Files:**
- Create: `hooks/post-tool-use`

- [ ] **Step 1: Write the new post-tool-use hook**

Create `hooks/post-tool-use`:
```bash
#!/bin/bash
# PostToolUse — fact-checking on writes (Layer 4)
# Throttled to bound cumulative latency in refactoring sessions.
set -e
source "$(dirname "$0")/lib.sh"

HOOK_INPUT=$(cat)
TOOL=$(echo "$HOOK_INPUT" | jq -r '.tool_name // empty')
[[ "$TOOL" =~ ^(Edit|Write|MultiEdit)$ ]] || exit 0

FILE_PATH=$(echo "$HOOK_INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')
should_fact_check "$FILE_PATH" || exit 0
server_is_healthy || exit 0

RESPONSE=$(echo "$HOOK_INPUT" | curl -sS --max-time 4 \
    -H "Content-Type: application/json" \
    --data-binary @- \
    "$MEMORY_SERVER_URL/fact_check" 2>/dev/null)

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

- [ ] **Step 2: Make executable**

Run: `chmod +x hooks/post-tool-use`

- [ ] **Step 3: Smoke test with non-Edit tool (should skip)**

Run:
```bash
echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | hooks/post-tool-use
echo "exit: $?"
```
Expected: No output, exit 0

- [ ] **Step 4: Smoke test with Edit tool**

Run:
```bash
echo '{"session_id":"test","tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.py","new_string":"safe content"}}' | hooks/post-tool-use
echo "exit: $?"
```
Expected: Either valid JSON or empty (no fact-check issues), exit 0

- [ ] **Step 5: Commit**

```bash
git add hooks/post-tool-use
git commit -m "feat(hooks): add post-tool-use hook for Layer 4 fact-checking"
```

### Task 26: Update `hooks/hooks.json`

**Files:**
- Modify: `hooks/hooks.json`

- [ ] **Step 1: Read current hooks.json**

Run: `cat hooks/hooks.json | jq .`

- [ ] **Step 2: Write new hooks.json**

Replace `hooks/hooks.json`:
```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "startup|resume",
      "hooks": [{
        "type": "command",
        "command": "${CLAUDE_PLUGIN_ROOT}/hooks/session-start",
        "timeout": 10
      }]
    }],
    "UserPromptSubmit": [{
      "hooks": [{
        "type": "command",
        "command": "${CLAUDE_PLUGIN_ROOT}/hooks/user-prompt-submit",
        "timeout": 5
      }]
    }],
    "PostToolUse": [{
      "matcher": "Edit|Write|MultiEdit",
      "hooks": [{
        "type": "command",
        "command": "${CLAUDE_PLUGIN_ROOT}/hooks/post-tool-use",
        "timeout": 5
      }]
    }]
  }
}
```

- [ ] **Step 3: Validate JSON**

Run: `jq . hooks/hooks.json`
Expected: Valid JSON output

- [ ] **Step 4: Commit**

```bash
git add hooks/hooks.json
git commit -m "feat(hooks): update hooks.json — add PostToolUse, drop Stop (mempalace handles it)"
```

### Task 27: Build bash hook test suite

**Files:**
- Create: `tests/test_lib_sh.py`

- [ ] **Step 1: Write the test file**

Create `tests/test_lib_sh.py`:
```python
"""Test bash hook helpers in lib.sh by sourcing and calling functions."""
import subprocess
import os
from pathlib import Path

LIB = Path(__file__).parent.parent / "hooks" / "lib.sh"


def run_bash(snippet: str, env: dict | None = None) -> tuple[int, str, str]:
    full_env = {**os.environ}
    if env:
        full_env.update(env)
    result = subprocess.run(
        ["bash", "-c", f"source {LIB}; {snippet}"],
        capture_output=True, text=True, env=full_env,
    )
    return result.returncode, result.stdout, result.stderr


class TestShouldSearch:
    def test_short_prompt_skipped(self):
        rc, _, _ = run_bash('should_search "short" "test"')
        assert rc != 0  # skip

    def test_long_prompt_accepted(self, tmp_path):
        rc, _, _ = run_bash(
            'should_search "this is a substantive prompt for searching" "test"',
            env={"MEMORY_STATE_DIR": str(tmp_path)},
        )
        assert rc == 0

    def test_slash_command_skipped(self):
        rc, _, _ = run_bash('should_search "/commit message here please" "test"')
        assert rc != 0

    def test_case_insensitive_lgtm_skipped(self):
        rc, _, _ = run_bash('should_search "LGTM" "test"')
        assert rc != 0

    def test_case_insensitive_looks_good_skipped(self):
        rc, _, _ = run_bash('should_search "Looks Good" "test"')
        assert rc != 0

    def test_debounce_blocks_recent(self, tmp_path):
        # Write a recent timestamp
        (tmp_path / "last-recall-ts-test").write_text(str(int(__import__("time").time())))
        rc, _, _ = run_bash(
            'should_search "this is a long prompt for testing" "test"',
            env={"MEMORY_STATE_DIR": str(tmp_path)},
        )
        assert rc != 0


class TestShouldFactCheck:
    def test_empty_path_skipped(self):
        rc, _, _ = run_bash('should_fact_check ""')
        assert rc != 0

    def test_per_file_dedup(self, tmp_path):
        session_id = "test-session"
        (tmp_path / f"fact-check-paths-{session_id}").write_text("/tmp/foo.py\n")
        rc, _, _ = run_bash(
            'should_fact_check "/tmp/foo.py"',
            env={"MEMORY_STATE_DIR": str(tmp_path), "CLAUDE_SESSION_ID": session_id},
        )
        assert rc != 0  # already checked

    def test_new_file_accepted(self, tmp_path):
        rc, _, _ = run_bash(
            'should_fact_check "/tmp/new.py"',
            env={"MEMORY_STATE_DIR": str(tmp_path), "CLAUDE_SESSION_ID": "test-session"},
        )
        assert rc == 0
```

- [ ] **Step 2: Run tests**

Run: `.venv/bin/python -m pytest tests/test_lib_sh.py -v 2>&1 | tail -20`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_lib_sh.py
git commit -m "test: add bash hook helpers test suite (should_search, should_fact_check)"
```

---

## Phase G — Integration & Canary Tests

### Task 28: Create canary test

**Files:**
- Create: `tests/canary.py`

- [ ] **Step 1: Write canary script**

Create `tests/canary.py`:
```python
"""Continuous health canary — write known fact via HTTP server, verify recall.
Safe to run during sessions because the HTTP server is the single writer.
"""
import json
import time
import fcntl
import os
import sys
import requests

CANARY_FACT = f"CANARY_{int(time.time())}: blue elephants prefer Tuesdays"
CANARY_LOCK = "/tmp/memorypalace-canary.lock"
SERVER_URL = os.environ.get("MEMORY_SERVER_URL", "http://127.0.0.1:8420")


def acquire_lock():
    fd = open(CANARY_LOCK, "w")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        print("CANARY SKIP — another canary is running")
        sys.exit(0)


def write_canary():
    r = requests.post(f"{SERVER_URL}/canary_write",
                      json={"fact": CANARY_FACT, "wing": "canary"},
                      timeout=8)
    r.raise_for_status()


def verify_recall(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.post(
            f"{SERVER_URL}/search?min_similarity=0.3&limit=5",
            json={"prompt": "blue elephants Tuesday"},
            timeout=4,
        )
        body = r.json()
        if any(CANARY_FACT in res.get("content", "") for res in body.get("results", [])):
            return True
        time.sleep(2)
    return False


def main():
    lock = acquire_lock()
    try:
        write_canary()
        if verify_recall():
            print("CANARY PASS")
            sys.exit(0)
        else:
            print("CANARY FAIL — memory pipeline broken")
            sys.exit(1)
    finally:
        lock.close()
        try:
            os.unlink(CANARY_LOCK)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test canary script (requires server running)**

Run:
```bash
# Start server in background
.venv/bin/python -m rawgentic_memory.server --port 8421 --timeout 60 &
SERVER_PID=$!
sleep 3
MEMORY_SERVER_URL=http://127.0.0.1:8421 .venv/bin/python tests/canary.py
kill $SERVER_PID 2>/dev/null
```
Expected: "CANARY PASS"

- [ ] **Step 3: Commit**

```bash
git add tests/canary.py
git commit -m "test: add canary script for continuous memory pipeline health"
```

### Task 29: Create concurrent write integration test

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_concurrent_writes.py`

- [ ] **Step 1: Create integration package**

Run: `mkdir -p tests/integration && touch tests/integration/__init__.py`

- [ ] **Step 2: Write test**

Create `tests/integration/test_concurrent_writes.py`:
```python
"""Verify concurrent write attempts don't corrupt the palace."""
import threading
import pytest
import requests
from concurrent.futures import ThreadPoolExecutor

SERVER_URL = "http://127.0.0.1:8421"


@pytest.fixture(scope="module")
def server():
    """Start a test server on port 8421."""
    import subprocess, time
    p = subprocess.Popen(
        ["python", "-m", "rawgentic_memory.server", "--port", "8421", "--timeout", "60"],
    )
    for _ in range(20):
        try:
            requests.get(f"{SERVER_URL}/healthz", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    yield
    p.terminate()
    p.wait(timeout=5)


def test_concurrent_canary_writes_are_safe(server):
    """20 concurrent writes via /canary_write must all succeed."""
    def write(i):
        return requests.post(
            f"{SERVER_URL}/canary_write",
            json={"fact": f"concurrent_test_{i}", "wing": "canary"},
            timeout=10,
        ).status_code

    with ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(write, range(20)))

    # All should succeed (200) or be deduplicated (202) — none should be 5xx
    for code in results:
        assert code < 500, f"Got server error {code}"
```

- [ ] **Step 3: Run integration test**

Run: `.venv/bin/python -m pytest tests/integration/test_concurrent_writes.py -v 2>&1 | tail -10`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_concurrent_writes.py
git commit -m "test(integration): verify concurrent canary writes don't corrupt palace"
```

### Task 30: Create graceful degradation integration test

**Files:**
- Create: `tests/integration/test_graceful_degradation.py`

- [ ] **Step 1: Write test**

Create `tests/integration/test_graceful_degradation.py`:
```python
"""Verify hooks return empty (not error) when server/mempalace unavailable."""
import os
import subprocess
from pathlib import Path

HOOKS = Path(__file__).parent.parent.parent / "hooks"


def test_session_start_returns_empty_when_server_down(tmp_path):
    env = {**os.environ, "MEMORY_NO_AUTOSTART": "1",
           "MEMORY_SERVER_URL": "http://127.0.0.1:65535",
           "MEMORY_STATE_DIR": str(tmp_path)}
    result = subprocess.run(
        [str(HOOKS / "session-start")],
        input='{"cwd":"/tmp","session_id":"t","source":"startup"}',
        capture_output=True, text=True, env=env, timeout=5,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""  # no injection when server down


def test_user_prompt_submit_returns_empty_when_server_down(tmp_path):
    env = {**os.environ,
           "MEMORY_SERVER_URL": "http://127.0.0.1:65535",
           "MEMORY_STATE_DIR": str(tmp_path)}
    result = subprocess.run(
        [str(HOOKS / "user-prompt-submit")],
        input='{"cwd":"/tmp","session_id":"t","prompt":"a substantive prompt for testing"}',
        capture_output=True, text=True, env=env, timeout=5,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_post_tool_use_returns_empty_when_server_down(tmp_path):
    env = {**os.environ,
           "MEMORY_SERVER_URL": "http://127.0.0.1:65535",
           "MEMORY_STATE_DIR": str(tmp_path),
           "CLAUDE_SESSION_ID": "test"}
    result = subprocess.run(
        [str(HOOKS / "post-tool-use")],
        input='{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.py","new_string":"x"}}',
        capture_output=True, text=True, env=env, timeout=5,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest tests/integration/test_graceful_degradation.py -v 2>&1 | tail -10`
Expected: All three PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_graceful_degradation.py
git commit -m "test(integration): verify hooks degrade gracefully when server unavailable"
```

### Task 31: Create hook timeout compliance test

**Files:**
- Create: `tests/integration/test_hook_timeouts.py`

- [ ] **Step 1: Write test**

Create `tests/integration/test_hook_timeouts.py`:
```python
"""Verify all hooks complete within their declared timeouts."""
import os
import subprocess
import time
from pathlib import Path

HOOKS = Path(__file__).parent.parent.parent / "hooks"


def test_session_start_completes_within_10s(tmp_path):
    env = {**os.environ, "MEMORY_NO_AUTOSTART": "1",
           "MEMORY_SERVER_URL": "http://127.0.0.1:65535",
           "MEMORY_STATE_DIR": str(tmp_path)}
    start = time.time()
    subprocess.run(
        [str(HOOKS / "session-start")],
        input='{"cwd":"/tmp","session_id":"t","source":"startup"}',
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert time.time() - start < 10


def test_user_prompt_submit_completes_within_5s(tmp_path):
    env = {**os.environ,
           "MEMORY_SERVER_URL": "http://127.0.0.1:65535",
           "MEMORY_STATE_DIR": str(tmp_path)}
    start = time.time()
    subprocess.run(
        [str(HOOKS / "user-prompt-submit")],
        input='{"cwd":"/tmp","session_id":"t","prompt":"long prompt for substantive search"}',
        capture_output=True, text=True, env=env, timeout=5,
    )
    assert time.time() - start < 5


def test_post_tool_use_completes_within_5s(tmp_path):
    env = {**os.environ,
           "MEMORY_SERVER_URL": "http://127.0.0.1:65535",
           "MEMORY_STATE_DIR": str(tmp_path),
           "CLAUDE_SESSION_ID": "test"}
    start = time.time()
    subprocess.run(
        [str(HOOKS / "post-tool-use")],
        input='{"tool_name":"Edit","tool_input":{"file_path":"/tmp/foo.py","new_string":"x"}}',
        capture_output=True, text=True, env=env, timeout=5,
    )
    assert time.time() - start < 5
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest tests/integration/test_hook_timeouts.py -v 2>&1 | tail -10`
Expected: All three PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_hook_timeouts.py
git commit -m "test(integration): verify hook timeout compliance under cold-start conditions"
```

### Task 32: Run full test suite before cutover

- [ ] **Step 1: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v --ignore=tests/test_enrichment.py --ignore=tests/test_mempalace_backend.py --ignore=tests/test_kg_endpoints.py --ignore=tests/test_reindex.py 2>&1 | tail -30`
Expected: All new/modified tests PASS; old tests excluded

---

## Phase H — Atomic Cutover

### Task 33: Pre-cutover backup and inventory

- [ ] **Step 1: Snapshot current state**

```bash
mkdir -p /tmp/cutover-backup
cp ~/.claude/settings.json /tmp/cutover-backup/settings.json.before
cp hooks/hooks.json /tmp/cutover-backup/hooks.json.before
ps aux | grep -E '(rawgentic_memory|mempalace)' | grep -v grep > /tmp/cutover-backup/processes.before
```

- [ ] **Step 2: Confirm rollback readiness**

Run:
```bash
ls -la /tmp/cutover-backup/
echo "---"
git log --oneline -5
```
Expected: backups exist; git history has all r1, r2, r3, and implementation commits

### Task 34: Stop old server processes

- [ ] **Step 1: Stop systemd service if exists**

Run:
```bash
systemctl --user stop rawgentic-memorypalace.service 2>/dev/null && echo "stopped systemd" || echo "no systemd service"
systemctl --user disable rawgentic-memorypalace.service 2>/dev/null
```

- [ ] **Step 2: Kill any lingering server processes**

Run:
```bash
pkill -f 'rawgentic_memory.server' || echo "no processes to kill"
sleep 1
ps aux | grep rawgentic_memory | grep -v grep || echo "no rawgentic_memory processes running"
```

### Task 35: Register mempalace MCP server

- [ ] **Step 1: Register MCP server**

Run:
```bash
claude mcp add mempalace -- python -m mempalace.mcp_server 2>&1
```
Expected: success message

- [ ] **Step 2: Verify registration**

Run: `claude mcp list 2>&1 | grep mempalace`
Expected: mempalace listed

### Task 36: Install mempalace native hooks in user settings

- [ ] **Step 1: Find mempalace hook paths**

Run:
```bash
MEMPAL_HOOK_DIR=$(.venv/bin/python -c "import mempalace, os; print(os.path.dirname(mempalace.__file__))")/hooks
ls $MEMPAL_HOOK_DIR
```
Expected: `mempal_save_hook.sh` and `mempal_precompact_hook.sh` exist

- [ ] **Step 2: Read current settings**

Run: `jq '.hooks' ~/.claude/settings.json`

- [ ] **Step 3: Add mempalace native hooks via jq merge**

```bash
MEMPAL_HOOK_DIR=$(.venv/bin/python -c "import mempalace, os; print(os.path.dirname(mempalace.__file__))")/hooks

jq --arg save "$MEMPAL_HOOK_DIR/mempal_save_hook.sh" \
   --arg pre "$MEMPAL_HOOK_DIR/mempal_precompact_hook.sh" \
   '.hooks.Stop = (.hooks.Stop // []) + [{"matcher":"*","hooks":[{"type":"command","command":$save,"timeout":30}]}] |
    .hooks.PreCompact = (.hooks.PreCompact // []) + [{"hooks":[{"type":"command","command":$pre,"timeout":30}]}]' \
   ~/.claude/settings.json > /tmp/settings.json.new
mv /tmp/settings.json.new ~/.claude/settings.json
```

- [ ] **Step 4: Verify mempalace hooks added**

Run: `jq '.hooks.Stop, .hooks.PreCompact' ~/.claude/settings.json`
Expected: shows mempal_save_hook.sh and mempal_precompact_hook.sh entries

### Task 37: Run canary verification

- [ ] **Step 1: Start fresh server**

Run: `.venv/bin/python -m rawgentic_memory.server --port 8420 --timeout 14400 >> /tmp/memorypalace-server.log 2>&1 &`

- [ ] **Step 2: Wait for healthz**

Run:
```bash
for i in $(seq 1 20); do
    sleep 0.5
    curl -sS --max-time 1 http://127.0.0.1:8420/healthz && break
done
```
Expected: JSON response with `available: true`

- [ ] **Step 3: Run canary**

Run: `.venv/bin/python tests/canary.py`
Expected: "CANARY PASS"

- [ ] **Step 4: Run diagnostic**

Run: `curl -sS http://127.0.0.1:8420/diagnostic | jq .`
Expected: All components healthy, doc_count > 0, no contract violations (or only warnings)

- [ ] **Step 5: Commit cutover state**

```bash
cp ~/.claude/settings.json docs/migration/settings.json.after-cutover
git add docs/migration/settings.json.after-cutover
git commit -m "chore(cutover): snapshot settings.json after atomic cutover"
```

---

## Phase I — Cleanup

### Task 38: Delete obsolete code (after cutover verified for one full session)

- [ ] **Step 1: Verify cutover stable for one full session**

Manually open a new Claude session, send 2-3 substantive prompts, verify wakeup + auto-recall fire.

- [ ] **Step 2: Delete obsolete Python modules**

```bash
git rm rawgentic_memory/enrichment.py
git rm rawgentic_memory/mempalace_backend.py
git rm rawgentic_memory/models.py
git rm rawgentic_memory/server.py.old-backup
```

- [ ] **Step 3: Delete obsolete tests**

```bash
git rm tests/test_enrichment.py
git rm tests/test_mempalace_backend.py
git rm tests/test_kg_endpoints.py
git rm tests/test_reindex.py
```

- [ ] **Step 4: Delete obsolete hooks**

```bash
git rm hooks/stop
git rm hooks/lib.sh.old-backup
git rm hooks/session-start.old-backup
git rm hooks/user-prompt-submit.old-backup
```

- [ ] **Step 5: Verify nothing imports deleted modules**

Run: `grep -rn "from rawgentic_memory.enrichment\|from rawgentic_memory.mempalace_backend\|from rawgentic_memory.models" rawgentic_memory/ tests/ 2>&1 | grep -v __pycache__`
Expected: No matches

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -25`
Expected: All remaining tests PASS

- [ ] **Step 7: Commit deletion**

```bash
git commit -m "feat(cleanup): delete obsolete enrichment, backend, models, old hooks

Replaced by:
- mempalace's general_extractor + Save Hook AI classification
- adapter.py (versioned wrapper)
- Slim server.py (4 endpoints)
- mempalace native Stop + PreCompact hooks"
```

---

## Phase J — Skills + Documentation

### Task 39: Update CLAUDE.md with memory instruction

**Files:**
- Modify: `CLAUDE.md` (project-level)

- [ ] **Step 1: Read current CLAUDE.md**

Run: `cat CLAUDE.md`

- [ ] **Step 2: Append memory section**

Append to `CLAUDE.md`:
```markdown

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
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add Memory section to CLAUDE.md instructing proactive MCP tool use"
```

### Task 40: Update rawgentic workflow skills

**Files:**
- Modify: `~/rawgentic/projects/rawgentic/skills/brainstorming/SKILL.md` (or wherever it lives)
- Modify: similar for implement-feature, fix-bug, refactor

- [ ] **Step 1: Locate skill files**

Run: `find ~/rawgentic/projects/rawgentic/skills/ -name "SKILL.md" 2>&1 | head -10`

- [ ] **Step 2: Add memory step to brainstorming**

For `brainstorming/SKILL.md`, add as a new first step:
```markdown
0. **Search mempalace for related context.** Call `mempalace_search` with
   the brainstorm topic. Surface any prior decisions, preferences, or
   architectural context that would shape the discussion. If you find
   prior work that conflicts with the user's framing, raise it before
   proposing approaches.
```

- [ ] **Step 3: Add memory step to implement-feature**

For `implement-feature/SKILL.md`, add after context gathering:
```markdown
**Search mempalace** for known gotchas, prior architecture decisions, and
related implementations in this area. Use `mempalace_search` with the
feature topic and `mempalace_kg_query` for entity-specific facts. Reference
findings explicitly when designing the implementation.
```

- [ ] **Step 4: Add memory step to fix-bug**

For `fix-bug/SKILL.md`, add as a new first step:
```markdown
0. **Search mempalace for bug history.** Call `mempalace_search` with
   the symptom and any error messages. Past similar bugs often have
   documented root causes and fixes.
```

- [ ] **Step 5: Add memory step to refactor**

For `refactor/SKILL.md`, add early:
```markdown
**Search mempalace for prior decisions about this area** before refactoring.
Past architectural choices (especially DECISION-flagged drawers) often
explain why code looks the way it does. Avoid undoing decisions that have
documented reasoning.
```

- [ ] **Step 6: Commit**

```bash
cd ~/rawgentic/projects/rawgentic
git add skills/
git commit -m "feat(skills): add mempalace memory search steps to brainstorming, implement-feature, fix-bug, refactor"
```

### Task 41: Update README

**Files:**
- Modify: `README.md` (rawgentic-memorypalace)

- [ ] **Step 1: Read current README**

Run: `cat README.md`

- [ ] **Step 2: Update README with new architecture**

Edit `README.md` to describe:
- Three-plugin architecture
- Adapter pattern (CONTRACT_VERSION = 3)
- Four recall layers
- Migration from r1/r2 plugins
- Troubleshooting (link to spec)

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README for r3 architecture (three-plugin split, adapter, 4 layers)"
```

### Task 42: Final verification + PR

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v 2>&1 | tail -30`
Expected: All tests PASS (>= 30 tests across adapter, server, lib, integration)

- [ ] **Step 2: Run canary one more time**

Run: `.venv/bin/python tests/canary.py`
Expected: "CANARY PASS"

- [ ] **Step 3: Verify diagnostic**

Run: `curl -sS http://127.0.0.1:8420/diagnostic | jq .`
Expected: All components healthy

- [ ] **Step 4: Push branch and open PR**

```bash
git push -u origin feature/mempalace-integration-redesign
GH_TOKEN=$(cat ~/.secrets/github-pat) gh pr create --title "feat: mempalace integration redesign (r3)" --body "$(cat <<'EOF'
## Summary

Implements the redesign spec at `docs/superpowers/specs/2026-04-14-mempalace-integration-redesign.md` (r3).

- Three-plugin architecture (rawgentic + mempalace MCP + bridge)
- Adapter pattern (CONTRACT_VERSION=3, MIN_VERSION=3.3.0)
- Four recall layers: wakeup, auto-recall, proactive MCP, fact-checking
- Slim HTTP server (~100 LOC, READ-only) as ChromaDB single-process gatekeeper
- Mempalace native Stop + PreCompact hooks handle ingest
- Atomic cutover migration with per-phase rollback

## Test plan

- [ ] All adapter unit tests pass (12 tests)
- [ ] All server endpoint tests pass (13 tests)
- [ ] All bash hook tests pass (8 tests)
- [ ] Concurrent write integration test passes
- [ ] Graceful degradation integration test passes
- [ ] Hook timeout compliance test passes
- [ ] Canary test passes
- [ ] Diagnostic endpoint reports all healthy

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Checklist

After implementing this plan, verify against the spec:

- [ ] **Adapter** — all 4 methods (search, wakeup, fact_check, health) + behavioral contract probe. CONTRACT_VERSION=3, MIN/MAX bounds enforced.
- [ ] **HTTP server** — ~100 lines, 6 endpoints (healthz, search, wakeup, fact_check, diagnostic, canary_write). READ-only for non-canary.
- [ ] **Hooks** — 3 bash hooks (session-start, user-prompt-submit, post-tool-use). lib.sh has env-configurable thresholds, smart_gate, fact_check_throttle, server_is_healthy vs ensure_server_running split.
- [ ] **Mempalace native hooks** — Save (every 15 messages) + PreCompact registered in `~/.claude/settings.json`.
- [ ] **MCP server** — registered via `claude mcp add mempalace`.
- [ ] **Identity file** — `~/.mempalace/identity.txt` populated from rawgentic workspace.
- [ ] **MEMPAL_DIR** — set in `~/.bashrc` for background mining.
- [ ] **Bulk-mine** — session notes + per-project docs+CLAUDE.md mined into wings.
- [ ] **Tests** — 12 adapter + 13 server + 8 lib.sh + 3 graceful + 1 concurrent + 3 timeout + 1 canary = 41 tests.
- [ ] **Deletions** — enrichment.py, mempalace_backend.py, models.py, hooks/stop, related test files all removed.
- [ ] **Skills** — 4 rawgentic skills updated with memory-search steps.
- [ ] **CLAUDE.md** — Memory section added.
- [ ] **Backups** — palace backup, settings.json backup, server.py.old-backup created and accessible for rollback.
