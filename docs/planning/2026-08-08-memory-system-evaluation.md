# Memory-system evaluation — 12 criteria, 10 candidates, 5 combinations

**The answer in one line: no single product beats what we have — but two combinations do, and
the highest-scoring path keeps MemPalace as the capture layer and builds around it.** MemPalace
as it stands today scores 29 of 50 and is the measured baseline. The best single product
(Graphiti, 30) beats it by one point on paper. The pragmatic winners are combinations:
harden-MemPalace (41) and MemPalace-plus-txtai-shadow (36) are buildable this month, and the
full event-sourced stack (47) is the ceiling if the seams prove themselves.

```verdict
ship | Run the txtai shadow index (C1) and the hygiene hardening (C0) now — together they cover 10 of 12 criteria and neither touches the capture path.
risk | Every combination score is a DESIGN grade — nothing but the baseline has been measured on this host.
risk | The criteria deliberately omit two axes that matter: build effort and upstream governance. They are reported beside the scores, never inside them.
```

## Where these criteria came from

Three lists were written independently on 2026-08-08 — one by this session, one by GPT-5.6
(Sol), one by qwen3.8-max — from the same facts and failure history, with none seeing another's
list. Five themes appeared in all three. The owner then added the three consumer-side criteria
the machinery-focused lists had missed: agent usability, data hygiene (dedup + lifecycle), and
consolidation. The merged set is 12 criteria in three ranked tiers.

Every tier-1 and tier-2 criterion traces to a failure measured in this workspace this month —
none is speculative.

## The 12 criteria

### Tier 1 — usefulness gates (weight ×3). Fail one, the system is out

| # | Criterion | The test |
| --- | --- | --- |
| 1 | **Agent-usable retrieval.** A Claude, GPT or qwen agent mid-task gets the right memory into context in 1–2 tool calls, without knowing the storage schema. | Ten task questions whose answers live in memory, asked by a FRESH agent over MCP. Pass = right memory in ≤2 calls for 8 of 10, inside a fixed token budget, across two model families. |
| 2 | **Automatic, crash-safe, concurrent capture with cross-project isolation.** | Kill the writer mid-save: nothing acknowledged is lost. Run concurrent sessions: zero contention errors, zero cross-project hits. |
| 3 | **Local-first, deny-by-default egress.** | Block outbound network. Capture and recall still work. Zero outbound packets carry memory content. |
| 4 | **Staleness-aware retrieval with a cohort ceiling.** | Fixed 20-query set: stale results under 5% of top-10, no ingestion cohort over 20% of top-10, full top-10 fill retained. |
| 5 | **Provenance on every record** — writer, timestamp, source, session. | Sample 100 records; all carry writer, timestamp and source. An audit like #74 is a query, not archaeology. |

### Tier 2 — hygiene gates (weight ×2)

| # | Criterion | The test |
| --- | --- | --- |
| 6 | **Deduplication** at write or by scheduled pass. | Write identical content twice: one record survives or the duplicate is linked. Lint asserts zero duplicate content hashes corpus-wide. |
| 7 | **Lifecycle archival by policy** — archive, never delete. | A policy ("unrecalled N days and superseded") moves records to archive. Default recall excludes them; explicit recall finds them. |
| 8 | **Honest tooling.** Non-zero exits on incomplete work; every displayed count reconciles against the store. | Run each mutating command against an empty scope: exit ≠ 0. Every surfaced count equals a direct store query, zero tolerance. |

### Tier 3 — scored differentiators (weight ×1)

| # | Criterion | The test |
| --- | --- | --- |
| 9 | **Consolidation** — memories combine into higher-order thoughts, with source citations. | Seed 5 related memories. After a consolidation pass, a synthesis record cites all 5, and topic recall returns it above its fragments. |
| 10 | **Closed predicate vocabulary + supersede-at-a-boundary.** | A triple with an unknown predicate is rejected. An as-of query at a supersede boundary returns exactly one value. |
| 11 | **Export and rebuild.** Engine-neutral export; every index rebuilds from it. | Export, wipe, rebuild in a clean environment: hashes match, fixed query set returns the same results. |
| 12 | **MCP surface for read AND write** — a preference and tiebreaker, not a gate. | List and call the tools from two different MCP clients. |

**Scoring.** Pass = 2, partial = 1, fail = 0, unverified = 0 (listed as an evidence gap, never
silently folded into fail). Tier weights ×3 / ×2 / ×1. Maximum = 50.

