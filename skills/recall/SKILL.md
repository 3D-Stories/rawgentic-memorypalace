---
name: rawgentic-memorypalace:recall
description: Search long-term memory by natural language query. Calls the memory server /search endpoint and displays results with content, project, memory_type, and similarity. Use when the user wants to find past decisions, discoveries, or events stored in memory.
argument-hint: Natural language query, optionally with --project <name> to filter
---

# /recall — Semantic Memory Search

Search your long-term memory for past decisions, discoveries, and events.

## Usage

```
/recall <query>
/recall <query> --project <project-name>
```

## Instructions

### 1. Parse Arguments

Extract the search query and optional flags from the arguments:

- **Query text:** Everything that is not a flag. Remove surrounding quotes if present.
- **`--project <name>`:** Optional. If present, filter results to this project only.

If no query is provided, ask the user what they want to search for and STOP.

### 2. Call the Memory Server

The memory server URL is `${MEMORY_SERVER_URL:-http://127.0.0.1:8420}`.

Use the Bash tool to call the `/search` endpoint:

```bash
MEMORY_SERVER_URL="${MEMORY_SERVER_URL:-http://127.0.0.1:8420}"
curl --silent --fail --connect-timeout 2 --max-time 10 \
  -X POST "${MEMORY_SERVER_URL}/search" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg query "THE_QUERY" --arg project "PROJECT_OR_EMPTY" \
    'if $project == "" then {query: $query, limit: 10}
     else {query: $query, project: $project, limit: 10} end')"
```

Replace `THE_QUERY` with the user's query and `PROJECT_OR_EMPTY` with the project name (or empty string if not specified).

### 3. Handle Server Not Reachable

If curl fails (exit code 7 = connection refused, or any non-zero exit):

Display this message to the user:
```
Memory server is not running. To start it:

1. The server starts automatically on next Claude Code session start
2. Or start manually: cd <plugin-dir> && .venv/bin/python -m rawgentic_memory.server
```

Do NOT attempt to start the server yourself. STOP after showing the message.

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
