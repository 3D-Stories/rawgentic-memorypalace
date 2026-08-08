# Sibyl-Memory against our MemPalace: should we switch?

**No. Stay on MemPalace, and do not pilot Sibyl-Memory as a replacement.** Sibyl's free tier
hard-caps a local database at 2 MB. Our palace is 308 MB across 22,092 drawers, so we are roughly
154x over that line before a single new memory is written. Switching is not a migration, it is a
purchase — and the product it buys is at version 0.1.2, has 98 GitHub stars, ships 305 downloads a
month, and its documentation site currently returns "Documentation is being rebuilt."

Two of Sibyl's design choices are nonetheless better than ours and worth stealing. Its
single-source-of-truth rule is enforced by a database constraint rather than by convention, and
its published reproducibility kit sets a standard our own benchmark claim does not meet.

```verdict
ship | Stay on MemPalace. The scale gap alone settles it; the maturity gap confirms it.
risk | Our palace is unhealthy in a way this comparison exposed: 85% of it is one room.
risk | Our headline benchmark number is not comparable to Sibyl's, and both get quoted.
```

```provenance
sibyl repo | github.com/Sibyl-Labs/Sibyl-Memory, read 2026-08-07
mempalace repo | github.com/MemPalace/mempalace, read 2026-08-07
our palace | our own live memory server, queried 2026-08-07
stars and forks | GitHub API, not the rendered page
research tools | Exa search and fetch; Context7 returned no entry for either package
```

## The decisive number

Everything else here is context for one line.

```callout
warn | Our palace is 154x the Sibyl free-tier cap
`sibyl-memory-mcp` 0.1.2 states the rule itself: "Free tier: 8 tools work. Hard-capped at 2 MB
of local storage. Writes that would push past the cap return `CAP_EXCEEDED`." The cap is
server-authoritative and HMAC-verified, so it cannot be edited locally. Our `chroma.sqlite3`
is 286,408,704 bytes and the palace directory is 308 MB.
```

**Confirmed.** `du -sh ~/.mempalace/palace` returned `308M`. The palace's own status call reports
`total_drawers: 22092` with an integrity check of `error_count: 0`.

Any move to Sibyl therefore starts on a paid tier. The public price is unavailable: the tiers page
at `docs.sibyllabs.org/memory/tiers` returns "Documentation is being rebuilt. In the meantime, the
Discord is where access, onboarding, and questions are handled." A pricing conversation that
happens only in a Discord is not a procurement path.

## What each system actually is

These are not variations on a theme. They sit on opposite sides of the central question in agent
memory: do you spend on embeddings, or do you spend on schema design?

| | **Our MemPalace** | **Sibyl-Memory** |
| --- | --- | --- |
| Retrieval | Semantic vector search | SQLite FTS5 keyword search |
| Embeddings | Yes — `embedding-gemma-300m` or `all-MiniLM-L6-v2` | **None, by design** |
| Store | ChromaDB default; SQLite, Milvus, Qdrant, pgvector pluggable | One SQLite file |
| Data model | Wings, rooms, drawers, plus tunnels between wings | Five tiers: HOT, WARM, COLD, REFERENCE, ARCHIVE |
| Knowledge graph | Temporal entity-relation graph with validity windows | None |
| Compression | AAAK dialect, readable by human and model | None |
| Size on disk | 308 MB here, plus roughly 300 MB of model | Kilobytes to a few MB |
| Account required | No | **Yes** — `sibyl init`, wallet or email |
| Outbound calls | None | Tier check to `api.sibyllabs.org` on write |
| License | MIT | MIT |
| Stars and forks | **58,200 / 7,481** | **98 / 10** |
| Monthly PyPI installs | **83,042** | **305** |
| Created | 2026-04-05 | 2026-05-20 |
| Version | 3.6.0 upstream; we pin `>=3.3.5,<4.0` | 0.4.x client, 0.1.2 MCP, "3 - Alpha" |

Both are MIT. Both were pushed to today. Both are young: MemPalace is four months old, Sibyl under
three.

## The comparison everyone will get wrong

This is the finding most likely to mislead a reader, including a reader inside this company.

```callout
warn | 96.6% and 95.6% are not the same measurement
MemPalace publishes **96.6% R@5** — recall at five, with "no heuristics, no LLM", asking only
whether the answer appeared in the top five retrieved items. Sibyl publishes **95.6% accuracy**
on LongMemEval Oracle, end to end, with Claude Opus 4.6 doing the answering. One measures a
retriever. The other measures a retriever plus a frontier model plus a prompt.
```

Reading those two numbers side by side and concluding MemPalace wins by a point is unsupported. So
is the reverse. **We have no head-to-head evidence, and this document does not manufacture one.**

Credit where it is due. Sibyl publishes `memory-bench-kit` with the scorer, the raw hypothesis
files, the run ID, the model, the cost (`$43.78`, `$0.088/question`) and the wall clock. That is a
materially higher standard of evidence than a percentage in a README, and it is the standard our
own 96.6% figure does not meet.

## Where Sibyl is genuinely better

Three things. The first is the one worth acting on.

```steps
1 | Schema-enforced single source of truth | Sibyl's Rule 43 is a `UNIQUE (tenant_id, category, name)` constraint. Ours is convention.
2 | No embedding dependency | No 300 MB model, no GPU question, no re-embedding cost when the model changes.
3 | A memory linter | A health check over the local database. We have no equivalent, and the next section shows why we need one.
```