## Three evidence classes — read every grade through this

```chips
mempalace baseline | done
single products | wip
combinations | plan
```

- **Measured (M)** — tested on this host, this month. Only the MemPalace baseline qualifies.
- **Paper (P)** — confirmed from the product's own repository or documentation, fetched live.
- **Design (D)** — a grade for an architecture that exists as a sketch, not a deployment.

A combination scoring 47 on design is a weaker claim than a baseline scoring 29 on measurement.
The scoreboard says which is which.

## Baseline: MemPalace 3.6.0 as it stands — 29/50, all grades Measured

Post-#77: 22,129 drawers, 51 wings, 74 rooms, `documentation` reduced from 84.7% to 1,736
drawers, `archive` separable at query time.

| # | Criterion | Grade | Evidence |
| --- | --- | :-: | --- |
| 1 | Agent-usable retrieval | ~1 | ~29 MCP tools exist and are used daily. The 10-question fresh-agent test has never run. Pre-fix, 73.5% of hits were stale-cohort. |
| 2 | Capture | ~1 | 3,209 drawers in 4 months, hands-free. But writer-lease contention observed, and cross-project scoping bug #54 is open. |
| 3 | Local-first | ✓2 | Local MiniLM embeddings, no API key anywhere in the path. |
| 4 | Staleness-aware | ~1 | No decay or recency weighting (independent analysis + our measurement). The `archive` exclusion lever now exists but is manual. |
| 5 | Provenance | ✓2 | `added_by`, `filed_at`, `source_file` on records. Caveat: 1,140 drawers carry no source. |
| 6 | Dedup | ~1 | `add_drawer` checks duplicates per its contract. Corpus-wide hash audit never run. |
| 7 | Lifecycle archival | ✗0 | Nothing ages anything. #77 was a one-time manual move. |
| 8 | Honest tooling | ~1 | Upstream web UI displayed 243,857 "drawers"; the real count is 23,558 (measured). Our own added tools are now tested honest. |
| 9 | Consolidation | ✗0 | Structurally absent — #74: drawers accumulate until a human re-files them. |
| 10 | Vocabulary + supersede | ~1 | Supersede works (2-for-2 measured, zero drift). Vocabulary open: 144 predicates over 164 triples. |
| 11 | Export/rebuild | ~1 | `exporter.py` ships (markdown, no wikilinks). A rebuild drill has never run. |
| 12 | MCP | ✓2 | In production use daily. |

Tier sums: T1 = 7×3 = 21 · T2 = 2×2 = 4 · T3 = 4×1 = 4 → **29/50**.

## Single products

### Graphiti (Zep) — 30/50, Paper

The only single product to out-score the baseline, by one point.

| # | Grade | Note |
| --- | :-: | --- |
| 1 | ~1 | Ships an MCP server; ergonomics untested here. |
| 2 | ✗0 | No capture of its own — episodes are pushed to it, and the write path calls an LLM. |
| 3 | ✓2 | Verified: any OpenAI-compatible endpoint including local models; FalkorDB local. |
| 4 | ✓2 | Bi-temporal validity windows are its core design. |
| 5 | ✓2 | Every fact traces to its source episode. |
| 6–7 | ~1 / ~1 | Entity resolution at extraction; edge invalidation is not archival policy. |
| 8 | U0 | Unverified. |
| 9 | ~1 | Entity summaries evolve over time — the closest thing to consolidation in this class. |
| 10 | ✓2 | Prescribed ontology supported. |
| 11 | U0 | Export/backup behavior unverified (flagged by Sol). |
| 12 | ✓2 | MCP server in the repository. |

T1 21 · T2 4 · T3 5 → **30**. Losing trade-off: LLM-in-the-write-path (latency,
nondeterminism, a runtime to operate) and a graph database to run.

### Basic Memory — 26/50, Paper

AGPL-3.0, markdown canonical, SQLite index, MCP-native, no server. The only candidate whose
native format gives Obsidian a real graph (wikilinks are the grammar). T1: agent-usable ✓2
(behavior-hinted MCP tools, `build_context`), capture ~1 (Claude Code plugin exists; volume
risk at ~27 chunks/day is real), local ✓2, staleness ~1, provenance ~1 → 21. T2: 0 (dedup and
tooling unverified, lifecycle manual). T3: vocabulary ~1 (entity/observation/relation grammar +
schema tools), export ✓2 ("index rebuilds from markdown"), MCP ✓2 → 5. **26.**

