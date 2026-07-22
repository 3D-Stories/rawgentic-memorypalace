# Memory Retention, Decay & Promotion Design (2026-07-08)

Companion to the audit
([`docs/reviews/2026-07-08-memory-system-audit.md`](../reviews/2026-07-08-memory-system-audit.md)).
Design goal: make every session compound into the next. Constraint honored throughout:
**mempalace stays the authoritative read/write memory store** (owner decision
2026-07-05); CLAUDE.md and session_notes stay in-repo because tooling reads them;
auto-memory dir stays secondary. This design changes *curation and flow*, not ownership.

Principles: one home per fact, pointers elsewhere. Every layer must have BOTH a
resurfacing path and a decay path — a layer with only capture is a graveyard. Prefer
rules enforceable by hooks that already exist; new infrastructure is specced as
follow-up issues, not built here.

---

## 1. Promotion ladder

A fact climbs exactly one rung at a time; each rung has an entry criterion and a home.

| Rung | Home | Enters when | Mechanism |
|---|---|---|---|
| L0 | `.remember/today-*.md` | Anything notable happens | Existing PostToolUse staging (unchanged) |
| L1 | `.remember/recent.md` → `archive.md` | Survives Haiku consolidation | Existing (unchanged) |
| L2 | mempalace drawer / `kg_add` | Recurred in ≥2 sessions, OR cost-of-forgetting is high (a gotcha that burned >30 min), OR cross-project relevance | Consolidation prompt gains a "promote?" pass: when merging a daily into recent, items meeting the criteria are written via `mempalace_add_drawer` (prose) or `mempalace_kg_add` (fact with relationships). This closes the audit's F6 gap: `.remember` insights currently die in archive.md |
| L3 | MEMORY.md index line | **Proven reuse**: the memory demonstrably changed a later session's behavior (once telemetry exists — §3; until then, the session's own judgment at save time) | Manual, budget-gated (§4) |
| L4 | CLAUDE.md rule | It is *process* — something that must bind even when no recall fires | Owner-visible PR only, never automatic |

Demotion is the same ladder downward: an index line whose body file is never read in 90
days drops to mempalace-only (pointer removed, drawer kept).

## 2. Decay & eviction rules

**R1 — Quarantine bulk documentation from recall (fixes F1).** The `documentation` room
(18,731 drawers, 93% of the palace, 87% of all injections) is repo docs — the repo is
its own source of truth and grep beats embeddings there. Exclude it from the
UserPromptSubmit `/search` path by default (server-side room exclusion, or an
`X-Exclude-Rooms: documentation` header set in `hooks/user-prompt-submit`). It stays
searchable explicitly (`mempalace_search room=documentation`).

**R2 — Dormant-wing damping (fixes F1).** Wings of retired/dormant projects (`millions`,
`clawd`, `daimonia`, `snowgate`, …) are excluded from cross-project recall unless the
bound project matches or the query names them. Implementation: a `dormant: true` flag
per wing honored by `/search`; list maintained in the server config.

**R3 — Recall threshold 0.30 → 0.45 (fixes F1).** Median injected similarity is 0.49 —
the current threshold admits mostly-noise. Raising to 0.45 cuts roughly the worse half.
Env-configurable already (`RECALL_SIMILARITY_THRESHOLD`, `hooks/lib.sh:37`); change the
default, keep the override.

**R4 — Time-damped ranking for episodic rooms.** `diary` and session-summary rooms decay
in recall *ranking* after 90 days (content retained; rank multiplier only). `decisions`
and `reference` never time-decay — they die only by supersession (R5).

**R5 — Correction protocol (fixes F3, F10).** A fact change is not done until all copies
move: (1) `mempalace_update_drawer` on the canonical drawer, (2) `mempalace_kg_invalidate`
+ `kg_add` for the supersession chain, (3) auto-memory body file edited or deleted with
its index line, (4) grep for remaining assertions of the old value
(`docs/`, session_notes). Enforcement: a nightly consistency check (follow-up issue)
that greps auto-memory descriptions against their palace canonical and reports drift —
report-only, never auto-edit.

