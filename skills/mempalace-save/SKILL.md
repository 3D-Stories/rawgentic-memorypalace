---
name: rawgentic-memorypalace:mempalace-save
description: Checkpoint the current session to long-term memory — an AAAK-compressed diary entry plus verbatim drawers for key decisions/code/quotes. Use when the user says "save to mempalace", "checkpoint the session", "save session memory", or before a planned /clear, compaction, or account switch.
argument-hint: [optional focus, e.g. "just the deploy decisions"]
---

<role>
You are the memory checkpoint assistant. Your job is to persist this session's substance to the rawgentic-memorypalace memory server through its MCP tools.
</role>

# /rawgentic-memorypalace:mempalace-save — Session Checkpoint

Persist this session's substance to your long-term memory using the mempalace MCP tools
(`mcp__mempalace__*`). Those tools connect to whichever memory server you configured with
`claude mcp add` (see the README "MCP Setup" section) — this skill never hardcodes a
server address. MemPalace is the authoritative long-term memory.

## Steps

1. **Diary:** call `mempalace_diary_write` with an AAAK-compressed semantic summary of the
   session — what shipped (PRs, versions, commits), decisions made, defects found/fixed,
   and open state.
2. **Drawers:** call `mempalace_add_drawer` for each piece of key VERBATIM content worth
   exact recall — owner decisions with their exact wording, load-bearing code snippets,
   quotes, gotchas with file:line anchors. Check for an existing drawer first when updating
   a fact (`mempalace_check_duplicate` / `mempalace_search`) rather than duplicating.
3. **Knowledge-graph writes (new + changed single-valued facts):** the KG stores single-valued
   facts (a decision, the model in use, an employer) as `subject predicate object` triples. When
   this session established or altered such a fact, write it structurally so point-in-time
   ("as-of") queries stay correct. Pick exactly ONE of the three primitives by what happened to
   the fact — this is the three-way rule:
   - **Value CHANGED** (a decision reversed, a model/employer/address swapped) →
     `mempalace_kg_supersede(subject, predicate, old_object, new_object)`. One atomic boundary:
     the old value closes and the new opens together, so an as-of query at the boundary returns
     only the new value. Do NOT hand-roll `invalidate` + `add` for a change — that leaves the old
     and new both open at the boundary and an as-of query then returns two values.
   - **Fact ENDED** (no longer true, and nothing replaces it) →
     `mempalace_kg_invalidate(subject, predicate, object)`.
   - **New INDEPENDENT / concurrent fact** (nothing it replaces) → `mempalace_kg_add(...)`.

   Skip this step when the session established no new or changed single-valued fact.
4. **Confirm in ONE line:** `Saved N drawers + diary` — nothing else. Be thorough but
   fast; this often runs right before a /clear.

## Guardrails

- **Writer lease busy** (`MCP error -32001: Peer MCP writer active`): another session holds
  the writer. Do NOT retry-fight it — report `mempalace write DEFERRED (writer lease held)`
  and record the intended content in your working notes so the next session can re-attempt.
- **Secrets by NAME only** — never a credential value in any drawer or diary.
- **No transcript-content dumps from privacy-sensitive projects** — metadata and decisions
  only.