### txtai — 22/50, Paper

Apache-2.0, one Python service, CPU-fine. Hybrid sparse+dense verified (`hybrid: true`), MCP
verified (`mcp: true`), SQL metadata filters give date-aware retrieval. It is infrastructure:
no capture, no lifecycle, no consolidation — you build the memory semantics. T1 18 · T2 0 ·
T3 4 → **22.** As a *component* it is the strongest retrieval engine here; as a *system* it is
incomplete by design.

### Weaviate CE — 19/50, Paper

BSD-3, Docker, hybrid BM25+vector native, typed cross-references. Same shape as txtai but
operationally heavier, and its MCP claim (v1.37) is unverified. **19.**

### Letta — disqualified at gate 3, with one distinction worth recording

Letta's own documentation: the git memory repository is "Stored in cloud (GCS)", reached via
the Letta API with a valid key, and its agent prompt warns memory "may be synced off this
machine". That fails local-first as verified, not as suspected. **Disqualified.** It would
have scored best-in-class on criterion 9 — sleep-time reflection, defragmentation, git-tracked
consolidation — which is exactly the shape criterion 9 wants from whoever passes the gates.

### Screened out — named, with the reason each was not graded

| Candidate | Verdict |
| --- | --- |
| Mem0 / OpenMemory | Graph bolted onto flat memory (both consultants). Vendor self-reports 93.4% on LongMemEval where a third party measured 32.4% — treat its claims accordingly. Not graded: evidence gaps on local storage ownership and deletion semantics. |
| MemOS | The tiered L1→L2→L3 promotion is the right idea. Months old, local plugin v1.0, heavy self-hosted path (Neo4j + Qdrant). Revisit later. |
| HippoRAG | Research framework (multi-hop retrieval via Personalized PageRank). A component to evaluate behind a retrieval layer, not a system of record. |
| Cognee, LightRAG, A-Mem, supermemory, MIRIX | Immature, wrong problem class, or no maturity evidence at this volume — per two independent consultants. Named so they are not re-litigated. |

## Combinations — all grades Design

Every combination keeps MemPalace capture running. None replaces the write path until parity
is proven — the capture pipeline is the most valuable property in the stack, and both
consultants independently refused to risk it.

| | C0 Harden MemPalace | C1 + txtai shadow | C2 + Graphiti layer | C3 + Basic Memory | C4 Full stack |
| --- | :-: | :-: | :-: | :-: | :-: |
| What is added | archive policy, dedup lint, consolidation cron, declared vocabulary | txtai dual-write; hybrid + date-weighted retrieval over MCP | async LLM extraction into FalkorDB; temporal graph | consolidation cron writes cited synthesis notes as markdown; Obsidian graph for free | owned event journal; txtai retrieval + Graphiti graph + consolidation |
| Tier 1 | 24 | 27 | 24 | 24 | 30 |
| Tier 2 | 12 | 4 | 4 | 6 | 10 |
| Tier 3 | 5 | 5 | 6 | 7 | 7 |
| **Total** | **41** | **36** | **34** | **37** | **47** |
| Effort | M | **S** | L | M | XL |
| New moving parts | none | 1 service | graph DB + LLM runtime + pipeline | 1 MCP server + cron | journal + 2 engines + workers |

Why each scores where it does:

- **C0 (41)** wins tier 2 outright — dedup, archival and honest tooling are cheap to build in
  this repository and, once built, are *ours and tested*. It cannot lift criterion 1 (agent
  ergonomics unchanged) and leaves the single-maintainer governance risk untouched.
- **C1 (36)** is Sol's shadow-index design: capture stays authoritative, txtai gets every event
  through an idempotent replay, reads cut over only if the fixed query set proves it better.
  Smallest effort, fully reversible, and it is the cheapest way to run the criterion-1 test on
  a real alternative.
- **C2 (34)** buys the best graph (bi-temporal, prescribed ontology) at the highest single-layer
  cost: FalkorDB, a local LLM runtime, and an extraction pipeline whose quality must be
  monitored or it rebuilds the vestigial-graph failure with more infrastructure.
