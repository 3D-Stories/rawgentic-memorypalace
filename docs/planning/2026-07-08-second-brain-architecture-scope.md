# Second-Brain Architecture & Implementation Scope (2026-07-08)

Companion to the research report
([`docs/reviews/2026-07-08-memory-brain-research.md`](../reviews/2026-07-08-memory-brain-research.md))
and the audit ([`2026-07-08-memory-system-audit.md`](../reviews/2026-07-08-memory-system-audit.md), F1–F10).
Owner direction (2026-07-08): best long-term solution wins over quickest; self-hosted;
human readability not required; must answer "remind me about the decision we made on xyz".
Owner approved revisiting the 2026-07-05 "mempalace authoritative" decision up to and
including full replacement. **Owner decision #304 (2026-07-08, same day) additionally
fixes the authority model: the brain (mempalace today, its successor after this program)
is the authoritative read+write long-term memory, and Claude Code auto-memory
`MEMORY.md` files are FROZEN thin pointer indexes — no new substantive content lands
there.** This scope conforms: the native layer is a pointer index + demand-loaded
caches derived FROM the brain, never a content authority.
**Scope only — implementation happens through the epic below.**

## Target architecture: native-first working memory + typed second brain

```
CLAUDE.md tiers (contract)                 [unchanged — loaded verbatim]
        │
Native auto-memory (working memory)        [Claude Code v2.1.59+: MEMORY.md index
  ~/.claude/projects/<ws>/memory/           200-line/25KB cap, topic files on demand,
                                            model-curated at write, compaction-safe]
        │  promote-pass (scheduled, A-MEM-style)
        ▼
SECOND BRAIN (durable, self-hosted, .205)  [typed records: decision / gotcha /
  MCP tools + HTTP for hooks                reference / diary / session-state
  ENGINE CHOSEN BY PHASE-0 BAKE-OFF         bi-temporal supersession
                                            dedup-at-write (semantic chunk ~0.85)
                                            retrieval telemetry (every search logged)
                                            typed TTL decay (session-state 90d;
                                            decisions/gotchas durable, die by
                                            supersession only)]
        │  explicit recall ONLY
        ▼
"remind me about the decision on xyz"  →  typed search + timeline (validity intervals)
```

**Retired:** the per-prompt semantic auto-inject channel (audit F1: 87% noise, ~zero
proven behavioral value). Replaced by (a) native MEMORY.md always-loaded index,
(b) explicit brain recall (model-initiated or user-asked), (c) optional ≤200-token
session-start brain digest (L0), budget-capped, behind a flag.

**Kept unchanged:** CLAUDE.md tiers as contract; `.remember` capture/consolidation
pipeline (audit's healthiest layer) — gains a promote-pass output; session_notes/WAL
run-state; capture triggers stay compaction-first (PreCompact primary, 2h timer,
Stop as flush only — historical: 3 stops per 371 tool calls).

**Audit rules mapping:** implements R5 (correction protocol → bi-temporal supersession +
`invalidate` MCP tool), R7 (MEMORY.md budget → native 200-line cap), telemetry spec (§3
of the design), injection budget (§4 → native cap + 8KB recall cap), scoping fix (§5).
Supersedes R1–R3/R6 (quarantines/thresholds/boosts) by retiring the channel they patch.
Ladder L0–L4 survives with new homes: L0/L1 `.remember` (unchanged) → L2 brain typed
record → L3 native MEMORY.md index line → L4 CLAUDE.md rule (owner PR).

## Engine bake-off (Phase 0 — the "best > quickest" mechanism)

Candidates, each behind the same thin storage interface:
1. **keep-ChromaDB**: current palace collection as-is (zero migration for the bake-off)
2. **mem0-OSS**: owner's existing container (locate it first — not on .205;
   `docker ps -a` empty for mem0)
3. **custom-lean**: sqlite-vec (or pgvector) + typed SQLite schema — the "boring
   swappable store" baseline

Judged on OUR data with the repo's existing ground-truth R@1/R@5 framework plus a new
owner-query set (20 real "remind me about…" questions harvested from history):
recall precision, latency, ops footprint on .205, and integration cost. The engine is
the commodity layer — if two candidates tie, the lower-maintenance one wins.

## Migration (one-time, after engine selection)

- **Migrate (typed)**: curated rooms only — decisions (388), reference (442),
  process-conventions (122), gotchas (15), diary (81) ≈ ~1,050 drawers, re-typed and
  dedup-checked at semantic-chunk level (the 0.9 full-text check provably missed ≥4
  copies of one fact).
- **Deliberately NOT migrated**: the `documentation` room (18,731 drawers — repos are
  their own source of truth; grep beats embeddings there) and dormant wings
  (`millions`, `clawd`, `daimonia`, …). The palace directory is retained read-only as
  a cold archive until the 30-day review passes, then archived to disk.
- Auto-memory dir (217 files): curated into native topic files + index during E6; the
  ~1,050-drawer overlap deduped against brain records.

## Packaging & coupling (owner directive 2026-07-08)

