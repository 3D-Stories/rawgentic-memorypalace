# What writes to the `documentation` room

**Issue #74. Audit only — nothing here deletes or moves a single drawer.**
Measured live on 2026-08-08 against `~/.mempalace/palace/chroma.sqlite3`, read-only.

---

## The answer in one line

**Nothing writes to it. It stopped growing in April 2026.**

`documentation` holds 18,731 of 22,110 drawers (84.7%), and **18,729 of those were written by
a single bulk `mempalace mine` run in April 2026.** Exactly **two** drawers have been added
since — both in July, both by an agent. It is not a room that is filling up. It is a fossil of
one import, and it has been sitting across the middle of every search since.

```verdict
ship | Split by project (#77), keep every drawer, and mark the import as a dated snapshot.
risk | 65 of 100 retrieved hits come from April-2026 file snapshots that have since changed.
risk | Tightening ingestion would change nothing — there is no tap left to turn down.
```

```chips
write path | blocked
room growth | done
retrieval share | wip
```

```callout measure
measure | The two numbers that carry the audit
The April 2026 bulk import is 18,901 of 22,110 drawers — 85.5% of the entire palace — and
99.1% of that import landed in `documentation`. Everything written since May is 3,209
drawers, and exactly 2 of them landed there.
```

---

## AC1 — the write paths, named

### This repository writes nothing to it

`grep -rn "documentation" hooks/ skills/ rawgentic_memory/` returns two hits, both prose in
`skills/recall/SKILL.md` describing what the room is. No hook, no skill, and no server endpoint
in this repository files a drawer into `documentation`. `rawgentic_memory/server.py` has no
write path to the palace at all beyond the canary.

### The room is assigned upstream, by folder name

Room routing lives in the third-party `mempalace` package:

- `mempalace/room_detector_local.py:43-48` — `FOLDER_ROOM_MAP` maps the folder keywords
  `docs`, `doc`, `documentation`, `wiki`, `readme` and `notes` to the room `documentation`.
- `mempalace/miner.py::detect_room` — priority 1 is "a folder in the path matches a room name
  or keyword". A file under `docs/` therefore lands in `documentation` before content is
  considered at all. The fallback when nothing matches is `general`, not `documentation`.

So every project's `docs/` directory routes into one shared room, across every project mined.

### Who actually wrote them

| `added_by` | drawers |
| --- | ---: |
| `mempalace` (the miner CLI) | 18,729 |
| `claude-fable` (an agent) | 2 |

For contrast, the whole palace: `mempalace` 18,901, `claude-code` 1,014, unset 537, `claude`
495, `mcp` 224, `claude-opus-4.8` 65.

### When

| `filed_at` month | `documentation` | whole palace |
| --- | ---: | ---: |
| 2026-04 | 18,729 | 18,901 |
| 2026-05 | 0 | 8 |
| 2026-06 | 0 | 304 |
| 2026-07 | 2 | 2,664 |
| 2026-08 | 0 | 233 |

Two numbers carry the whole audit:

- The April import is **18,901 of 22,110 drawers — 85.5% of the entire palace**, and 99.1% of
  that import went into `documentation`.
- **Everything written since May is 3,209 drawers, and exactly 2 of them landed in
  `documentation`.**

Every source path in the room begins `/tmp/mempalace-restage/<project>/docs/...` — a staging
directory used for that one migration. The paths do not exist any more.

---

## AC2 — what a typical drawer actually contains

639 distinct source files became 18,731 drawers. **Mean 29.3 chunks per file, median 23,
maximum 174.** One long planning document becomes over a hundred drawers.

| source file | drawers |
| --- | ---: |
| `millions/docs/plans/2026-02-27-phase4-strategy-templates-plan.md` | 176 |
| `grocusave/docs/superpowers/plans/2026-03-31-national-data-layer.md` | 175 |
| `grocusave/docs/planning/ux-design-specification.md` | 165 |
| `rawgentic-memorypalace/docs/superpowers/plans/2026-04-14-mempalace-integration.md` | 165 |
| `2024-2025_Taxes/docs/superpowers/plans/2026-04-08-tax-expense-tracker.md` | 147 |

Drawer size is uniform: **median 719 characters, mean 685, maximum 824.** That is a mechanical
fixed-width chunker, not a semantic one. Three drawers sampled at the 25th, 50th and 75th
percentile:

> `chorestory/docs/product/REPORTING_REQUIREMENTS_FAMILY_ADMINS.md`
> "4 days (actual average)" - "This chore is completed 2 days early on average - reduce
> frequency" 5. **Reward Optimization Analysis** - **Question:** "Is the reward value
> appropriate?" …

> `chorestory/docs/archive/analysis/CRITICAL_BUG_ANALYSIS_CHORE_ROLLOVER.md`
> od**: "Is chore date before today's date?" (correct semantics) ### 3. Test Edge Cases at
> Boundaries Always test: - Midnight (00:00:00) …

> `millions/docs/plans/2026-02-27-phase4-strategy-templates-design.md`
> on wizard in the dashboard lets users configure and launch new strategies. --- ## Design
> Decisions | Decision | Choice | Rationale | …

Two of the three **begin mid-word** — `od**:` is the tail of `method**:`, and `on wizard` is
the tail of something like `A configuration wizard`. This is the honest characterization:
a typical `documentation` drawer is a ~700-character slice cut out of the middle of a long
markdown file, with no guarantee that it starts or ends at a sentence, let alone an idea.