- **C3 (37)** is the consolidation play: a scheduled agent job reads recent drawers, writes
  synthesis notes with drawer-id citations into Basic Memory's markdown, and Obsidian's graph
  view lights up for free — wikilinks are the native grammar. Raw recall stays in MemPalace.
- **C4 (47)** is Sol's event-sourced architecture: hooks append to an owned journal; MemPalace,
  txtai, Graphiti and a policy worker all consume it. It is the only design that fixes capture
  crash-safety (criterion 2) at the source, and the only one where "replace MemPalace later"
  becomes a consumer swap instead of a migration. It is also the most operations this host has
  ever been asked to carry.

```callout measure
measure | What the score deliberately leaves out
Two axes are reported beside the table, never inside it. EFFORT: C4's 47 costs roughly a
quarter's work; C1's 36 costs days. GOVERNANCE: C0 leaves the single-maintainer upstream risk
fully in place; C4 retires it. A score that blended these in would hide the trade instead of
presenting it.
```

## Recommendation

Sequence, not a single pick. Each step is independently valuable and independently reversible.

```steps
1 | Ship C0's hygiene pieces | Dedup lint, archive policy, honest-count checks. Ours, tested, no new services. Lifts the baseline to ~35 regardless of what else happens.
2 | Stand up C1's txtai shadow | Dual-write behind an idempotent queue; MemPalace stays authoritative. Days of work, fully reversible.
3 | Run the criterion-1 test on both | Ten questions, fresh agent, two model families, over MCP. This is the measurement that has never existed — it decides the read path.
4 | Pilot C3's consolidation cron | One scheduled agent job writing cited synthesis notes into Basic Memory markdown. First real test of criterion 9, and the Obsidian graph arrives with it.
5 | Decide on C4 with evidence | Only if steps 2–4 prove their seams. The journal is the point of no cheap return — enter it measured, not hopeful.
```

The honest bottom line: **the evaluation did not find a product to replace MemPalace. It found
that MemPalace's capture is worth keeping, its retrieval and hygiene are worth augmenting, and
the two augmentations that matter most (txtai for retrieval, a consolidation job for thoughts)
are small, separable, and testable against criteria we now have in writing.**

## Milestones and issues — appended 2026-08-08 night, for the morning review

C0 is decomposed and **filed** (owner-approved): epic #91 plus five children. C1–C4 are
decomposed below but deliberately **not filed** — filing the remaining ~21 issues awaits the
morning review, per combination: file as-is, edit, or hold. A backlog written unreviewed by the
run that drafted it is what the issue throttle exists to prevent. Implementation of everything
on this page stays owner-gated.

### C0 — filed as epic [#91](https://github.com/3D-Stories/rawgentic-memorypalace/issues/91)

