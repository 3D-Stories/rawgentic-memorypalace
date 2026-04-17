#!/bin/bash
# Shared library for rawgentic-memorypalace hook scripts.
# Provides memory server communication with graceful degradation and lazy-start.
# NO set -e — curl/jq non-zero returns must not abort hooks silently.

# ---------------------------------------------------------------------------
# Configuration — all thresholds env-configurable from v1
# ---------------------------------------------------------------------------

# Server URL
MEMORY_SERVER_URL="${MEMORY_SERVER_URL:-http://127.0.0.1:8420}"

# Debug logging — set MEMORY_DEBUG=1 to log to stderr
MEMORY_DEBUG="${MEMORY_DEBUG:-0}"

# State directory for timer files and server logs
STATE_DIR="${STATE_DIR:-/tmp}"

# Set MEMORY_NO_AUTOSTART=1 to disable lazy-start (useful for testing)
MEMORY_NO_AUTOSTART="${MEMORY_NO_AUTOSTART:-0}"

# Plugin venv Python path (derived from script location if not set)
PLUGIN_VENV="${PLUGIN_VENV:-}"

# Workspace root — for session registry lookups.
# Auto-detected from hook input .cwd by each hook script; env var overrides.
MEMPALACE_CLAUDE_WORKSPACE="${MEMPALACE_CLAUDE_WORKSPACE:-}"

# --- Smart-gate thresholds ---
# Minimum prompt character count to trigger recall
RECALL_MIN_PROMPT_CHARS="${RECALL_MIN_PROMPT_CHARS:-20}"

# Seconds of debounce between recall calls (per project)
RECALL_DEBOUNCE_SECS="${RECALL_DEBOUNCE_SECS:-30}"

# Cosine similarity threshold for /search results
RECALL_SIMILARITY_THRESHOLD="${RECALL_SIMILARITY_THRESHOLD:-0.30}"

# Maximum results returned from /search
RECALL_MAX_RESULTS="${RECALL_MAX_RESULTS:-5}"

# Seconds of debounce between fact-check calls (per project)
FACT_CHECK_DEBOUNCE_SECS="${FACT_CHECK_DEBOUNCE_SECS:-60}"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_debug() {
    if [[ "$MEMORY_DEBUG" == "1" ]]; then
        echo "[memorypalace] $*" >&2
    fi
}

# Resolve the Python interpreter from the plugin's venv.
_resolve_python() {
    if [[ -n "$PLUGIN_VENV" && -x "$PLUGIN_VENV" ]]; then
        echo "$PLUGIN_VENV"
        return 0
    fi

    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local venv_python="${script_dir}/../.venv/bin/python3"

    if [[ -x "$venv_python" ]]; then
        echo "$venv_python"
        return 0
    fi

    _debug "No venv python at $venv_python — cannot start server"
    return 1
}

# ---------------------------------------------------------------------------
# server_is_healthy — curl /healthz with 1s timeout
# Returns 0 if healthy, 1 otherwise. No side effects.
# ---------------------------------------------------------------------------
server_is_healthy() {
    curl --silent --fail --connect-timeout 1 --max-time 2 \
        "${MEMORY_SERVER_URL}/healthz" >/dev/null 2>&1
}

# ---------------------------------------------------------------------------
# ensure_server_running — health check → lazy-start with flock → poll 10s
# Returns 0 if server reachable, 1 otherwise.
# ---------------------------------------------------------------------------
ensure_server_running() {
    if server_is_healthy; then
        _debug "Server already running"
        return 0
    fi

    if [[ "$MEMORY_NO_AUTOSTART" == "1" ]]; then
        _debug "MEMORY_NO_AUTOSTART=1 — skipping lazy-start"
        return 1
    fi

    local python
    python=$(_resolve_python) || return 1

    # Extract port from MEMORY_SERVER_URL
    local port
    port=$(echo "$MEMORY_SERVER_URL" | grep -oP '://[^/]+:\K[0-9]+') || true
    port="${port:-8420}"

    local lockfile="${STATE_DIR}/memorypalace-start.lock"
    local logfile="${STATE_DIR}/memorypalace-server.log"

    mkdir -p "$(dirname "$lockfile")" || true

    # Use flock to prevent concurrent start attempts
    (
        if ! flock --nonblock --exclusive 200 2>/dev/null; then
            _debug "Another process is starting the server — waiting for healthz"
        else
            _debug "Starting memory server on port $port"
            "$python" -m rawgentic_memory.server --port "$port" --timeout 14400 \
                >> "$logfile" 2>&1 &
            disown 2>/dev/null || true
        fi
    ) 200>"$lockfile"

    # Poll /healthz — wait up to 10 seconds (20 x 0.5s)
    local max_attempts=20
    local i
    for (( i=1; i<=max_attempts; i++ )); do
        if server_is_healthy; then
            _debug "Server ready after $i poll(s)"
            return 0
        fi
        sleep 0.5
    done

    _debug "Server failed to start within 10 seconds"
    return 1
}