Is it content a future session would want returned? **Sometimes, and that is the problem.**
The third sample is a genuine design-decision table worth recalling. The second is a
lesson-learned from an `archive/` directory. The first is a requirements fragment about a
feature that may no longer exist. A reader cannot tell which is which from the drawer, because
the drawer is a snapshot of a file as it stood in April 2026 and the file has moved on.

---

## AC3 — retrieval evidence, not intuition

Ten realistic session queries, top 10 results each, room recorded for every hit:

| query | hits from `documentation` |
| --- | ---: |
| why did we choose this database | 10 / 10 |
| chorestory chore approval flow | 10 / 10 |
| what broke in CI last time | 9 / 10 |
| how do we deploy the studio | 8 / 10 |
| how does the recall hook work | 8 / 10 |
| what did we decide about the memory server | 8 / 10 |
| what is the test gate for this project | 7 / 10 |
| vercel deployment problem | 3 / 10 |
| owner decision about merging pull requests | 2 / 10 |
| known gotcha with the mirror | 0 / 10 |

**Across 100 retrieved hits: 65 came from `documentation`.**

| room | share of hits |
| --- | ---: |
| documentation | 65% |
| decisions | 16% |
| reference | 5% |
| gotchas | 4% |
| everything else | 10% |

This settles the question the issue asked. The room is **not** occupying the index without
being recalled. The opposite: it wins roughly two-thirds of every retrieval, and it does so
with April-2026 snapshots of files that have since changed.

The two queries where the curated rooms won are the tell. "known gotcha with the mirror"
returned zero `documentation` hits and found the real drawer. "owner decision about merging
pull requests" returned 2 of 10. When a question is sharply about a decision or a gotcha, the
curated rooms surface. When it is a general "how does X work" question — which is most
questions — 18,731 fixed-width fragments of old plans crowd them out.

---

## AC4 — recommendation, with the trade-off stated

**Recommended: split by project (issue #77), keep the content, and mark it as a dated
snapshot. Do not delete, and do not tighten ingestion.**

Why each alternative loses:

**Leave it alone.** Cheapest, and defensible — retrieval works, people are finding things.
It loses because 65% of every result set comes from one April snapshot, and a reader cannot
tell a live note from a four-month-old file that has since been rewritten. That is a
correctness risk, not a tidiness complaint.

**Scope ingestion more tightly.** This was the obvious guess before the measurement, and the
measurement kills it. **Nothing is ingesting.** Two drawers in four months. There is no tap to
turn down; tightening the miner's routing would change nothing about the 18,731 already there.

**Delete or archive the slice.** Not recommended, and by the issue's own rule not a default.
The content is demonstrably being used — 65 of 100 hits. Deleting it would remove the material
that is currently answering most questions, and replace a precision problem with a recall
problem.

**Split into per-project rooms (#77).** Recommended. It directly fixes what is broken: the
palace's premise is that a search can be scoped, and a room spanning 14 wings and 85% of
everything scopes to nothing. Splitting restores the scope without losing a drawer. The
trade-off is honest: it is the largest single change ever made to this palace, it needs a
verified backup and a reversible path, and it re-files 18,731 drawers whose retrieval behavior
will change — which is why #77 requires a before-and-after measurement on a fixed query set
rather than a belief that it got better.

**One addition to #77, from this audit.** Splitting alone does not fix staleness. These are
April-2026 snapshots. #77 should carry the import date into the new rooms so a future reader —
and a future ranking rule — can tell a four-month-old file snapshot from a note somebody wrote
this week.

```steps
1 | Back up the palace and restore it once | 308 MB. A restore that has never been tried is not a backup.
2 | Break the room down per wing first | The 18,731 by wing. The epic's table is wing TOTALS, which is a different number.
3 | Resolve the three fragmented wing names | #73's linter fails on them today. Re-filing into `rawgentic` while `wing_rawgentic` also exists just moves the problem.
4 | Fix a query set and measure it BEFORE moving anything | Otherwise "more findable" stays a belief. The ten queries in this audit are a starting set.
5 | Re-file per project, carrying the import date | Splitting alone does not fix staleness; these are April snapshots.
6 | Measure the same query set again | The number, not the feeling, decides whether it worked.
```

---

## AC5 — the rule, so the ratio does not rebuild itself

Written here, and to be carried into `#77` when it lands:

> **A bulk mine of a project's files is filed per project, never into a shared room, and is
> marked with the date it was taken.**
>
> `docs/` is a folder name, not a topic. Routing every project's `docs/` directory into one
> shared `documentation` room defeats scoped search at the room level, which is the palace's
> whole retrieval premise. A bulk import is also a *snapshot*: it records a file as it stood on
> one day, and it does not update when the file does. It must therefore be distinguishable from
> a note somebody wrote deliberately, both by a person reading a result and by any future
> ranking rule.

The rule holds regardless of whether #77 is done: it constrains the next bulk mine, and the
next one is what would rebuild the ratio.

---

## What this audit did not do

Nothing was deleted, moved, or rewritten. No drawer was created. Every query above was run
read-only, and the palace is byte-identical to how it was found.

## How to re-run any of this

The shape numbers come from the linter shipped in #73:

```bash
python -m rawgentic_memory.palace_lint --json
```

The retrieval experiment is ten `search_memories` calls with the room of each hit tallied. The
per-drawer counts are read directly from `~/.mempalace/palace/chroma.sqlite3` in `mode=ro`.

```provenance
source | docs/reviews/2026-08-08-74-documentation-room-audit.md
issue | #74
epic | #71
measured | 2026-08-08
palace | 22,110 drawers, 51 wings, 66 rooms
```