The brain is **standalone from rawgentic** — the same pattern rawgentic-memorypalace
uses today: its own repo, its own Claude Code plugin (hooks + MCP server + skills),
its own service on .205, usable in ANY Claude Code workspace with zero rawgentic
dependency. rawgentic couples to it only through optional integration points (its
hooks call the brain's HTTP/MCP API if present; graceful degradation if absent —
the existing `server_is_healthy` + exit-0 pattern). Natural home: this repo
(rawgentic-memorypalace) evolves into the brain — it already has the plugin scaffold,
hooks, HTTP server, tests, and deploy story; rename is a cosmetic decision for E4.
Nothing in the brain may import from or assume the rawgentic plugin; the
`session_registry.jsonl` session-scoping integration (E7) lives on the rawgentic side
of the boundary, with a plain-cwd fallback when no registry exists.

## rawgentic integration map

| Surface | Change |
|---|---|
| memorypalace bridge `hooks/user-prompt-submit` | retire auto-inject (flag first, delete after 30-day review) |
| `hooks/lib.sh resolve_project()` | session-scoped: match hook stdin `session_id` against `session_registry.jsonl`; drop `basename(cwd)` fallback (F9) |
| `hooks/session-start` | optional ≤200-tok brain digest, budget-capped |
| Stop/PreCompact wrapper | unchanged trigger shape; writes go to brain API |
| `.remember` consolidation | promote-pass: qualifying items → typed brain writes (recurred ≥2 sessions / burned >30min / cross-project) |
| mempalace MCP toolset | replaced by brain MCP: `brain_search`, `brain_timeline`, `brain_remember`, `brain_invalidate`, `brain_stats` (names final at E4) |
| rawgentic plugin (WF skills, WAL, guards) | untouched |
| CLAUDE.md memory sections | updated once at E8 (correction-protocol checklist + new tool names) |

## Epic breakdown (WF2-sized; telemetry lands FIRST)

| # | Issue | Delivers | Test strategy | Size |
|---|---|---|---|---|
| E1 | Retrieval telemetry on CURRENT stack | `retrievals` SQLite table; `/search` + MCP search log (memory_id, query_hash, rank, sim, channel, ts); `stats` endpoint | unit + integration on live server; 7 days of baseline data is the exit gate | S |
| E2 | Owner-query eval set + harness | 20 real "remind me…" queries + graded answers, stratified over LongMemEval-V2's five agent-memory abilities (static state recall, dynamic state tracking, workflow knowledge, environment gotchas, premise awareness — arXiv 2605.12493); runs against any engine via the storage interface; reuses ground-truth R@1/R@5 framework | the harness IS the test; red on empty engine | S |
| E3 | Engine bake-off (spike, time-boxed) | scored matrix: keep-Chroma vs mem0-OSS vs custom-lean on E2 set + ops cost; DECISION RECORD | evaluation report, owner sign-off on engine | M |
| E4 | Brain service v1 (STANDALONE plugin+service in this repo) | typed schema, bi-temporal supersession, dedup-at-write, MCP tools, telemetry native from day one (E1 schema); zero rawgentic imports; works in any Claude Code workspace | TDD; contract tests on the storage interface; supersession red-before-green; a no-rawgentic-workspace smoke test | L |
| E5 | Curated migration | ~1,050 typed drawers in; documentation room + dormant wings excluded; reversible (source untouched) | migration dry-run diff + spot-check sample; count reconciliation | M |
| E6 | Auto-memory freeze & pointerization (per owner #304) | 217-file dir content migrated INTO the brain; MEMORY.md rewritten as a frozen thin pointer index (≤ native 200-line/25KB cap) whose entries point at brain records; topic files become brain-derived read caches or are deleted | line/size budget guard test; pointer↔brain-record consistency check; guard that flags new substantive content added to MEMORY.md | M |
| E7 | Capture rewire | promote-pass in `.remember` consolidation; hooks point at brain; auto-inject retired behind flag; `resolve_project` session-scoped | hook bats/pytest incl. concurrent-session scoping test (F9 red-before-green) | M |
| E8 | 30-day review gate | telemetry report vs kill criteria; flag flip permanent or rollback; CLAUDE.md docs updated; palace cold-archived | the report itself; owner decision recorded | S |

Order: E1 → E2 → E3 (owner gate) → E4 → E5..E7 (parallelizable) → E8.
E1/E2 start immediately — they instrument the CURRENT system, so even a stalled program
leaves the audit's #1 gap closed.

## Kill criteria (measured by E1 telemetry, judged at E8)

New design must beat the instrumented baseline within 30 days or roll back:
1. **Used-recall rate**: ≥30% of explicit brain retrievals are cited/used in the
   session's subsequent work (baseline auto-inject: unmeasurable, est. ≈0).
2. **Noise**: <10% of injected/recalled items from bulk-doc or dormant sources
   (baseline: 87% + 27%).
3. **Owner-query accuracy**: ≥80% on the E2 set (baseline measured in E3).
4. **Token cost**: session-start memory load ≤ current 18.1k; per-prompt recall
   payload ≤ 8KB always.
5. **Staleness**: zero known-superseded facts served as current in E8 spot-check
   (baseline: RLS case live).
Rollback path: flag re-enables auto-inject; palace archive is untouched until E8 passes.

## Not in scope

- Cross-machine memory sync; Obsidian vault view (store stays plain-text-exportable —
  possible later at near-zero cost); RL-trained memory controllers; changing CLAUDE.md
  contract semantics or the `.remember` plugin's internals beyond the promote-pass hook.
