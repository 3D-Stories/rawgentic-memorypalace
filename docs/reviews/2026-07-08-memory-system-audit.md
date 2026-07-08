# Memory System Audit — Learning or Hoarding? (2026-07-08)

**Verdict: ACCUMULATING.** The workspace gets genuinely smarter only through its
always-loaded file layers (CLAUDE.md tiers, MEMORY.md index, `.remember` injection).
The 20,155-drawer semantic layer (mempalace) is noise-dominated, carries stale facts
it actively re-serves as truth, and has no feedback loop that could tell anyone which
memories are ever used. Capture works everywhere; resurfacing works only where content
is force-loaded; curation exists nowhere except `.remember`'s consolidation pipeline.

Audit scope: rawgentic workspace (`/home/rocky00717/rawgentic/`), all memory layers,
session-bound to rawgentic-memorypalace. Method: live server interrogation (MCP tools),
source reads of every hook in the capture/recall path, and quantitative analysis of all
114 Claude Code transcripts in the workspace project dir. Every load-bearing claim below
is marked **[confirmed]** with its evidence or **[inferred]** with what would confirm it.

---

## 1. Layer inventory — capture vs. resurfacing

| Layer | Captured by | Resurfaced by | Verdict |
|---|---|---|---|
| mempalace (20,155 drawers) | Stop/PreCompact hooks (MCP writes), bulk doc ingest, 07-05 backfill | UserPromptSubmit `/search` injection; manual MCP search | Noise-dominated recall; no usage telemetry |
| Auto-memory dir (217 files + MEMORY.md) | Manual Writes by sessions | MEMORY.md auto-load (index only); body via explicit Read | 82% of body files never read |
| `.remember/` | PostToolUse staging | SessionStart injects identity+core+today+now+recent+archive | Healthiest layer: capture + decay + resurfacing all work |
| session_notes/ (56 files) | Manual, append-only | Explicit Read when a session knows to look | 42/56 write-only |
| CLAUDE.md tiers | Owner/PR edits | Loaded verbatim every session | Works; used as overflow for facts other layers can't resurface |
| KG (mempalace) | `mempalace_kg_add` | `kg_query`/fact-check hook | 14 triples vs 20,155 drawers — effectively unused |

## 2. Findings

### F1 — The recall channel is noise-dominated **[confirmed]**
Across 114 transcripts: **15,398** `[memory]` injection items. **87%** (13,427) came from
the `documentation` room — wholesale-ingested repo docs. Dead/dormant projects supply a
quarter of everything injected: `millions` 2,804 + `clawd` 1,363. Median similarity of
injected items: **0.49** against a threshold of 0.30 (`hooks/lib.sh:37`,
`RECALL_SIMILARITY_THRESHOLD=0.30`, max 5 results).
Evidence: regex count over `~/.claude/projects/-home-rocky00717-rawgentic/*.jsonl`
(counts approximate — compaction summaries can repeat items; direction unaffected).
Qualitative sample: both injections in the audit session itself top-ranked a stale
`clawd` "Clawdbot" doc (sim 0.95–0.99) for a question about *this* workspace's memory.

### F2 — Nothing tracks whether a memory is ever used **[confirmed]**
No hit/retrieval/access counting exists in the mempalace 3.5.0 package
(`~/.local/share/pipx/venvs/mempalace/.../mempalace/*.py` — grep clean), in
`rawgentic_memory/server.py`, or in the server log (`/var/log/rawgentic-memorypalace.log`,
46,635 lines: HNSW mtime warnings, zero request logs). The question "which of the 18,731
documentation drawers were ever retrieved" is **unanswerable from system state** — the
audit's transcript mining is the only proxy, and it can't see MCP-side searches (stdio,
unlogged). This missing primitive blocks any usage-informed decay or promotion.

### F3 — Stale facts are re-served as truth; correction doesn't propagate **[confirmed]**
Trace: chorestory RLS. The palace's *top-ranked* result for "chorestory RLS inert
superuser bypassrls" (similarity 0.967 after a +0.4 `closet_boost`) is a **November 2025
aspirational schema doc** claiming "✅ RLS at database level" — ranked *above* the
verified-live drawer that documents RLS as bypassed. The backfilled reference drawer
still asserts RLS is inert "in BOTH dev and prod," though the dev flip went live
2026-07-03. Same rot in the auto-memory body file
(`reference_chorestory_rls_inert_app_superuser.md` description) — the MEMORY.md index
line was annotated "STALE-for-dev" but the body wasn't corrected. KG invalidation exists
(`mempalace_kg_invalidate`) but is effectively unused: **1 expired fact palace-wide**
(kg_stats: 25 entities, 14 triples, 13 current). The `closet_boost` mechanism amplifies
bulk-doc noise: it lifted a 0.567-raw match to top rank.

### F4 — Auto-memory is 82% write-only **[confirmed]**
217 body files (1.1 MB). Transcript analysis of actual `Read` tool calls: only **40
distinct body files ever read** across 114 sessions (63 sessions read ≥1). The index
(`MEMORY.md`, 19.4 KB ≈ 4,850 tokens) loads every session and was itself read 155 more
times. 2 orphan files aren't in the index at all
(`feedback_board_updates_timestamped.md`,
`reference_studio_gui_resume_broken_perphase_completedpackage.md`). The 07-08 laptop
migration merged in entries that now contradict a local directive in the same index
(line 17: laptop `subagent-model-routing` vs. local no-multiagent-workflows, flagged
only by a "cf." note).