The constraint is the interesting one. We rely on a protocol — the instruction to call
`mempalace_kg_supersede` rather than hand-rolling invalidate-then-add — to prevent duplicate facts.
Sibyl makes that class of drift impossible at the schema level. A rule a model must remember is
weaker than a rule the database enforces, and we have 22,092 drawers written under the weaker one.

## Where we are weak, which this comparison exposed

Being fair to Sibyl means being honest about our own numbers. The palace is lopsided.

| Slice of the palace | Drawers | Share of 22,092 |
| --- | ---: | ---: |
| The `documentation` room | 18,731 | **85%** |
| The `chorestory` wing | 10,182 | **46%** |
| `decisions` + `reference` + `diary` + `gotchas` combined | 2,494 | 11% |
| Knowledge-graph triples | 158 | 0.7% |

**85% of the palace is one room.** `documentation` holds 18,731 of 22,092 drawers. The rooms
carrying curated judgment are comparatively tiny: `decisions` 934, `reference` 613, `diary` 552,
`gotchas` 395. **46% of the palace is one wing** — `chorestory` alone holds 10,182.

The knowledge-graph layer is barely used. It holds **287 entities and 158 triples**, of which
**2 are expired**. We built a temporal graph with supersede and invalidate semantics and roughly
140 relationship types, then recorded 158 facts in it. The bitemporal machinery is real and almost
untouched.

```callout
note | This is not an argument for Sibyl
Sibyl would fix none of it. A 2 MB cap does not cure a bloated documentation room, it merely
refuses to hold it. The finding is that our retrieval quality is probably limited by what we put
in the palace rather than by the engine underneath it.
```

## Supply chain, and who is behind each

Worth stating plainly, because both answers are unusual.

**MemPalace** is a third-party PyPI package authored by `milla-jovovich`. We depend on it directly
(`mempalace>=3.3.5,<4.0`) and wrap it. Its own README carries a security warning: "Beware of
impostor sites… Any other domain… is an impostor and may distribute malware." A project needing
that notice is a project being actively targeted. Our pin is a floor with an upper bound, which is
the right shape, but the upstream is one maintainer.

**Sibyl-Memory** is written by an autonomous agent. Its README says so directly: SIBYL "has been
operating in production since February 2026, ships code daily, holds an on-chain identity on Base
(ERC-8004 agent ID 20880), runs an autonomous trading engine, an on-chain messaging protocol, an
x402 payment rail." The upgrade path is a "staker / subscription flow."

That is not a disqualification, and the engineering in the repo looks competent. It is a
disclosure. Adopting it couples our long-term memory to a crypto-funded product line, an account
system, and a phone-home write check, maintained by an agent. For a store already holding 22,092
records of our decisions, that coupling is the risk, not the code quality.

## What a migration would actually cost

If the decision were reversed, this is the shape of the work. Recorded so the estimate is not
re-derived later.

```steps
1 | Buy a paid tier | Price unknown and unpublished. Discord only.
2 | Map wings, rooms and drawers onto five fixed tiers | Our model is two-dimensional. Sibyl's is one ordered ladder. No mechanical mapping exists.
3 | Accept the loss of semantic retrieval | 22,092 drawers written for vector search, queried by keyword instead.
4 | Rebuild the temporal knowledge graph | Sibyl has no graph layer. 287 entities and 158 triples have nowhere to land.
5 | Rewrite every skill and hook | Eight `memory_*` tools replace our whole surface, including AAAK, tunnels, diary and checkpoint.
```

Steps 3 and 4 are not migration tasks. They are capability deletions. That is the real answer to
"should we switch": the question is not whether Sibyl is good, it is whether we want to give up a
knowledge graph and semantic search to gain a database constraint and a smaller file.

## Recommendation

```chips
Stay on MemPalace | done
Add a uniqueness guard for entities | wip
Write a palace linter | wip
Re-audit what we write to documentation | wip
Re-state our benchmark claim honestly | wip
Pilot Sibyl as a replacement | blocked
```

**Stay.** Then take the three ideas Sibyl got right.

1. **Enforce single source of truth in the store, not the protocol.** The `mempalace_kg_supersede`
   instruction has the right semantics carried by the wrong mechanism.
2. **Write a linter.** 85% of the palace being one room is exactly what a health check exists to
   surface, and we found it by accident while researching a competitor.
3. **Stop quoting 96.6% beside anyone else's accuracy figure.** It is a recall number. Either say
   so every time, or run the end-to-end evaluation and publish the kit the way Sibyl did.

**Revisit if** Sibyl publishes pricing, reaches a stable release, and adds a graph layer. Track it
rather than adopt it. At 305 downloads a month it is not yet a thing running in production anywhere
but its author's own infrastructure.

## What I did not verify

Stated so confidence in the rest is legible.

- **I did not install or run Sibyl-Memory.** Every claim about its behaviour comes from its README,
  its PyPI pages and its own marketing site. The 2 MB cap, the HMAC-signed credential and the
  `check-write` call are quoted from `sibyl-memory-mcp` 0.1.2's own documentation, not observed.
- **I did not benchmark either system.** Both percentages are vendor-published.
- **I did not read the upstream MemPalace source.** Backend claims come from its README and PyPI
  metadata, plus our live server's own `backend: chroma` report.
- **The 308 MB is this workstation.** The memory server runs on a separate LAN host and `ssh` to it
  failed with `Host key verification failed`, so the server-side copy was never measured separately.