**R6 — Retire `closet_boost` for bulk-ingested rooms (fixes F3).** A +0.4 boost lifted a
2025 aspirational doc above verified reality. Boosts apply only to curated rooms
(`decisions`, `reference`, `gotchas`).

**R7 — MEMORY.md hard budget (fixes F4, F8).** Cap ~120 lines / ~5k tokens (currently
124 lines / 4.85k — at cap). Adding a line requires removing or merging one. Orphan
body files (not indexed) are moved into mempalace and deleted from the dir monthly.

## 3. The missing primitive: retrieval telemetry (fixes F2)

Neither decay nor promotion can be usage-informed while nothing records usage. Spec (one
follow-up issue in this repo): a `retrievals` SQLite table (memory_id, query_hash, rank,
similarity, channel ∈ {hook, mcp}, ts) written by `/search` and the MCP search path.
Cheap (one INSERT per result row), local, no schema migration of the palace itself.
Unlocks: R4's ranking signal, L3's "proven reuse" criterion, dead-drawer reports
("never retrieved in 180d"), and honest future audits.

## 4. Injection budget (fixes F5, F8)

- **Session start:** total guaranteed memory load ≤ 20k tokens (measured today: 18.1k).
  Any new always-loaded content must name what it displaces.
- **Per-prompt recall:** the server caps `additionalContext` at **8 KB** with a final
  line `[+N more above threshold — mempalace_search to see them]`. Never emit a payload
  the harness will persist-to-file (~10 KB observed limit) — a truncated pointer the
  model may never follow is worse than fewer, complete memories.
- **`.remember` injection:** consolidation keeps identity+core+today+now+recent+archive
  under 8 KB combined; when over, archive.md compresses first (it is already the
  compression tier).

## 5. Scoping fix (fixes F9)

`resolve_project()` must resolve the *session's own* binding: read
`claude_docs/session_registry.jsonl` for the newest line whose `session_id` matches the
hook input's `session_id` (hooks receive it on stdin). Fallback order: session registry
→ workspace `lastUsed` (current behavior, now explicitly a fallback) → literal
`"unscoped"` (never `basename(cwd)` — no more `prompts`/`tmp` wings).

## 6. Dedup discipline (fixes F10)

- One home per fact: the mempalace drawer is canonical; MEMORY.md lines and CLAUDE.md
  rules are pointers/derivations, and say so.
- `mempalace_check_duplicate` runs on semantic chunks, not full-file text with
  frontmatter (0.9 full-text flagged 0 dups across a 197-file backfill that
  demonstrably contained ≥4 copies of one fact). Threshold per-chunk ≈ 0.85.
- Existing near-dups: one-time merge pass over `decisions`/`reference` rooms (follow-up
  issue; report-first, owner approves merges).

## 7. Follow-up issues to file (implementation is NOT this audit's scope)

1. rawgentic-memorypalace: retrieval telemetry table + `/search` and MCP write path (§3).
2. rawgentic-memorypalace: room/wing exclusion + dormant flag + boost scoping (R1, R2, R6).
3. rawgentic-memorypalace: `resolve_project` session-scoped resolution (§5).
4. rawgentic-memorypalace: recall payload 8 KB cap + "+N more" trailer (§4).
5. rawgentic-memorypalace: nightly consistency check, report-only (R5).
6. remember-plugin (or wrapper): consolidation "promote?" pass writing to mempalace (§1 L2).
7. Workspace docs: correction-protocol checklist added to the workspace CLAUDE.md (R5) —
   owner PR.

## 8. What this design deliberately does NOT do

- No new memory store, no re-architecture — the layers stay; their flow changes.
- No auto-deletion anywhere; decay is ranking/exclusion, eviction is report-first.
- No relitigation of mempalace authority, CLAUDE.md-as-contract, or session_notes
  append-only.
