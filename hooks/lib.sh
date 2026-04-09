#!/bin/bash
# Shared library for rawgentic-memorypalace hook scripts.
# Provides memory server communication with graceful degradation and lazy-start.

# Server URL — override via environment variable
MEMORY_SERVER_URL="${MEMORY_SERVER_URL:-http://127.0.0.1:8420}"

# Debug logging — set MEMORY_DEBUG=1 to log to stderr
MEMORY_DEBUG="${MEMORY_DEBUG:-0}"

# State directory for timer files and server logs
MEMORY_STATE_DIR="${MEMORY_STATE_DIR:-/tmp}"

# Set MEMORY_NO_AUTOSTART=1 to disable lazy-start (useful for testing)
MEMORY_NO_AUTOSTART="${MEMORY_NO_AUTOSTART:-0}"

_debug() {
    if [[ "$MEMORY_DEBUG" == "1" ]]; then
        echo "[memorypalace] $*" >&2
    fi
}

# Resolve the Python interpreter from the plugin's venv.
# Derives path from this script's location (hooks/ -> ../.venv/bin/python3).
_resolve_python() {
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

# Start the memory server if it's not already running.
# Uses flock to prevent concurrent start attempts.
# Returns 0 if server is reachable after this call, 1 otherwise.
ensure_server_running() {
    # Quick check: is it already up?
    if curl --silent --fail --connect-timeout 1 "${MEMORY_SERVER_URL}/healthz" >/dev/null 2>&1; then
        _debug "Server already running"
        return 0
    fi

    # Opt-out for testing
    if [[ "$MEMORY_NO_AUTOSTART" == "1" ]]; then
        _debug "MEMORY_NO_AUTOSTART=1 — skipping lazy-start"
        return 1
    fi

    local python
    python=$(_resolve_python) || return 1

    # Extract port from MEMORY_SERVER_URL
    local port
    port=$(echo "$MEMORY_SERVER_URL" | grep -oP '://[^/]+:\K[0-9]+' || echo "8420")

    local lockfile="${MEMORY_STATE_DIR}/memorypalace-start.lock"
    local logfile="${MEMORY_STATE_DIR}/memorypalace-server.log"

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
    for (( i=1; i<=max_attempts; i++ )); do
        if curl --silent --fail --connect-timeout 1 "${MEMORY_SERVER_URL}/healthz" >/dev/null 2>&1; then
            _debug "Server ready after $i poll(s)"
            return 0
        fi
        sleep 0.5
    done

    _debug "Server failed to start within 10 seconds"
    return 1
}

# Call the memory server. Returns 0 on success, 1 on failure.
# On connection refused (curl exit 7), attempts lazy-start before retrying.
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
    response=$(curl "${curl_args[@]}" "$url" 2>/dev/null)
    local curl_exit=$?

    if [[ $curl_exit -eq 0 ]]; then
        _debug "Response: $response"
        echo "$response"
        return 0
    fi

    # Exit code 7 = connection refused (server not running)
    # Any other error = server is running but returned an error — don't restart
    if [[ $curl_exit -ne 7 ]]; then
        _debug "Server returned error (curl exit $curl_exit) at $url"
        return 1
    fi

    _debug "Connection refused — attempting lazy-start"
    if ! ensure_server_running; then
        _debug "Lazy-start failed — returning silently"
        return 1
    fi

    # Retry the original call
    _debug "Retrying $method $url after lazy-start"
    if response=$(curl "${curl_args[@]}" "$url" 2>/dev/null); then
        _debug "Response: $response"
        echo "$response"
        return 0
    else
        _debug "Retry failed at $url"
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
