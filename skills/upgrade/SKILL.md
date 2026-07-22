---
name: rawgentic-memorypalace:upgrade
description: Upgrade mempalace everywhere it runs on this host and reconcile the live memory server(s) — every install (pipx, user/system pip, plugin venv, the project server venv, and the Docker image) AND the running memory-server services — then verify the palace data survived. Assesses the release changelog for breaking changes and backs up the palace BEFORE touching anything. Use when the user says "upgrade mempalace", "update the memory server", "reconcile the memory palace version", or "get the palace on the latest".
argument-hint: "[target-version]  (optional; default = latest on PyPI)"
---

<role>
You are the MemPalace upgrade + reconciliation assistant. A host can run mempalace
in SEVERAL places at once — a pipx CLI, a project server `.venv`, a plugin `.venv`,
a Docker image — and one or more long-lived HTTP servers hold the live palace. A
naive `pipx upgrade` leaves the running server on the OLD version. Your job: assess
the changelog for anything that breaks OUR deployment, back the palace up, upgrade
EVERY install, restart EVERY server, and prove the data survived. Never leave the
host in a split-version state.
</role>

# /rawgentic-memorypalace:upgrade — Upgrade + Reconcile MemPalace

Do the steps in order. Steps 2 (changelog gate) and 5 (backup) run BEFORE any
mutation. Do not skip the verification in Step 7 — a green restart is not proof the
palace survived.

## Step 1: Determine the target version

- If the user passed a version argument, that is the target.
- Else read the latest from PyPI:
  ```bash
  python3 -m pip index versions mempalace 2>/dev/null | head -1
  ```
- Record the target. You will compare every install and server against it.

## Step 2: Assess the changelog — GATE before upgrading

The whole point of "make sure nothing breaks": read the release notes and actually
check them against how WE run mempalace.

1. Fetch the target release notes and scan for danger sections:
   ```bash
   python3 - <<'PY'
   import json, urllib.request, re
   TARGET = "3.6.0"  # <-- the Step 1 target
   req = urllib.request.Request(
       "https://api.github.com/repos/MemPalace/mempalace/releases?per_page=12",
       headers={"Accept": "application/vnd.github+json", "User-Agent": "upgrade"})
   for r in json.load(urllib.request.urlopen(req, timeout=20)):
       if r.get("tag_name","").lstrip("v") == TARGET:
           body = r.get("body","") or ""
           print(body[:6000])
           hits = re.findall(r"(?im)^#{1,4}.*(break|migrat|remov|deprecat|BREAKING).*$", body)
           print("\n=== DANGER HEADINGS ===")
           print("\n".join(hits) if hits else "none found")
           break
   PY
   ```
2. **Validate OUR API surface still resolves** against the new version. The project
   server (`rawgentic_memory/`) imports a specific slice of mempalace; a renamed or
   removed symbol would break the server even on a "minor" bump. Install the target
   into a throwaway check (or use a host install already on the target) and run:
   ```bash
   <python-on-target> -c "
   import importlib
   for mod,attr in [('mempalace.palace','get_collection'),
                    ('mempalace.palace_graph','find_tunnels'),
                    ('mempalace.palace_graph','follow_tunnels'),
                    ('mempalace.searcher','search_memories'),
                    ('mempalace.fact_checker','check_text'),
                    ('mempalace.miner','add_drawer'),
                    ('mempalace.version','__version__')]:
       m=importlib.import_module(mod); assert hasattr(m,attr), f'{mod}.{attr} MISSING'
   import mempalace.mcp_server  # noqa
   print('API surface OK on target')"
   ```
   (Keep this list in sync with `grep -rhE 'from mempalace|import mempalace' rawgentic_memory/`.)
3. **Gate:**
   - **Major version bump** (X.y.z → (X+1).0.0), OR a non-empty DANGER heading, OR a
     broken API-surface check → STOP. Present the findings and ask the user before
     proceeding. This may include breaking API changes; the memory server and clients
     may need config changes.
   - Minor/patch with a clean surface check → note the highlights and proceed.

## Step 3: Enumerate EVERY mempalace install on this host

Do not stop at the first hit — find them all, record path + current version each:

```bash
echo "=== pipx ===" && pipx list 2>/dev/null | grep -A1 "mempalace" || echo "not in pipx"
echo "=== user/system pip ===" && python3 -c "import mempalace,sys; print(mempalace.__version__, sys.executable)" 2>/dev/null || echo "not in python3"
echo "=== plugin venv ===" && PLUGIN_VENV=$(jq -r '.plugins["rawgentic-memorypalace@rawgentic-memorypalace"][0].installPath' ~/.claude/plugins/installed_plugins.json 2>/dev/null) && "$PLUGIN_VENV/.venv/bin/python3" -c "import mempalace; print(mempalace.__version__)" 2>/dev/null || echo "not in plugin venv"
echo "=== Docker images ===" && docker images 2>/dev/null | grep -iE "memory|palace" || echo "no docker images"
```

The project server `.venv` is resolved from the running server's cmdline in Step 4.
Each install at or above the target is already done; each below the target is a
reconcile target for Step 6.

## Step 4: Enumerate the running memory server(s) + pre-upgrade state

The servers are what actually hold the palace. Find them, their install source, their
RUNNING version, and the drawer count BEFORE the upgrade (so Step 7 can prove no loss):

