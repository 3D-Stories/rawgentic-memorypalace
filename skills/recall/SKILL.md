---
name: rawgentic-memorypalace:recall
description: Search long-term memory, invalidate stale decisions, supersede a changed decision, view decision timelines, or browse cross-project tunnels. Supports subcommands: search (default), invalidate, supersede, timeline, tunnels.
argument-hint: <query> | invalidate "<subject> decided <object>" | supersede "<subject> <predicate> <old> -> <new>" | timeline <entity> | tunnels [wing] | --project <name>
---

<role>
You are the memory recall assistant. Your job is to search the rawgentic-memorypalace memory server and present results clearly to the user.
</role>

# /rawgentic-memorypalace:recall — Semantic Memory Search

Search your long-term memory for past decisions, discoveries, and events.

## Usage

```
/rawgentic-memorypalace:recall <query>
/rawgentic-memorypalace:recall <query> --project <project-name>
/rawgentic-memorypalace:recall invalidate "<subject> decided <object>"
/rawgentic-memorypalace:recall supersede "<subject> <predicate> <old> -> <new>"
/rawgentic-memorypalace:recall timeline <entity>
/rawgentic-memorypalace:recall tunnels [wing]
```

## Instructions

### 1. Parse Arguments — Subcommand Dispatch

Check the first word of the arguments to determine the subcommand:

- **`invalidate`** → go to **Section 5: Invalidate a Decision**
- **`supersede`** → go to **Section 5b: Supersede a Changed Fact**
- **`timeline`** → go to **Section 6: View Timeline**
- **`tunnels`** → go to **Section 7: Browse Cross-Project Tunnels**
- **Anything else** → treat as a search query, continue to Step 2

> **Which KG write?** For a single-valued fact whose value **changes** (a decision reversed,
> a model or employer swapped) use `supersede` — one atomic boundary. For a fact that merely
> **ended** use `invalidate`. For a new **independent/concurrent** fact, record it via
> `/rawgentic-memorypalace:mempalace-save` (which calls `mempalace_kg_add`). Do NOT hand-roll
> `invalidate` + `add` for a changed value — that leaves the old and new both open at the
> boundary, so an as-of query returns two values.

For search queries, extract:
- **Query text:** Everything that is not a flag. Remove surrounding quotes if present.
- **`--project <name>`:** Optional. If present, filter results to this project only.

If no arguments are provided, ask the user what they want to do and STOP.

### 2. Call the Memory Server

Read the `MEMORY_SERVER_URL` from the `Memory Server Configuration` section of CLAUDE.md. Use the URL exactly as configured there. If no such section exists, default to `http://127.0.0.1:8420`.

Use the Bash tool to call the `/search` endpoint, substituting the URL you read.

**This endpoint is the hook bridge, and its contract is not the obvious one.** It reads the
query from the body field **`prompt`** — a `query` field is ignored, and you silently get an
empty result. It takes the project filter from the **`x-project` header**, not from a body
field. It returns a formatted **string**, not an array. The implementation is
`rawgentic_memory/server.py` (`@app.post("/search")`), and `tests/test_recall_skill.py` pins
the two sides together.

**Without project filter:**
```bash
curl --silent --fail --connect-timeout 2 --max-time 10 \
  -X POST "MEMORY_SERVER_URL/search" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "THE_QUERY", "limit": 10}'
```

**With project filter:**
```bash
curl --silent --fail --connect-timeout 2 --max-time 10 \
  -X POST "MEMORY_SERVER_URL/search" \
  -H "Content-Type: application/json" \
  -H "x-project: PROJECT_NAME" \
  -d '{"prompt": "THE_QUERY", "limit": 10}'
```

Replace `THE_QUERY` and `PROJECT_NAME` with the actual values. Escape any double quotes in the query.

Two optional knobs are honored: `min_similarity` in the body (default `0.3` — set it lower
when a query returns nothing you expected), and an `x-max-results` header, which wins over
the body's `limit`.

### 3. Handle Errors

Check the curl exit code to distinguish failure modes:

**Exit code 7 (connection refused) — server is not running:**
```
Memory server is not running. To start it:

1. The server starts automatically on next Claude Code session start
2. Or start manually: cd <plugin-dir> && .venv/bin/python -m rawgentic_memory.server
```