| Issue | Child | Criterion |
| --- | --- | --- |
| [#86](https://github.com/3D-Stories/rawgentic-memorypalace/issues/86) | feat(recall): exclude the archive room from default recall, with an explicit include option | 4 staleness, ~1→✓2 |
| [#87](https://github.com/3D-Stories/rawgentic-memorypalace/issues/87) | feat(lint): corpus-wide duplicate-content lint | 6 dedup, ~1→✓2 |
| [#90](https://github.com/3D-Stories/rawgentic-memorypalace/issues/90) | feat(lifecycle): archive-by-policy — **depends on #86** | 7 lifecycle, ✗0→✓2 |
| [#88](https://github.com/3D-Stories/rawgentic-memorypalace/issues/88) | feat(tooling): honest counts, reconciled against the store | 8 honest tooling, ~1→✓2 |
| [#89](https://github.com/3D-Stories/rawgentic-memorypalace/issues/89) | feat(kg): closed predicate vocabulary with write-time rejection | 10 vocabulary, ~1→✓2 |

29 + 3 + 2 + 4 + 2 + 1 = 41 — the C0 column, reproduced exactly. The consolidation cron in
C0's column is excluded on purpose: it adds no points to C0's own score, and consolidation is
piloted as C3, so it is not built twice.

### C1 — txtai shadow index (draft, not filed)

Capture stays authoritative; txtai sees every event through an idempotent replay; reads cut
over only on evidence. Effort S · one new service · fully reversible — stop the dual-write and
delete the shadow, MemPalace untouched.

| # | Child | Depends |
| --- | --- | --- |
| C1.1 | feat(shadow): durable write-event queue + dual-write — every drawer write appends an event (drawer id + content hash); a backfill mode enqueues the existing ~22k drawers | — |
| C1.2 | feat(shadow): txtai service + idempotent replayer — hybrid sparse+dense, SQL metadata filters (project, room, filed_at); local bind only; a killed replay re-runs to convergence with zero duplicates | C1.1 |
| C1.3 | feat(shadow): side-by-side comparison harness — the fixed 20-query set plus a retrieval-quality set against BOTH engines, one command, report into docs/measurements | C1.2 |
| C1.4 | feat(shadow): MCP read surface for the shadow — required by the criterion-1 test, which runs over MCP on both engines | C1.2 |

### The criterion-1 test — between C1 and C3, and it decides the read path

Ten task questions whose answers live in memory, asked by a FRESH agent over MCP, two model
families, fixed token budget. Pass = the right memory in ≤2 calls for 8 of 10. It runs against
MemPalace AND the C1 shadow. This measurement has never existed; it, not taste, picks the
default read path.

### C3 — consolidation pilot into Basic Memory (draft, not filed)

A scheduled agent job reads recent drawers and writes cited synthesis notes as markdown;
Obsidian's graph arrives free, because wikilinks are the native grammar. Raw recall stays in
MemPalace. Effort M · one MCP server + a cron job.

| # | Child | Depends |
| --- | --- | --- |
| C3.1 | infra: Basic Memory local install + a palace-notes home — notes directory, MCP registration, index-rebuilds-from-markdown proven | — |
| C3.2 | feat(consolidate): the consolidation job — cluster related drawers, write synthesis notes citing drawer ids; criterion 9's seed-5 test is the acceptance test | C3.1 |
| C3.3 | feat(consolidate): topic recall surfaces the synthesis above its fragments — the criterion's second half; the surface is chosen in design | C3.2 |
| C3.4 | ops: durable cron wiring + honest run records (drawers read, notes written, citation counts) | C3.2 |

### C2 — Graphiti layer (draft, not filed; not a recommended standalone step)

C2 standalone scores below C0 and C3, and it appears in the recommendation only inside C4. It
is drafted so the shape is on record; entering it is an evidence decision after the criterion-1
test. Effort L · FalkorDB + a local LLM runtime + an extraction pipeline that must be
quality-monitored, or it rebuilds the vestigial-graph failure with more infrastructure.

| # | Child | Depends |
| --- | --- | --- |
| C2.1 | infra: FalkorDB + Graphiti on a LOCAL OpenAI-compatible endpoint — end-to-end episode→graph with zero outbound packets | — |
| C2.2 | feat(graph): async episode feed off the capture path (reuses C1's queue if built); capture latency measurably unchanged | C2.1 |
| C2.3 | feat(graph): extraction-quality monitor — sampled precision + coverage lint, with a threshold alert | C2.2 |
| C2.4 | feat(graph): bi-temporal as-of query surface over MCP | C2.1 |

### C4 — the event-sourced stack (draft, not filed; evidence-gated)

The journal is the point of no cheap return — enter it measured, not hopeful. Only after C1,
the criterion-1 test, and the C3 pilot prove their seams. Effort XL.

| # | Child | Depends |
| --- | --- | --- |
| C4.1 | design: the event-journal ADR — format, schema, fsync and crash semantics, replay contract; cross-model review (WF5) BEFORE any code | — |
| C4.2 | feat(journal): hooks append to the journal first; MemPalace becomes consumer #1 via idempotent replay — criterion 2's kill-the-writer test finally becomes passable | C4.1 |
| C4.3 | feat(journal): consumer framework — offsets, lag metrics, rebuild-from-zero; criterion 11's wipe-and-rebuild test | C4.2 |
| C4.4 | feat(journal): txtai and Graphiti become journal consumers (ports C1 and C2) | C4.3 |
| C4.5 | feat(journal): policy worker — the archive policy and dedup run as journal-driven jobs | C4.3 |

```provenance
source | docs/planning/2026-08-08-memory-system-evaluation.md
criteria authors | claude-fable-5, gpt-5.6-sol, qwen3.8-max — independent lists, merged; consumer criteria added by the owner
baseline measured | 2026-08-08, this host, post-#77 split
product facts | fetched live from each repository 2026-08-08
epic | #71 (closed); consults follow rawgentic WF13 shape
milestones | appended 2026-08-08 night — C0 filed as epic #91 (children #86–#90); C1–C4 drafted, filing deferred to the morning review
```