# ---------------------------------------------------------------------------
# should_search <prompt> <project>
# Returns 0 (search allowed) or 1 (skip).
# Gates: prompt length, slash command, stop-words, debounce.
# ---------------------------------------------------------------------------
should_search() {
    local prompt="$1"
    local project="$2"

    # Gate 1: minimum length
    local prompt_len=${#prompt}
    if [[ "$prompt_len" -lt "$RECALL_MIN_PROMPT_CHARS" ]]; then
        _debug "should_search: skip — prompt too short ($prompt_len < $RECALL_MIN_PROMPT_CHARS)"
        return 1
    fi

    # Gate 2: slash commands (e.g. /commit, /help)
    if [[ "$prompt" =~ ^[[:space:]]*/[a-zA-Z] ]]; then
        _debug "should_search: skip — slash command"
        return 1
    fi

    # Gate 3: case-insensitive stop-words / short ack phrases
    local prompt_lower="${prompt,,}"
    # Single-word acks
    if [[ "$prompt_lower" =~ ^[[:space:]]*(yes|no|ok|okay|sure|lgtm|thanks|done|cool|great|perfect|proceed|continue|y|n)[[:space:]]*$ ]]; then
        _debug "should_search: skip — stop-word ack"
        return 1
    fi
    # Multi-word ack phrases
    if [[ "$prompt_lower" =~ ^[[:space:]]*(looks[[:space:]]+good|sounds[[:space:]]+good|do[[:space:]]+it|go[[:space:]]+ahead|that[[:space:]]+(works|looks|sounds)[[:space:]]+(good|fine|right))[[:space:]]*$ ]]; then
        _debug "should_search: skip — multi-word ack phrase"
        return 1
    fi

    # Gate 4: debounce — skip if called within RECALL_DEBOUNCE_SECS
    local safe_project
    safe_project=$(echo "$project" | tr -cd 'a-zA-Z0-9_-')
    safe_project="${safe_project:-default}"
    local debounce_file="${STATE_DIR}/memorypalace-recall-debounce-${safe_project}"
    local now
    now=$(date +%s)

    if [[ -f "$debounce_file" ]]; then
        local last_recall
        last_recall=$(cat "$debounce_file" 2>/dev/null) || true
        if [[ "$last_recall" =~ ^[0-9]+$ ]]; then
            local elapsed=$(( now - last_recall ))
            if [[ "$elapsed" -lt "$RECALL_DEBOUNCE_SECS" ]]; then
                _debug "should_search: skip — debounce ($elapsed < $RECALL_DEBOUNCE_SECS s)"
                return 1
            fi
        fi
    fi

    # Update debounce timestamp
    echo "$now" > "$debounce_file" || true

    _debug "should_search: allow"
    return 0
}

# ---------------------------------------------------------------------------
# should_fact_check <file_path> <project>
# Returns 0 (fact-check allowed) or 1 (skip).
# Gates: path required, debounce, per-file dedup.
# ---------------------------------------------------------------------------
should_fact_check() {
    local file_path="$1"
    local project="$2"

    # Gate 1: path required
    if [[ -z "$file_path" ]]; then
        _debug "should_fact_check: skip — no file path"
        return 1
    fi

    local safe_project
    safe_project=$(echo "$project" | tr -cd 'a-zA-Z0-9_-')
    safe_project="${safe_project:-default}"

    # Gate 2: per-project fact-check debounce
    local debounce_file="${STATE_DIR}/memorypalace-factcheck-debounce-${safe_project}"
    local now
    now=$(date +%s)

    if [[ -f "$debounce_file" ]]; then
        local last_check
        last_check=$(cat "$debounce_file" 2>/dev/null) || true
        if [[ "$last_check" =~ ^[0-9]+$ ]]; then
            local elapsed=$(( now - last_check ))
            if [[ "$elapsed" -lt "$FACT_CHECK_DEBOUNCE_SECS" ]]; then
                _debug "should_fact_check: skip — debounce ($elapsed < $FACT_CHECK_DEBOUNCE_SECS s)"
                return 1
            fi
        fi
    fi

    # Gate 3: per-file dedup — skip if this exact file was recently fact-checked
    local file_hash
    file_hash=$(printf '%s' "$file_path" | md5sum | cut -d' ' -f1) || true
    local file_dedup_marker="${STATE_DIR}/memorypalace-factcheck-file-${file_hash}"

    if [[ -f "$file_dedup_marker" ]]; then
        local last_file_check
        last_file_check=$(cat "$file_dedup_marker" 2>/dev/null) || true
        if [[ "$last_file_check" =~ ^[0-9]+$ ]]; then
            local file_elapsed=$(( now - last_file_check ))
            if [[ "$file_elapsed" -lt "$FACT_CHECK_DEBOUNCE_SECS" ]]; then
                _debug "should_fact_check: skip — file dedup ($file_path checked ${file_elapsed}s ago)"
                return 1
            fi
        fi
    fi

    # Update both debounce states
    echo "$now" > "$debounce_file" || true
    echo "$now" > "$file_dedup_marker" || true

    _debug "should_fact_check: allow ($file_path)"
    return 0
}

# ---------------------------------------------------------------------------
# resolve_project [cwd]
# Looks up session registry for most-recently-used active project.
# Falls back to basename of cwd, then "unknown".
# ---------------------------------------------------------------------------
resolve_project() {
    local cwd="${1:-}"

    # Try workspace registry — most recently used active project
    local workspace="${MEMPALACE_CLAUDE_WORKSPACE:-$cwd}"
    local workspace_json="${workspace:+$workspace/.rawgentic_workspace.json}"
    if [[ -n "$workspace_json" && -f "$workspace_json" ]]; then
        local reg_project
        reg_project=$(jq -r '[.projects[] | select(.active==true)] | sort_by(.lastUsed) | last | .name // empty' \
            "$workspace_json" 2>/dev/null) || true
        if [[ -n "$reg_project" ]]; then
            _debug "resolve_project: registry → $reg_project"
            echo "$reg_project"
            return 0
        fi
    fi

    # Fallback: basename of cwd
    if [[ -n "$cwd" ]]; then
        local basename_project
        basename_project=$(basename "$cwd" 2>/dev/null) || true
        basename_project=$(echo "$basename_project" | tr -cd 'a-zA-Z0-9_-')
        if [[ -n "$basename_project" ]]; then
            _debug "resolve_project: cwd basename → $basename_project"
            echo "$basename_project"
            return 0
        fi
    fi

    _debug "resolve_project: fallback → unknown"
    echo "unknown"
}

# ---------------------------------------------------------------------------
# Legacy helpers (kept for backward compatibility)
# ---------------------------------------------------------------------------

# Read JSON from stdin into HOOK_INPUT variable
read_hook_input() {
    HOOK_INPUT=$(cat)
    _debug "Hook input: $HOOK_INPUT"
}

# Extract a field from HOOK_INPUT using jq
get_field() {
    local field="$1"
    echo "$HOOK_INPUT" | jq -r ".$field // empty" 2>/dev/null
}

# Call the memory server. Returns 0 on success, 1 on failure.
# Usage: call_memory_server <endpoint> [method] [body]
call_memory_server() {
    local endpoint="$1"
    local method="${2:-GET}"
    local body="${3:-}"

    local url="${MEMORY_SERVER_URL}${endpoint}"
    local curl_args=(
        --silent
        --fail
        --connect-timeout 2
        --max-time 5
        -X "$method"
    )

    if [[ -n "$body" ]]; then
        curl_args+=(-H "Content-Type: application/json" -d "$body")
    fi

    _debug "Calling $method $url"

    local response
    response=$(curl "${curl_args[@]}" "$url" 2>/dev/null) || true
    if [[ -n "$response" ]]; then
        echo "$response"
        return 0
    fi
    return 1
}

# Read session notes from a project directory.
gather_session_notes() {
    local cwd="$1"
    if [[ -z "$cwd" ]]; then
        return 0
    fi

    local notes_path
    notes_path="$(realpath "${cwd}/claude_docs/session_notes.md" 2>/dev/null)" || true

    if [[ -z "$notes_path" ]]; then
        _debug "Could not resolve session notes path"
        return 0
    fi

    local safe_home
    safe_home="$(realpath "$HOME" 2>/dev/null || echo "$HOME")"
    if [[ "$notes_path" != "$safe_home"/* ]]; then
        _debug "Session notes path $notes_path is not under HOME ($safe_home) — rejected"
        return 0
    fi

    if [[ ! -f "$notes_path" ]]; then
        _debug "Session notes file not found: $notes_path"
        return 0
    fi

    cat "$notes_path"
}

# Build a JSON payload for the /ingest endpoint.
build_ingest_payload() {
    local project="$1"
    local session_id="$2"
    local notes="$3"
    local source="$4"
    local source_file="${5:-}"
    local timestamp
    timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    if [[ -z "$session_id" ]]; then
        session_id="hook-$(date +%s)"
    fi

    jq -n \
        --arg session_id "$session_id" \
        --arg project "$project" \
        --arg notes "$notes" \
        --arg source "$source" \
        --arg timestamp "$timestamp" \
        --arg source_file "$source_file" \
        '{session_id: $session_id, project: $project, notes: $notes,
          source: $source, timestamp: $timestamp, source_file: $source_file}'
}
