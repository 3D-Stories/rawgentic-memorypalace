# Unwinding the `documentation` room

**Issue #77, acting on #74's finding.** The plan, the tool, and the before-measurement.
**The move has not been run.** Executing it against the live palace is a separate,
owner-approved step, exactly as the issue requires.

---

## The number the epic did not have

AC1 asked for the per-wing breakdown of the room itself, not wing totals. Measured
2026-08-08, read-only:

| wing | in `documentation` | wing total | share of the wing |
| --- | ---: | ---: | ---: |
| chorestory | 10,018 | 10,182 | 98.4% |
| millions | 2,704 | 2,705 | **100.0%** |
| sysop | 1,690 | 1,811 | 93.3% |
| grocusave | 1,554 | 1,595 | 97.4% |
| rawgentic | 1,309 | 2,290 | 57.2% |
| clawd | 462 | 463 | 99.8% |
| daimonia | 273 | 274 | 99.6% |
| rawgentic_memorypalace | 273 | 312 | 87.5% |
| 2024_2025_taxes | 173 | 174 | 99.4% |
| chorestory_business | 114 | 115 | 99.1% |
| arc | 101 | 102 | 99.0% |
| ai_coding_presentation | 37 | 38 | 97.4% |
| snowgate | 19 | 20 | 95.0% |
| nillerkgames | 4 | 5 | 80.0% |
| **total** | **18,731** | **22,110** | |

```callout measure
measure | This is what changed the design
For 11 of the 14 wings, `documentation` is 95-100% of the entire wing. `millions` is
2,704 of 2,705. Only `rawgentic` (57.2%) has substantial content outside it.
```

---

## AC2 — the target structure, and why it is not what the issue sketched

The issue proposed **per-project rooms**. The table above argues against it. A room called
`millions-documentation` would hold 2,704 of the 2,705 drawers in the `millions` wing — it
restates the wing, which already scopes the project. The room dimension would still carry no
information, and the palace's premise, that a search can be scoped by wing AND room, would
still be half dead.

**So the wing keeps the project, and the room carries the KIND.** That is what a room is for.
Owner decision, 2026-08-08, taken on the numbers above against two alternatives (per-project
rooms as sketched; or splitting only `docs/archive/**` out).

The taxonomy is not invented — it is already in the data. Every drawer records the folder it
was mined from, and those folders sort the content across 59 distinct paths:

| source folder | → room | drawers |
| --- | --- | ---: |
| `docs/archive/**` | `archive` | 5,251 |
| `docs/plans`, `docs/planning`, `docs/roadmap` | `plans` | 3,877 |
| `docs/superpowers/**`, `docs/specs` | `specs` | 1,954 |
| `docs/reference`, `docs/domain`, `docs/quickstart` | `reference` | 1,130 |
| `docs/runbooks`, `docs/operations`, `docs/monitoring`, `docs/deploy`, `docs/hardware` | `operations` | 857 |
| `docs/product` | `product` | 852 |
| `docs/design`, `docs/architecture`, `docs/ux-review` | `design` | 787 |
| `docs/features` | `features` | 723 |
| `docs/migration` | `migration` | 539 |
| `docs/TDD`, `docs/testing` | `testing` | 278 |
| `docs/sessions` | `sessions` | 271 |
| `docs/analysis` | `analysis` | 265 |
| `docs/SDLC` | `process` | 211 |
| anything unmapped | stays `documentation` | 1,736 |

**Dry run against the live palace: 16,995 of 18,731 drawers (90.7%) get a meaningful room.
1,736 stay put.** Nothing is forced: an unrecognized source path keeps the residue room rather
than being guessed into a wrong one.

Matching is on **path components**, not raw prefixes — a review pass found that a raw prefix
swept `docs/archived`, `docs/plans-old` and `docs/productivity` into rooms they do not belong
to. Fixing it moved 154 drawers back to the residue room, which is why the numbers here are
slightly lower than a naive match would report.

What that does to the biggest wings:

```
chorestory (10,018)  archive 5159 · reference 1130 · product 852 · features 723 ·
                     documentation 513 · design 361 · testing 278 · sessions 271 ·
                     analysis 265 · process 211 · specs 184 · plans 71
millions   (2,704)   plans 2497 · documentation 207
sysop      (1,690)   operations 857 · migration 533 · specs 134 · archive 92 · documentation 74
grocusave  (1,554)   specs 858 · plans 520 · documentation 176
rawgentic  (1,309)   plans 559 · design 426 · documentation 278 · specs 46
```

`chorestory` goes from one room to twelve. That is the room dimension coming back to life.

Three wings gain nothing: `arc` (101), `snowgate` (19) and `nillerkgames` (4) stay entirely in
the residue room, because their source folders are not ones the rules recognize. That is
reported rather than forced — guessing a room for them would be inventing a taxonomy instead of
reading one.

**The naming rule, written down:** a room is a KIND of content, never a project. The project is
the wing. A room name is a lowercase singular-or-plural noun naming what the content *is*
(`plans`, `specs`, `archive`), never who it belongs to.

---

## AC3 — the rule that stops it rebuilding

From #74: **nothing writes to `documentation` today.** 18,729 of its 18,731 drawers came from a
single bulk `mempalace mine` run in April 2026, and exactly two have been added since. There is
no live tap to close. So the rule has to bind the NEXT bulk mine rather than an ongoing process:

> **A bulk mine files by kind, not into a shared catch-all, and carries the date it was taken.**
>
> `docs/` is a folder name, not a topic. Routing every project's `docs/` tree into one room
> defeats scoped search at the room level. A bulk import is also a *snapshot* — it records a
> file as it stood on one day and does not update when the file does — so it must stay
> distinguishable from a note somebody wrote deliberately.

