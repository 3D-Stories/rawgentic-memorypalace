---
name: rawgentic-memorypalace:upgrade
description: Upgrade the mempalace dependency to the latest version. Displays old and new version numbers, warns on major version changes.
argument-hint: No arguments needed
---

<role>
You are the dependency upgrade assistant. Your job is to safely upgrade the mempalace pip package and report the results.
</role>

# /upgrade — Upgrade MemPalace Dependency

Upgrade the mempalace library that powers the memory backend.

## Instructions

### 1. Get Current Version

Use the Bash tool to capture the current version:

```bash
python3 -c "import mempalace; print(mempalace.__version__)" 2>/dev/null || echo "NOT_INSTALLED"
```

If `NOT_INSTALLED`, tell the user mempalace is not installed and suggest `pip install mempalace`. STOP.

### 2. Run the Upgrade

```bash
pip install --upgrade mempalace 2>&1
```

### 3. Get New Version

```bash
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
```

**If the major version changed** (e.g., 3.x → 4.x):
```
⚠️ **Major version change detected** (v{old_major} → v{new_major}).
This may include breaking API changes. Check the mempalace changelog
before restarting sessions. The memory server may need updates.
```

### 5. Verify the Upgrade

Run a quick import check to confirm the upgrade didn't break anything:

```bash
python3 -c "from mempalace.miner import get_collection; from mempalace.searcher import search_memories; from mempalace.layers import MemoryStack; print('All imports OK')"
```

If verification fails, warn the user that the upgrade may have broken compatibility.

STOP after reporting results. Do NOT restart any servers.