### F5 — Memory delivery silently truncates at the harness boundary **[confirmed]**
Both memory systems overflowed the inline hook-output threshold in a single session
(2026-07-08): the `.remember` SessionStart injection (11.1 KB) and a mempalace recall
payload (10.2 KB) were persisted to files with only ~2 KB previews reaching context.
The systems "resurfaced" the memory; the harness delivered a pointer. Nothing alerts on
this, and the memory is effectively lost unless the model chooses to Read the file.

### F6 — `.remember` is the healthiest layer **[confirmed]**
Full pipeline exists and runs: PostToolUse staging → `today-*.md` → Haiku consolidation
into `recent.md` (7d) → compressed `archive.md`
(`remember/0.8.3/scripts/run-consolidation.sh`), with SessionStart injecting all tiers
including archive. ~60 dailies renamed `.done.md` prove consolidation fires. Its
weaknesses are F5 (delivery truncation) and that its content never promotes anywhere —
insights die in `archive.md` (2.4 KB, compressed) instead of graduating to mempalace or
MEMORY.md.

### F7 — session_notes handoffs work only when a session knows to look **[confirmed]**
56 files; **14 ever read**. Reads concentrate where CLAUDE.md/MEMORY.md point at the
file by name (`3dstories-studio.handoff.md`: 44 reads). The other 42 files are
write-only history. A memory that requires prior knowledge of its own existence is
functionally dead — these survive only via their pointer lines in always-loaded layers.

### F8 — Guaranteed session-start memory load ≈ 18,100 tokens **[confirmed]**
operating-instructions.md 4,457 + workspace CLAUDE.md 5,375 + MEMORY.md 4,852 +
`.remember` injection 2,824 + global CLAUDE.md 302 + context7 rule 327 ≈ **18.1k tokens
every session**, before mode hooks (caveman/ponytail/superpowers/learning add more) and
before mempalace L0/L1. This is the de-facto injection budget, and it is already at a
sensible ceiling — every new always-loaded line now competes with the others.

### F9 — Recall scoping is wrong under concurrency **[confirmed in code; live impact inferred]**
`hooks/lib.sh resolve_project()`: primary path picks the **globally most-recently-used
active project** from the workspace registry — not this session's binding — so
concurrent sessions bound to different projects mis-scope each other's recall (same bug
class as the documented `.current_session_id` hazard). Fallback is `basename(cwd)`:
debounce state files for bogus "projects" `prompts`, `skills`, `docs`, `tmp`,
`competitors`, `reviews` prove it fires in practice. Confirming live mis-scoping would
need two concurrent bound sessions and MEMORY_DEBUG traces.

### F10 — Duplication is systemic; dedup as implemented can't catch it **[confirmed]**
The memory-policy fact alone exists in ≥6 places: 4 mempalace drawers
(`auto-memory-backfill-206`, `docs/memory-source-of-truth.md` ×2 chunks,
`session-2026-07-05-owner-quotes`), the auto-memory body file, and the MEMORY.md index
line. The 07-05 backfill dedup-checked 197 files at threshold 0.9 over *full file text
with frontmatter* and flagged **zero** duplicates. Even the server URL is written two
ways (global CLAUDE.md: `10.0.17.205:8420`; project CLAUDE.md: `127.0.0.1:8420` — same
box, divergent spellings; 8 facts traced in total, all multi-copy).

## 3. Smarter vs. accumulating — the ratio

**Smarter (all via always-loaded layers):** this audit session itself used
`$CLAUDE_CODE_SESSION_ID` + the expansion-free bind (avoiding the documented
`.current_session_id` bug and a permission prompt) straight from workspace CLAUDE.md +
memory; the chorestory CI-polling gotcha, the overnight-watchdog pattern, and the
never-Haiku rule demonstrably steer sessions. **[confirmed by this session's own
behavior + memory annotations]**

**Accumulating:** zero observed cases in sampled transcripts where a mempalace
*semantic search* changed a session's behavior; today's two recall injections were both
irrelevant; the top-ranked answer on a real operational question (RLS) was a stale
aspiration. **[inferred — sampled, not exhaustive; F2 makes exhaustive measurement
impossible, which is the point]**

The system's real learning loop is: session → owner-visible lesson → **manually
promoted** to CLAUDE.md/MEMORY.md → force-loaded forever. That loop works but doesn't
scale (F8: the budget is spent), and everything below it accumulates without compounding.

## 4. Not checked

- MCP-side (stdio) mempalace query frequency — unlogged (F2), invisible to transcripts
  from other workspaces.
- Quality of the 10,175-drawer chorestory wing (only the RLS trace sampled it).
- Whether Stop-hook save instructions reliably result in MCP writes
  (`silent_save=true` path) — capture completeness unverified.
- Memory behavior on other machines / other workspace dirs (only
  `-home-rocky00717-rawgentic` transcripts mined).
- Qualitative relevance of injections beyond two sessions (quantitative distribution
  only).

## 5. Companion design

Retention, decay, and promotion rules that address F1–F10:
[`docs/planning/2026-07-08-memory-retention-decay-promotion-design.md`](../planning/2026-07-08-memory-retention-decay-promotion-design.md).