**Exit code 22 (HTTP error, e.g. 503) — server is running but unhealthy:**
```
Memory server is running but returned an error. The backend may not be initialized.
Check server logs at /tmp/memorypalace-server.log for details.
```

**Any other non-zero exit — network or timeout error:**
```
Could not reach memory server. Check that MEMORY_SERVER_URL is correct
in the Memory Server Configuration section of CLAUDE.md.
```

Do NOT attempt to start the server yourself. STOP after showing the appropriate message.

### 4. Format and Display Results

Parse the JSON response. It is one formatted **string**, not an array of objects:
```json
{
  "additionalContext": "[decision] (auth) sim=0.85 project=chorestory\nThe memory content...\n\n[discovery] (recall) sim=0.72 project=rawgentic\nMore content..."
}
```

One memory is a header line followed by its content, and a blank line separates memories. The
header is `[<memory_type>] (<topic>) sim=<score> project=<project>`. The topic part and the
project part are omitted when the memory carries neither, and `memory_type` falls back to the
literal `memory`.

**This endpoint returns no timestamp, no source_file and no session_id.** The server does not
emit them. Use the `mempalace_search` MCP tool when you need those fields.

**If `additionalContext` is empty:** Tell the user "No memories found matching that query." and STOP.

Note: the server drops every memory scoring below `min_similarity` (default `0.3`) before it
builds this string. An empty result can therefore mean "nothing scored high enough" rather
than "nothing is stored". Say which one you mean when you report an empty result.

**If it is not empty:** Display the memories as a numbered list:

```
## Memory Search Results

**Query:** "<the query>"

1. **[decision]** <topic> — <project>
   <content>
   _similarity: 0.85_

2. **[discovery]** <topic> — <project>
   <content>
   _similarity: 0.72_

...
```

Each result MUST show:
- **memory_type** in brackets (e.g., `[decision]`)
- **topic** as the heading
- **project** name after the topic (so the user knows which project it came from)
- **content** as the body
- **similarity** score as metadata

This ensures results from multiple projects are clearly labeled (AC4).

---

### 5. Invalidate a Decision

When the first argument is `invalidate`, parse the remaining text as a KG triple to invalidate.

**Parsing the triple:** The text after `invalidate` should contain: `"<subject> decided <object>"` (with or without quotes).

- **Subject:** the first word (typically the project name)
- **Predicate:** always `"decided"` (hardcoded for v1)
- **Object:** everything after the word "decided"

Example: `/rawgentic-memorypalace:recall invalidate "chorestory decided use Zod"` → subject=`chorestory`, predicate=`decided`, object=`use Zod`

If the text doesn't contain "decided", tell the user: "Expected format: /rawgentic-memorypalace:recall invalidate \"<project> decided <description>\"" and STOP.

**Call the MCP tool directly:**

Use the `mempalace_kg_invalidate` MCP tool with these parameters:
- `subject`: the parsed subject
- `predicate`: `"decided"`
- `object`: the parsed object

**Display confirmation:**

If the tool succeeds:
```
Invalidated: **<subject>** decided **<object>**
This decision is now marked as historical and will be demoted in search results.
```

If the tool reports no matching triple:
```
No matching active decision found for: <subject> decided <object>
The triple may not exist or may already be invalidated.
```

If the MCP tool is not available (mempalace plugin not installed): tell the user "The mempalace MCP server is not connected. Ensure the mempalace plugin is installed and active." and STOP.

---

### 5b. Supersede a Changed Fact

When the first argument is `supersede`, the user is recording that a **single-valued fact
changed value** — a decision reversed, a model or employer swapped, an address updated. This
is the atomic replacement primitive (`mempalace_kg_supersede`): it closes the old value and
opens the new one at ONE shared boundary, so a point-in-time query at the boundary returns
only the new value. Use it instead of a hand-rolled `invalidate` + `add`, which leaves both
values open at the boundary and makes an as-of query return two.

**Parsing the argument:** the text after `supersede` is `"<subject> <predicate> <old> -> <new>"`
(with or without quotes).

1. First strip any surrounding single or double quotes from the whole argument (the search
   branch in Section 2 does the same), then find the first `->` (the arrow). If there is no
   `->`, STOP and show the expected-format message below.
