#!/bin/bash
# Shared library for rawgentic-memorypalace hook scripts.
# Provides memory server communication with graceful degradation.

# Server URL — override via environment variable
MEMORY_SERVER_URL="${MEMORY_SERVER_URL:-http://127.0.0.1:8420}"

# Debug logging — set MEMORY_DEBUG=1 to log to stderr
MEMORY_DEBUG="${MEMORY_DEBUG:-0}"

# State directory for timer files
MEMORY_STATE_DIR="${MEMORY_STATE_DIR:-/tmp}"

_debug() {
    if [[ "$MEMORY_DEBUG" == "1" ]]; then
        echo "[memorypalace] $*" >&2
    fi
}

# Call the memory server. Returns 0 on success, 1 on failure.
# Usage: call_memory_server <endpoint> [method] [body]
# Output: server response on stdout (if any)
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
    if response=$(curl "${curl_args[@]}" "$url" 2>/dev/null); then
        _debug "Response: $response"
        echo "$response"
        return 0
    else
        _debug "Server unreachable or error at $url"
        return 1
    fi
}

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
