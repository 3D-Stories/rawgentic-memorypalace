# Memory/Second-Brain Research — July 2026 Landscape (2026-07-08)

**Verdict: no off-the-shelf system ships what this workspace needs; the winning
architecture is native-first working memory (Claude Code auto-memory) + a self-hosted
typed "second brain" for durable recall, with the storage engine chosen by a measured
bake-off on our own data — not bet on today.** Two facts force this: (1) retrieval
telemetry — the audit's #1 missing primitive — is shipped by NO surveyed system, so it
is custom work under every option; (2) curation/decay quality, not storage, is what
separates systems, and the strongest curation story in the market is Claude Code's own
native auto-memory (the model decides what's worth remembering at write time).

Companion scope: [`docs/planning/2026-07-08-second-brain-architecture-scope.md`](../planning/2026-07-08-second-brain-architecture-scope.md).
Evidence base: the 2026-07-08 audit (F1–F10,
[`2026-07-08-memory-system-audit.md`](2026-07-08-memory-system-audit.md)) plus the live
sources below. Owner constraints gathered 2026-07-08: best long-term > quickest;
self-hosted preferred over paid service (a mem0 Docker container already exists,
unused); human readability of memories NOT required; must answer queries like
"remind me about the decision we made on xyz".

---

## 1. Anthropic-native (confirmed — official docs, fetched live 2026-07-08)

Source: https://code.claude.com/docs/en/memory

- **Auto memory** (v2.1.59+, shipped 2026-02-26, on by default): Claude writes its own
  notes during the session — "Claude doesn't save something every session. It decides
  what's worth remembering." Storage: `~/.claude/projects/<project>/memory/` with
  `MEMORY.md` index + topic files.
- **Hard injection budget by design**: "The first 200 lines of `MEMORY.md`, or the
  first 25KB, whichever comes first, are loaded at the start of every conversation."
  Topic files load on demand only.
- **Relocatable + scoped**: `autoMemoryDirectory` setting (any settings scope);
  per-git-repo derivation, shared across worktrees. Subagents can hold their own memory.
- **Compaction-safe**: memory writes happen during the session (not stop-gated);
  project-root CLAUDE.md is re-read and re-injected after `/compact`.
- **Path-scoped rules** (`.claude/rules/` + `paths:` frontmatter): instructions load
  only when matching files are touched — a native mechanism for keeping always-loaded
  budget down.
- **`InstructionsLoaded` hook**: logs which instruction files loaded and why — the
  first native telemetry-adjacent primitive for the instruction layer.
- **`claudeMdExcludes`**, `@import` (loads at launch — organization, not budget relief),
  HTML comments stripped token-free.

Implication: since the audit, the native layer now covers most of what the audit's
L0/L3 rungs needed — model-curated capture, budget-capped index, demand-loaded detail,
per-repo scoping. It does NOT cover: durable cross-project recall, typed queries
("the decision about xyz"), supersession chains, or retrieval telemetry.

## 2. Ecosystem (each claim sourced; adversarial pass on leaders)

### mempalace upstream (the engine under the current stack)
- Releases through **v3.5.0 (2026-06-23)** are infrastructure: pluggable vector
  backends (Qdrant, pgvector, sqlite_exact), daemon write serialization, HTTP MCP
  transport, OOM/backup fixes, a *"silent data loss from drawer_id hash collisions"*
  fix (v3.4.0). **No release ships telemetry, decay, dedup, or contradiction
  detection.** (github.com/mempalace/mempalace/releases, fetched live)
- Independent analysis (lhl/agentic-memory `ANALYSIS-mempalace.md`, fetched live) —
  findings that mirror our audit: *"no decay/forgetting — memories accumulate without
  recency weighting or pruning"*, *"no feedback loops"*, contradiction detection
  *"does not exist"* despite README claims, and the headline 96.6% LongMemEval score
  *"actually measures ChromaDB's default embedding performance on uncompressed text —
  not MemPalace"* (AAAK-compressed: 84.2%; LoCoMo 60.3% "mediocre"). Palace graph
  builds are O(n) metadata scans.
- Strengths it does keep: genuinely low wake-up cost (~170 tokens), zero-LLM
  deterministic write path, fully local, zero API cost.

### claude-mem (Claude Code plugin, ~89K GitHub stars by Feb 2026)
- Best decay design surveyed: typed observations where session-state/compact-summary
  memories get `expiration_date = today + 90 days` while *"durable memory types like
  decisions, anti-patterns, and conventions stay unexpired."*
- Progressive-disclosure retrieval (compact index → timeline → full detail on demand),
  ~10x claimed token savings vs dump-at-start. Five lifecycle hooks.
- Cost: a second opinionated hook pipeline that would overlap rawgentic's own hooks;
  still no retrieval telemetry. (termdock.com, augmentcode.com writeups; repo claims —
  star count and savings figure are the repo's own, inferred not independently verified.)

### mem0 / OpenMemory (owner has an unused self-host container)
- Reported at scale: *"indexing reliability issues — memories not being added
  consistently, context recall failures under load"*; extraction misses context
  nuance; *"if you want self-hosting, you're mostly on your own — the hosted platform
  is the real product."* LongMemEval 49.0% (GPT-4o) vs Zep's 63.8%. Hosted free tier
  100 memories/mo. (Medium honest-review + comparison posts, 2026)
- Still the fastest integration path in the ecosystem and genuinely open-source.

### Zep / Graphiti
- Best correction/supersession model surveyed: bi-temporal knowledge graph — facts
  carry validity intervals, so "Alice owned the budget until February, then Bob" is a
  first-class query. LongMemEval 63.8%.
- Disqualifiers for us: **Zep Community Edition deprecated — full-feature self-hosting
  is no longer available**; reported ~600k-token per-conversation memory footprint vs
  1,764 for mem0 in one test; ~4s average query latency; delayed availability
  (ingestion → graph processing lag). (2026 comparison posts; footprint/latency figures
  are single-source — inferred, would confirm in a bake-off if Zep were still
  self-hostable.)

### Letta (MemGPT lineage)
- OS-style memory tiers with the LLM paging memory in/out — right model for
  long-autonomous agents, but: framework lock-in (memory access requires building
  inside Letta's runtime), no standardized benchmark publication, and *"less
  predictable behavior — the agent's memory decisions depend on the underlying
  model's judgment."* Disqualified for a Claude Code workspace.

### Others
- **Cognee**: graph+vector hybrid, self-hostable, 14 retrieval modes — only
  marketing-level evidence gathered; carried as a bake-off candidate, not a finalist.
- **Obsidian** (owner floated): a markdown UI + link graph. With human readability
  explicitly NOT required, it adds a UI layer over what plain files + an index already
  give; its graph is manual/link-based, not typed or temporal. Not a memory engine —
  dropped, with the note that the brain's store stays plain-text-exportable so an
  Obsidian vault view remains possible later at near-zero cost.

## 3. Research literature (actionable items only)

- **Tiered consolidation** is the emerging consensus shape: short-term scratchpad
  wiped per-task → medium-term that *"decays unless reinforced by re-access"* →
  long-term requiring *"explicit promotion."* This independently validates the audit's
  L0–L4 ladder — and "reinforced by re-access" REQUIRES retrieval telemetry, which is
  exactly our F2 gap.
- **Bi-temporal facts** (Zep/Graphiti pattern): supersession as first-class validity
  intervals rather than delete-and-replace — adopt the schema idea without adopting Zep.
- **Priority Decay** (2026): *"bounded, budget-aware forgetting policies not only
  reduce computational cost but actively preserve narrative coherence"* — decay is a
  quality feature, not just a cost feature.
- **A-MEM**: periodic LLM-mediated consolidation passes that rewrite link structure —
  the model for our promote-pass (cheap, scheduled, not per-write).
- RL-trained memory controllers (Memory-R1, MemAgent): not actionable for this stack.

### A note on benchmark numbers
The same system scores wildly differently across sources — mem0 is reported at 49.0%
LongMemEval by a third-party comparison and 94.4% by its own 2026 blog; mempalace's
96.6% turned out to measure its embedding backend. Vendor benchmark numbers are
configuration-dependent to the point of being unusable for selection. This is why the
scope's E3 bake-off runs on OUR data with OUR queries, and why no engine is chosen in
this document.

## 4. What NO system ships

Retrieval telemetry as a first-class primitive — logging which memories were retrieved,
at what rank, and whether they were used. Every candidate would need it added. The
audit's conclusion stands against the whole July-2026 market: **the storage engine is a
commodity; curation, decay, correction, and telemetry are the product, and we own them
under every option.**

## 5. Scorecard vs the 7 disqualifiers

| Disqualifier | Native auto-mem | mempalace (upstream) | claude-mem | mem0 self-host | Zep | Letta |
|---|---|---|---|---|---|---|
| 1 Telemetry | ✗ (InstructionsLoaded only) | ✗ | ✗ | ✗ | ✗ | ✗ |
| 2 Curation over accumulation | **✓ model-curated at write** | ✗ (no write gating) | ✓ typed obs | ~ (lossy extraction) | ✓ LLM graph | ~ |
| 3 Correction propagation | ~ (model edits md) | ✗ (kg_invalidate unused, no contradiction detection) | ~ | ~ | **✓ bi-temporal** | ~ |
| 4 Injection budget | **✓ 200-line/25KB cap** | ✓ 170-tok wake-up | ✓ progressive | ✓ | ✗ (~600k tok reported) | ~ |
| 5 Session-scoped | ✓ per-repo | ✗ (F9 bug ours) | ✓ | ✓ | ✓ | ✓ |
| 6 Compaction-heavy-safe | **✓ writes during session** | ✓ (bridge PreCompact) | ✓ hooks | ✓ | ✗ (ingest lag) | ✗ |
| 7 Resurface AND decay | ~ (resurface ✓, decay model-only) | ✗ (neither, upstream) | **✓ typed TTL** | ~ | ✓ | ~ |
| Self-hosted (owner) | ✓ local | ✓ | ✓ | ✓ (second-class) | **✗ CE deprecated** | ✓ |

## 6. Recommendation (carried into the scope doc)

**Native-first + typed second brain, engine by bake-off.** Working memory moves to
native auto-memory (curated, budgeted, compaction-safe, Anthropic-maintained). Durable
memory becomes a self-hosted typed brain — decision/gotcha/reference/diary records with
bi-temporal supersession, dedup-at-write, retrieval telemetry, explicit MCP recall
(per-prompt auto-inject retired; the audit measured it at ~zero proven behavioral
value). The storage engine under that brain — keep-ChromaDB (current palace data
as-is), mem0-OSS (owner's container), or custom-lean (sqlite-vec) — is selected by a
Phase-0 bake-off using the ground-truth R@1/R@5 framework this repo already has, plus
owner-style queries ("remind me about the decision on xyz"). This supersedes the
2026-07-05 "mempalace authoritative" framing **with owner approval given 2026-07-08**
(open to full replacement; best long-term > quickest). Owner decision #304 (same day)
sharpens the authority model this recommendation must respect: the brain is the
authoritative read+write memory, and native auto-memory `MEMORY.md` stays a FROZEN thin
pointer index — so "native-first" here means the native layer carries pointers and
demand-loaded caches derived from the brain, never authoritative content.

## 7. Not checked

- ossinsight.io "Agent Memory Race of 2026" taxonomy piece — fetch blocked repeatedly
  (harness classifier outage), only its search summary used.
- Owner's mem0 Docker container — not present on this host (`docker ps -a` grep empty);
  location/state unknown, bake-off issue starts by finding it.
- Cognee beyond marketing claims; claude-mem's 10x savings and star figures
  (repo-self-reported).
- Zep footprint/latency figures are single-source.
- No hands-on benchmarking was run in this phase — that is deliberately the Phase-0
  bake-off's job, on our data.

## Sources

- https://code.claude.com/docs/en/memory (official, fetched in full)
- https://github.com/mempalace/mempalace/releases (fetched)
- https://github.com/lhl/agentic-memory/blob/main/ANALYSIS-mempalace.md (fetched)
- https://www.termdock.com/blog/claude-mem-persistent-memory-claude-code · https://www.augmentcode.com/learn/claude-mem-persistent-memory-claude-code
- https://medium.com/@reliabledataengineering/mem0-do-ai-agents-really-need-memory-honest-review-6760b5288f37
- https://rohitraj.tech/en/notes/open-source-ai-agent-memory-mem0-vs-zep-letta-2026 (search summary; direct fetch blocked)
- https://blog.devgenius.io/ai-agent-memory-systems-in-2026-mem0-zep-hindsight-memvid-and-everything-in-between-compared-96e35b818da8
- https://particula.tech/blog/agent-memory-frameworks-tested-mem0-zep-letta-cognee-2026
- https://arxiv.org/html/2603.11768v1 (SSGM) · https://arxiv.org/pdf/2601.07468 (temporal semantic memory) · https://arxiv.org/html/2601.09913v1 (continuum architectures)
- https://www.mindstudio.ai/blog/what-is-claude-code-auto-memory · https://claudefa.st/blog/guide/mechanics/auto-memory