```bash
echo "=== listeners ==="; ss -tlnp 2>/dev/null | grep -E ":8420|:8765|:8099" || sudo -n ss -tlnp 2>/dev/null | grep -E ":8420|:8765|:8099"
echo "=== systemd units ==="; systemctl list-units --type=service --all 2>/dev/null | grep -iE "memor|palace"
echo "=== :8420 healthz (authoritative MEMORY_SERVER_URL) ==="; curl -s -m8 http://127.0.0.1:8420/healthz
echo "=== :8765 healthz (MCP owner) ==="; curl -s -m8 -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/healthz
```

Known topology on the memory host (10.0.17.205, `claude-code`):
- **`rawgentic-memorypalace.service`** → `.venv/bin/python -m rawgentic_memory.server --host 0.0.0.0 --port 8420` — the authoritative `MEMORY_SERVER_URL` endpoint; mempalace comes from the **project `.venv`** (`projects/rawgentic-memorypalace/.venv`). Resolve the venv path from `/proc/<pid>/cmdline`.
- **`mempalace-mcp-http.service`** → host **pipx** `mempalace-mcp --transport http --host 127.0.0.1 --port 8765` — loopback MCP owner.

**If the server runs on a DIFFERENT host** than the one you are on (`hostname -I` does
not include the server IP), do the whole reconcile over `ssh <host>` instead — the
upgrade only helps where the server actually runs.

## Step 5: Back up the palace — BEFORE any upgrade or restart

A server-backed palace is irreplaceable. Snapshot it first (cheap; ~150M):

```bash
BK=~/.mempalace/backups/pre-<target>-$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$BK"
cp -a ~/.mempalace/config.json ~/.mempalace/knowledge_graph.sqlite3* "$BK"/ 2>/dev/null
tar -C ~/.mempalace -czf "$BK/palace.tar.gz" palace && echo "backed up to $BK"
```

Record the backup path — it is the rollback anchor if Step 7 finds data loss.

## Step 6: Upgrade every install to the target

Run the matching command for each install found in Steps 3–4 (upgrade ALL of them,
not one):

| Install | Upgrade command |
|--------|----------------|
| pipx | `pipx upgrade mempalace` |
| user/system pip | `pip install --upgrade mempalace` |
| plugin venv | `<plugin-venv>/bin/pip install --upgrade "mempalace<4"` |
| project server venv | `<project>/.venv/bin/pip install --upgrade "mempalace<4"` |

Pin `"mempalace<4"` on the venvs so a future major (which the Step 2 gate must review)
is never pulled silently. Re-check each with
`… -c "import mempalace; print(mempalace.__version__)"` and confirm it equals the target.

## Step 7: Restart each server and VERIFY the data survived

Upgrading the files on disk does nothing until the long-lived server restarts. For
each server, restart and then prove three things — version bumped, no drawers lost,
integrity clean:

```bash
sudo -n systemctl restart rawgentic-memorypalace.service && sleep 4
curl -s -m8 http://127.0.0.1:8420/healthz     # expect version==target, doc_count >= pre-count
sudo -n systemctl restart mempalace-mcp-http.service && sleep 4
curl -s -m8 -o /dev/null -w "8765: %{http_code}\n" http://127.0.0.1:8765/healthz   # expect 200
```

Then reconnect the palace and confirm integrity through the MCP layer this session
uses (external CLI/restarts can leave the in-memory index stale):
- `mcp__mempalace__mempalace_reconnect` → `success: true`, drawers >= pre-count.
- `mcp__mempalace__mempalace_status` → `sqlite_integrity.ok == true`, `error_count == 0`.

**If doc_count dropped, healthz stays on the old version, or integrity fails →** the
restart did not land cleanly. STOP, report, and offer to restore from the Step-5
backup (`systemctl stop` the writers, replace `~/.mempalace/palace` from `palace.tar.gz`
and the KG sqlite files, restart). Do NOT declare success.

## Step 8: Reconcile the Docker image + pin (if present)

A memory-server Docker image (`docker images | grep memory`) carries its OWN mempalace
baked at build time, independent of the host installs. It only matters if the palace
is served from the container (`docker ps`). If it is — rebuild so the pin resolves to
the target: `cd deploy && docker compose build memory-server && docker compose up -d`.
If the container is NOT running (the palace is served by the systemd `.venv` process),
note the stale image as a follow-up rather than rebuilding. The pyproject pin
`mempalace>=3.3.5,<4.0` already admits any 3.x target — leave it unless the target is 4.x.

## Step 9: Report

```
## MemPalace Upgraded + Reconciled  (v{old} -> v{new})

Changelog gate: {clean | highlights | STOPPED-for-breaking}
Installs updated:  pipx {a->b}, project .venv {a->b}, plugin venv {...}, docker {...|skipped}
Servers restarted: :8420 {ver, drawers pre->post}, :8765 {ver, 200}
Integrity:         sqlite_integrity ok, drawers {pre}->{post} (no loss)
Backup:            {backup path}
Follow-ups:        {stale docker image / remote host / pin / new features to consider}
```

Report old->new for EVERY install and EVERY server. If any surface was left behind (a
remote host you could not reach, a container you did not rebuild), say so explicitly —
a partial reconcile that reads as complete is the failure this skill exists to prevent.
A **major version** change stays a hard STOP at Step 2: never upgrade across a major
without the user's go-ahead, because the memory server and its clients may need
migration.
