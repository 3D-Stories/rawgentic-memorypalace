#!/bin/bash
# mempalace-hook-wrapper.sh {precompact|stop}
#
# Stop mode:       time-throttled. On non-due turns: no-op. On due turns:
#                  inject AUTO-SAVE instruction via systemMessage so Claude
#                  saves via MCP. Stop hooks only support top-level fields
#                  (systemMessage, decision, stopReason) — NOT hookSpecificOutput.
#                  Recursion guard retained as defense-in-depth.
#
# PreCompact mode: fork-resume the session, save via MCP, approve compact on
#                  success or BLOCK on failure (information loss is unacceptable
#                  per project policy). Slower, but compact is a one-shot
#                  user-initiated event so the latency is acceptable.
#
# NO set -e — graceful degradation requires non-zero returns to be handled
# explicitly. curl/jq non-zero must not abort hooks silently.
#
# Env overrides:
#   CLAUDE_BIN                            default: ~/.local/bin/claude
#   MEMPALACE_CLAUDE_WORKSPACE            override: auto-detected from hook input .cwd
#   MEMPALACE_STOP_BLOCK_INTERVAL_SECS    default: 900 (15 min) — stop mode throttle
#   MEMPALACE_PRECOMPACT_TIMEOUT_SECS     default: 180 (3 min) — precompact fork timeout

MODE="${1:-}"
if [[ "$MODE" != "precompact" && "$MODE" != "stop" ]]; then
    echo "usage: $0 <precompact|stop>" >&2
    exit 2
fi
INPUT=$(cat)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null) || true
# Path-safety: session_id is interpolated into marker + fallback filenames.
SESSION_ID=$(printf '%s' "$SESSION_ID" | tr -cd 'A-Za-z0-9-')
STOP_ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // empty' 2>/dev/null) || true
HOOK_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null) || true
LOG="$HOME/.mempalace-hook-wrapper.log"
STATE_DIR="$HOME/.mempalace-wrapper-state"
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
STOP_BLOCK_INTERVAL_SECS="${MEMPALACE_STOP_BLOCK_INTERVAL_SECS:-900}"
PRECOMPACT_TIMEOUT_SECS="${MEMPALACE_PRECOMPACT_TIMEOUT_SECS:-180}"
# Workspace root for --resume: auto-detect from hook input .cwd, override via env.
CLAUDE_WORKSPACE="${MEMPALACE_CLAUDE_WORKSPACE:-$HOOK_CWD}"

mkdir -p "$STATE_DIR" 2>/dev/null || true

json_escape() { printf '%s' "$1" | jq -Rs .; }
log() { echo "[$(date -Iseconds)] [$MODE] $*" >> "$LOG"; }