2. Split once on that first `->`: **`new_object`** = everything to its RIGHT, trimmed of
   whitespace. If it is empty, STOP with the expected-format message.
3. Tokenize the text to the LEFT of the arrow (trimmed): the **first word** is `subject`, the
   **second word** is `predicate`, and the **remaining words** are `old_object`. `subject` and
   `predicate` are each a **single token** (predicate e.g. `decided`, `uses_model`, `works_at`);
   a subject or predicate containing spaces is not supported. If the left side has fewer than
   three words, STOP with the expected-format message.

The optional `at` boundary (a backdated supersede) is not parsed here — the server defaults to now.

Example: `/rawgentic-memorypalace:recall supersede "rawgentic decided use-Zod -> use-Valibot"`
→ subject=`rawgentic`, predicate=`decided`, old_object=`use-Zod`, new_object=`use-Valibot`.

If the text cannot be parsed, tell the user and STOP:

```
Expected format: /rawgentic-memorypalace:recall supersede "<subject> <predicate> <old> -> <new>" (e.g. "rawgentic decided use-Zod -> use-Valibot")
```

**Call the MCP tool directly:**

Use the `mempalace_kg_supersede` MCP tool with these parameters:
- `subject`: the parsed subject
- `predicate`: the parsed predicate
- `old_object`: the parsed old value
- `new_object`: the parsed new value

**Display confirmation:**

If the tool succeeds:
```
Superseded: **<subject> <predicate>** — **<old_object>** -> **<new_object>**
The old value is closed and the new value opened at one boundary; an as-of query now returns only the new value.
```

If the tool reports no matching active triple:
```
No matching active fact found for: <subject> <predicate> <old_object>
Nothing was superseded — check the subject/predicate/old value, or use invalidate/add if this is not a value change.
```

If the MCP tool is not available (mempalace plugin not installed): tell the user "The mempalace MCP server is not connected. Ensure the mempalace plugin is installed and active." and STOP.

---

### 6. View Timeline

When the first argument is `timeline`, the second argument is the entity name.

If no entity name is provided, ask the user: "Which project or entity timeline do you want to see?" and STOP.

**Call the MCP tool directly:**

Use the `mempalace_kg_timeline` MCP tool with:
- `entity`: the entity name

**Display the timeline** in chronological order (oldest to newest):

| # | Date | Decision | Status |
|---|------|----------|--------|
| 1 | 2026-01-15 | decided: use PostgreSQL | current |
| 2 | 2026-02-20 | decided: use Zod | invalidated |
| 3 | 2026-03-01 | decided: use Valibot | current |

Each entry MUST show:
- **valid_from** date (formatted as YYYY-MM-DD)
- **predicate** and **object** as the decision description
- **Status:** "current" if `current: true`, "invalidated" if `current: false`

If the timeline is empty: "No decision history found for <entity>." and STOP.

If the MCP tool is not available: tell the user "The mempalace MCP server is not connected. Ensure the mempalace plugin is installed and active." and STOP.

---

### 7. Browse Cross-Project Tunnels

When the first argument is `tunnels`, the optional second argument is a wing (project) name.

Read the `MEMORY_SERVER_URL` from the `Memory Server Configuration` section of CLAUDE.md. Default to `http://127.0.0.1:8420`.

**Call the tunnels endpoint:**

If a wing name is provided:
```bash
curl --silent --fail --connect-timeout 2 --max-time 10 \
  "MEMORY_SERVER_URL/tunnels?wing=WING_NAME"
```

If no wing name is provided, use the current active project from the rawgentic workspace. Determine this by reading `.rawgentic_workspace.json` and finding the most recently used active project.

**Display results:**

Parse the JSON response. The response shape is:
```json
{
  "tunnels": [
    {
      "shared_topic": "documentation",
      "connected_wings": ["chorestory", "grocusave", "rawgentic"],
      "drawer_count": 18729
    }
  ]
}
```

Format as a table:

## Cross-Project Tunnels: <wing>

| # | Shared Topic | Connected Projects | Memories |
|---|--------------|-------------------|----------|
| 1 | documentation | chorestory, grocusave, rawgentic | 18,729 |
| 2 | testing | chorestory, nillerkgames | 342 |

If no tunnels found: "No cross-project topic tunnels found for <wing>." and STOP.

Handle server errors the same as Section 3. STOP after displaying.