Upstream's router is what produced the ratio (`mempalace/room_detector_local.py:43-48` maps the
folder keywords `docs`, `doc`, `documentation`, `wiki`, `readme`, `notes` to one room). We do
not own that package, so the rule binds **our** procedure for running a mine, and
`rawgentic_memory.room_split` is the tool that re-sorts the result.

---

## AC4 — the reversible path

`rawgentic_memory/room_split.py`. **Nothing it does deletes a drawer.** The only mutation is a
drawer's `room` metadata value.

```bash
python -m rawgentic_memory.room_split                    # dry run — the default
python -m rawgentic_memory.room_split --json
python -m rawgentic_memory.room_split --apply \
    --manifest revert-2026-08-08.json --i-have-a-verified-backup
python -m rawgentic_memory.room_split --revert --manifest revert-2026-08-08.json
```

Six properties, each one a refusal rather than a hope:

- **Dry run is the default.**
- **`--apply` AND `--revert` both write, and both refuse without
  `--i-have-a-verified-backup`.** An earlier draft said "`--apply` is the only path that
  writes" and then let `--revert` through without the flag; a review pass caught the
  contradiction. The palace is 308 MB and a backup nobody has restored is not a backup.
- **`--apply` refuses without `--manifest`,** and the manifest is written BEFORE anything
  changes. It records every drawer id with its old and new room, so `--revert` puts each one
  back exactly.
- **A manifest is never overwritten,** and it is created with exclusive mode rather than a
  check-then-write, which had a window where another process could create the file and have it
  truncated.
- **A corrupt manifest is refused.** It carries a version and a move count, and a mismatch
  raises. An empty-but-valid `{}` would otherwise revert nothing and report success — a
  recovery command claiming it worked while the palace stays migrated.
- **A partial write is refused, not reported.** Every id is checked before anything is written,
  and a missing or duplicated id raises with nothing changed. A half-migrated palace that
  automation reads as clean is the worst outcome available here.

Both write paths are tested against a real ephemeral palace, not a mock: apply moves the
drawers, revert restores them, every other metadata key survives, and the drawer count is
unchanged. A migration tool whose write path has never run is a claim, not a capability.

```steps
1 | Back up the palace AND restore it once | 308 MB at ~/.mempalace/palace. `sqlite_integrity` currently reports error_count 0 — that clean baseline is what the restore has to reproduce.
2 | Run the dry run and read the per-wing table | It is the diff. If a wing looks wrong, fix the rules before touching anything.
3 | Apply with a dated manifest | `--apply --manifest revert-<date>.json --i-have-a-verified-backup`.
4 | Re-run the AFTER measurement on the fixed query set | docs/reviews/2026-08-08-77-retrieval-query-set.json, unchanged. A query set edited between runs measures nothing.
5 | Compare, and revert if it got worse | `--revert --manifest revert-<date>.json --i-have-a-verified-backup`. The number decides, not the feeling.
```

---

## AC5 — the before measurement, recorded

Twenty queries, top 10 each, fixed in
`docs/reviews/2026-08-08-77-retrieval-query-set.json` so the after-run uses exactly the same set.

**BEFORE (2026-08-08): 147 of 200 hits — 73.5% — came from `documentation`.**

| room | hits | share |
| --- | ---: | ---: |
| documentation | 147 | 73.5% |
| decisions | 18 | 9.0% |
| reference | 8 | 4.0% |
| _registry | 8 | 4.0% |
| process-conventions | 6 | 3.0% |
| gotchas | 4 | 2.0% |
| everything else | 9 | 4.5% |

Eight of the twenty queries returned **10 of 10** from `documentation`. Two returned 2 or
fewer, and both were sharply-worded questions about a decision or a gotcha — the shape that
already reaches the curated rooms.

**What "better" will mean.** Not "fewer documentation hits" — the content is useful and #74
showed it is answering most questions. Better means the same content arriving under a room that
says what it is, so a scoped search can ask for `plans` and not get `archive`. The honest test
after the move is whether a query scoped to a kind returns what that kind promises; the
unscoped 73.5% may barely move, and that would not be a failure.

---

## AC6 — wing-name fragmentation: explicitly deferred, with the reason

#73's linter fails on the live palace today, on three groups:

| normalized | spellings | drawers |
| --- | --- | --- |
| `rawgentic` | `rawgentic`, `wing_rawgentic` | 2,290 + 52 |
| `herdr_dashboard` | `herdr-dashboard`, `herdr_dashboard` | 134 + 6 |
| `chorestory_studio` | `chorestory-studio`, `wing_chorestory_studio` | 19 + 1 |

AC6 allows "resolved first or explicitly deferred". **Deferred, and here is why it is safe to
defer in this specific design:** the issue's concern was "re-filing into `rawgentic` while
`wing_rawgentic` also exists just moves the problem." That concern applies to a plan that
re-files into WINGS. This plan does not touch a wing at all — it changes only the `room` value.
Fragmentation is therefore orthogonal: the split neither fixes it nor makes it worse, and the
linter will keep failing on it until a separate wing rename is approved.

A wing rename has a different blast radius: it moves other sessions' stored memories under a
different scope key, and none of those sessions are ours to speak for. It deserves its own
decision.

---

## What has NOT been done

**The move has not been run.** The live palace is untouched: every measurement in this document
was read-only, and the dry run writes nothing. Steps 1 to 5 above are the owner's to authorize.

```provenance
source | docs/planning/2026-08-08-77-documentation-room-split.md
issue | #77
acts on | #74
epic | #71
measured | 2026-08-08
state | plan + tool + before-measurement; move NOT executed
```
