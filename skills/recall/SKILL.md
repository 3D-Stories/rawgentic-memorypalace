---
name: rawgentic-memorypalace:recall
description: Search long-term memory, invalidate stale decisions, or view decision timelines. Supports subcommands: search (default), invalidate, timeline.
argument-hint: <query> | invalidate "<subject> decided <object>" | timeline <entity> | --project <name>
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
/rawgentic-memorypalace:recall timeline <entity>
```

## Instructions

### 1. Parse Arguments — Subcommand Dispatch

Check the first word of the arguments to determine the subcommand:

- **`invalidate`** → go to **Section 5: Invalidate a Decision**
- **`timeline`** → go to **Section 6: View Timeline**
- **Anything else** → treat as a search query, continue to Step 2

For search queries, extract:
- **Query text:** Everything that is not a flag. Remove surrounding quotes if present.
- **`--project <name>`:** Optional. If present, filter results to this project only.

If no arguments are provided, ask the user what they want to do and STOP.

### 2. Call the Memory Server

Read the `MEMORY_SERVER_URL` from the `Memory Server Configuration` section of CLAUDE.md. Use the URL exactly as configured there. If no such section exists, default to `http://127.0.0.1:8420`.

Use the Bash tool to call the `/search` endpoint, substituting the URL you read:

If a project filter was specified, include the `project` field. Otherwise omit it.

**Without project filter:**
```bash
curl --silent --fail --connect-timeout 2 --max-time 10 \
  -X POST "MEMORY_SERVER_URL/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "THE_QUERY", "limit": 10}'
```

**With project filter:**
```bash
curl --silent --fail --connect-timeout 2 --max-time 10 \
  -X POST "MEMORY_SERVER_URL/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "THE_QUERY", "project": "PROJECT_NAME", "limit": 10}'
```

Replace `THE_QUERY` and `PROJECT_NAME` with the actual values. Escape any double quotes in the query.

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

Parse the JSON response. The response shape is:
```json
{
  "results": [
    {
      "content": "...",
      "project": "...",
      "memory_type": "decision|event|discovery|preference|artifact",
      "topic": "...",
      "similarity": 0.85,
      "source_file": "...",
      "session_id": "...",
      "timestamp": "..."
    }
  ]
}
```

**If results are empty:** Tell the user "No memories found matching that query." and STOP.

**If results exist:** Display them as a numbered list:

```
## Memory Search Results

**Query:** "<the query>"

1. **[decision]** <topic> — <project>
   <content>
   _similarity: 0.85 | <timestamp>_

2. **[discovery]** <topic> — <project>
   <content>
   _similarity: 0.72 | <timestamp>_

...
```

Each result MUST show:
- **memory_type** in brackets (e.g., `[decision]`)
- **topic** as the heading
- **project** name after the topic (so the user knows which project it came from)
- **content** as the body
- **similarity** score and **timestamp** as metadata

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

**Call the endpoint:**

```bash
curl --silent --fail --connect-timeout 2 --max-time 10 \
  -X POST "MEMORY_SERVER_URL/kg/invalidate" \
  -H "Content-Type: application/json" \
  -d '{"subject": "SUBJECT", "predicate": "decided", "object": "OBJECT"}'
```

Replace `SUBJECT` and `OBJECT` with the parsed values. Escape any double quotes.

**Display confirmation:**

If `found` is true:
```
Invalidated: **<subject>** decided **<object>**
This decision is now marked as historical and will be demoted in search results.
```

If `found` is false:
```
No matching active decision found for: <subject> decided <object>
The triple may not exist or may already be invalidated.
```

Handle server errors the same as Section 3. STOP after displaying.

---

### 6. View Timeline

When the first argument is `timeline`, the second argument is the entity name.

If no entity name is provided, ask the user: "Which project or entity timeline do you want to see?" and STOP.

**Call the endpoint:**

```bash
curl --silent --fail --connect-timeout 2 --max-time 10 \
  "MEMORY_SERVER_URL/kg/timeline?entity=ENTITY_NAME"
```

**Display the timeline** in chronological order (oldest to newest):

```
## Decision Timeline: <entity>

| # | Date | Decision | Status |
|---|------|----------|--------|
| 1 | 2026-01-15 | decided: use PostgreSQL | current |
| 2 | 2026-02-20 | decided: use Zod | invalidated |
| 3 | 2026-03-01 | decided: use Valibot | current |
```

Each entry MUST show:
- **valid_from** date (formatted as YYYY-MM-DD)
- **predicate** and **object** as the decision description
- **Status:** "current" if `current: true`, "invalidated" if `current: false`

If the timeline is empty: "No decision history found for <entity>." and STOP.

Handle server errors the same as Section 3. STOP after displaying.
