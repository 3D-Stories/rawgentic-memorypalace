---
name: rawgentic-memorypalace:upgrade
description: Upgrade the mempalace dependency to the latest version. Displays old and new version numbers, warns on major version changes.
argument-hint: No arguments needed
---

<role>
You are the dependency upgrade assistant. Your job is to safely upgrade the mempalace package and report the results.
</role>

# /rawgentic-memorypalace:upgrade — Upgrade MemPalace Dependency

Upgrade the mempalace library that powers the memory backend.

## Instructions

### 1. Detect Install Method

mempalace can be installed via pipx, pip, or the plugin's own .venv. Run this to detect which:

```bash
echo "=== pipx ===" && pipx list 2>/dev/null | grep -A1 "mempalace" || echo "not in pipx"
echo "=== pip (user) ===" && python3 -c "import mempalace; print(mempalace.__version__)" 2>/dev/null || echo "not in python3"
echo "=== plugin venv ===" && PLUGIN_VENV=$(jq -r '.plugins["rawgentic-memorypalace@rawgentic-memorypalace"][0].installPath' ~/.claude/plugins/installed_plugins.json 2>/dev/null) && "$PLUGIN_VENV/.venv/bin/python3" -c "import mempalace; print(mempalace.__version__)" 2>/dev/null || echo "not in plugin venv"
```

Determine the install method:
- **pipx:** `pipx list` shows `package mempalace X.Y.Z` → use `pipx upgrade mempalace`
- **pip (user/system):** `python3 -c "import mempalace"` succeeds → use `pip install --upgrade mempalace`
- **plugin venv:** plugin venv python can import it → use `<plugin-venv>/bin/pip install --upgrade mempalace`
- **None found:** tell the user mempalace is not installed and suggest `pipx install mempalace` (preferred) or `pip install --user mempalace`. STOP.

Record the current version from whichever method succeeds.

### 2. Run the Upgrade

Use the appropriate command based on detected install method:

| Method | Upgrade command |
|--------|----------------|
| pipx | `pipx upgrade mempalace` |
| pip (user/system) | `pip install --upgrade mempalace` |
| plugin venv | `<plugin-venv-path>/bin/pip install --upgrade mempalace` |

### 3. Get New Version

Re-check the version using the same Python that had mempalace:

```bash
# For pipx:
~/.local/bin/mempalace --version 2>/dev/null || ~/.local/share/pipx/venvs/mempalace/bin/python3 -c "import mempalace; print(mempalace.__version__)"

# For pip:
python3 -c "import mempalace; print(mempalace.__version__)"
```

### 4. Compare and Report

Compare the old and new version strings.

**If versions are the same:**
```
mempalace is already up to date (v{version}).
```

**If versions differ:**
```
## MemPalace Upgraded

- **Old version:** v{old_version}
- **New version:** v{new_version}
- **Install method:** {pipx|pip|plugin venv}
```

**If the major version changed** (e.g., 3.x → 4.x):
```
⚠️ **Major version change detected** (v{old_major} → v{new_major}).
This may include breaking API changes. Check the mempalace changelog
before restarting sessions. The memory server may need updates.
```

### 5. Verify the Upgrade

Run a quick import check using the correct Python to confirm the upgrade didn't break anything:

```bash
# Use the same python that has mempalace (pipx venv, system python3, or plugin venv)
<python> -c "from mempalace.miner import get_collection; from mempalace.searcher import search_memories; from mempalace.layers import MemoryStack; print('All imports OK')"
```

If verification fails, warn the user that the upgrade may have broken compatibility.

STOP after reporting results. Do NOT restart any servers.