AUTO_SAVE_REASON='AUTO-SAVE checkpoint (MemPalace). Save this session'\''s key content:
1. mempalace_diary_write — AAAK-compressed session summary
2. mempalace_add_drawer — verbatim quotes, decisions, code snippets
3. mempalace_kg_add — entity relationships (optional)
MemPalace is the authoritative memory store (owner decision 2026-07-08, rawgentic#304): save substantive content ONLY via the MCP tools above — never as new Claude Code native auto-memory .md files (the native MEMORY.md is a frozen thin pointer index). Continue conversation after saving.'

# --- Recursion guard: post-save Stop refire OR our own forked-resume call ---
if [[ "$STOP_ACTIVE" == "true" ]] || [[ -n "${MEMPALACE_SAVE_IN_PROGRESS:-}" ]]; then
    log "recursion guard hit; no-op"
    printf '{}'
    exit 0
fi

# --- No session id → can't fork or address the right session for save ---
if [[ -z "$SESSION_ID" ]]; then
    if [[ "$MODE" == "precompact" ]]; then
        R=$(json_escape "PreCompact: no session_id in hook input; refusing to compact (information loss risk).")
        printf '{"decision":"block","reason":%s}' "$R"
    else
        echo "⚠️  MemPalace auto-save skipped — no session_id in hook input. Recent turns NOT persisted." >&2
        log "no session_id; warned to stderr"
        printf '{}'
    fi
    exit 0
fi

# ============================================================================
# STOP MODE — inject save context on N-min interval; no fork
# ============================================================================
if [[ "$MODE" == "stop" ]]; then
    MARKER="$STATE_DIR/last-save-$SESSION_ID"
    LOCK="$STATE_DIR/last-save-$SESSION_ID.lock"
    DECISION=""
    ELAPSED_VAL=0

    # Critical section: serialize concurrent Stop fires via flock.
    {
        flock -x 9
        LAST=$(cat "$MARKER" 2>/dev/null || echo 0)
        [[ "$LAST" =~ ^[0-9]+$ ]] || LAST=0
        NOW=$(date +%s)
        ELAPSED_VAL=$((NOW - LAST))
        if [[ $ELAPSED_VAL -lt $STOP_BLOCK_INTERVAL_SECS ]]; then
            DECISION="throttle"
        else
            DECISION="due"
            echo "$NOW" > "$MARKER"
            sync
        fi
    } 9>"$LOCK"

    if [[ "$DECISION" == "throttle" ]]; then
        printf '{}'
        exit 0
    fi

    # Due. Inject save instruction via systemMessage (Stop hooks don't
    # support hookSpecificOutput — only PreToolUse/UserPromptSubmit/PostToolUse do).
    log "injecting save context (${ELAPSED_VAL}s since last)"
    R=$(json_escape "$AUTO_SAVE_REASON")
    printf '{"systemMessage":%s}' "$R"
    exit 0
fi

# ============================================================================
# PRECOMPACT MODE — fork + save + approve, or BLOCK on failure
# ============================================================================
if [[ -z "$CLAUDE_WORKSPACE" ]]; then
    R=$(json_escape "PreCompact: no workspace detected (no .cwd in hook input, no MEMPALACE_CLAUDE_WORKSPACE). Refusing to compact.")
    printf '{"decision":"block","reason":%s}' "$R"
    exit 0
fi

log "forking session $SESSION_ID (workspace=$CLAUDE_WORKSPACE, timeout=${PRECOMPACT_TIMEOUT_SECS}s)"
# rawgentic#306: NO `|| true` here — it made $? always 0, so the old block
# path was dead code and every fork failure silently approved with no save.
SAVE_OUTPUT=$(cd "$CLAUDE_WORKSPACE" && MEMPALACE_SAVE_IN_PROGRESS=1 timeout "$PRECOMPACT_TIMEOUT_SECS" "$CLAUDE_BIN" \
    --resume "$SESSION_ID" --fork-session --disable-slash-commands -p \
    'Save the current session to mempalace NOW: (1) call mempalace_diary_write with an AAAK-compressed semantic summary, (2) call mempalace_add_drawer for key verbatim content — decisions, code, quotes. Be thorough but fast. Respond with a one-line confirmation like "Saved N drawers + diary" and nothing else.' \
    2>&1)
SAVE_EXIT=$?
log "fork exit=$SAVE_EXIT"
printf '%s\n---\n' "$SAVE_OUTPUT" | tail -20 >> "$LOG"

# Success requires BOTH a clean exit AND the positive confirmation the prompt
# demands ("Saved N drawers + diary", N >= 1) — a mempalace outage leaves
# claude -p exiting 0 while reporting failure in prose, and failure prose can
# contain "saved…drawer" ("I have NOT saved any drawers"), so the pattern is
# positive-only. A false NEGATIVE is safe: it fires the degraded path, which
# preserves the transcript and still approves.
SAVE_OK=0
if [[ $SAVE_EXIT -eq 0 ]] && printf '%s' "$SAVE_OUTPUT" | grep -qiE 'saved [1-9][0-9]* drawers?'; then
    SAVE_OK=1
fi

if [[ $SAVE_OK -eq 1 ]]; then
    R=$(json_escape "PreCompact: session saved to mempalace (forked). Compaction allowed.")
    printf '{"decision":"approve","reason":%s}' "$R"
    exit 0
fi

# --- Degraded path (rawgentic#306): mempalace save failed → local transcript
# fallback, approve loudly; block ONLY when both fail. ---
FALLBACK_DIR="${MEMPALACE_PRECOMPACT_FALLBACK_DIR:-$STATE_DIR/precompact-fallback}"
log "save FAILED (exit=$SAVE_EXIT, confirmation absent) — attempting local transcript fallback to $FALLBACK_DIR"

TRANSCRIPT=""
for f in "$HOME"/.claude/projects/*/"$SESSION_ID".jsonl; do
    [[ -f "$f" ]] && TRANSCRIPT="$f" && break
done

# Zero-byte transcript: nothing to preserve — degraded approve, never a wedge.
if [[ -n "$TRANSCRIPT" && ! -s "$TRANSCRIPT" ]]; then
    MSG="PreCompact DEGRADED: mempalace save failed (fork exit $SAVE_EXIT) and the session transcript at $TRANSCRIPT is empty — nothing to preserve. Compaction allowed. See $LOG."
    echo "⚠️  $MSG" >&2
    log "$MSG"
    R=$(json_escape "$MSG")
    printf '{"decision":"approve","reason":%s}' "$R"
    exit 0
fi

FALLBACK_OK=0
FALLBACK_DEST=""
if [[ -n "$TRANSCRIPT" ]]; then
    # ponytail: fallback dir grows unbounded across repeated outage compacts —
    # operator cleanup; add pruning if it ever matters.
    mkdir -p "$FALLBACK_DIR" 2>/dev/null || true
    FALLBACK_DEST="$FALLBACK_DIR/${SESSION_ID}-$(date +%s).jsonl"
    if cp "$TRANSCRIPT" "$FALLBACK_DEST" 2>/dev/null && [[ -s "$FALLBACK_DEST" ]]; then
        FALLBACK_OK=1
    fi
fi

if [[ $FALLBACK_OK -eq 1 ]]; then
    MSG="PreCompact DEGRADED: mempalace save failed (fork exit $SAVE_EXIT) — full session transcript preserved locally at $FALLBACK_DEST. Compaction allowed; re-ingest the transcript when mempalace is back. See $LOG."
    echo "⚠️  $MSG" >&2
    log "$MSG"
    R=$(json_escape "$MSG")
    printf '{"decision":"approve","reason":%s}' "$R"
    exit 0
fi

MSG="PreCompact: BOTH saves failed — mempalace fork-save (exit $SAVE_EXIT) AND local transcript fallback (transcript ${TRANSCRIPT:-not found}, dest ${FALLBACK_DEST:-n/a}). Blocking compact: information loss is unacceptable. See $LOG."
echo "⚠️  $MSG" >&2
log "$MSG"
R=$(json_escape "$MSG")
printf '{"decision":"block","reason":%s}' "$R"
