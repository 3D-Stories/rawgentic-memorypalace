"""Tests for hook output schema compliance (Issue #41, Group 5).

AC21: all 4 hook scripts produce output matching Claude Code's hook-response schema.
AC22: mock HTTP server, no live palace needed; covers empty + populated output paths.

Claude Code hook output schema (Stop hooks use top-level fields only):
  Bridge hooks: {"hookSpecificOutput": {"hookEventName": "<Event>", "additionalContext": "<str>"}}
  Stop hooks:   {"systemMessage": "<str>"} or {"decision": "block"|"approve", "reason": "<str>"} or {}
  PreCompact:   {"decision": "block"|"approve", "reason": "<str>"}
"""

import json
import os
import subprocess
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
HOOKS_DIR = PROJECT_ROOT / "hooks"

# ---------------------------------------------------------------------------
# Mock HTTP server — responds to /healthz, /wakeup, /search, /fact_check
# ---------------------------------------------------------------------------

class _MockHandler(BaseHTTPRequestHandler):
    """Canned responses for bridge hook endpoints."""

    # Class-level flag: if True, return populated responses; if False, empty
    populated = True

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/healthz"):
            self._respond(200, {"status": "ok"})
        elif self.path.startswith("/wakeup"):
            if self.populated:
                self._respond(200, {"text": "Welcome back. Last session: testing hooks."})
            else:
                self._respond(200, {})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)

        if self.path.startswith("/search"):
            if self.populated:
                self._respond(200, {
                    "additionalContext": "Found 2 results about hook testing."
                })
            else:
                self._respond(200, {})
        elif self.path.startswith("/fact_check"):
            if self.populated:
                self._respond(200, {
                    "additionalContext": "Potential issue: function name changed from foo to bar."
                })
            else:
                self._respond(200, {})
        else:
            self._respond(404, {"error": "not found"})

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


def _start_mock_server(port, populated=True):
    """Start a mock HTTP server on the given port. Returns (server, thread)."""
    _MockHandler.populated = populated
    server = HTTPServer(("127.0.0.1", port), _MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _run_hook(script_name, hook_input, port, env_extras=None, args=None):
    """Run a hook script via subprocess with MEMORY_SERVER_URL pointed at mock."""
    script = HOOKS_DIR / script_name
    env = os.environ.copy()
    env["MEMORY_SERVER_URL"] = f"http://127.0.0.1:{port}"
    env["MEMORY_NO_AUTOSTART"] = "1"
    env["MEMORY_DEBUG"] = "0"
    env["MEMPALACE_CLAUDE_WORKSPACE"] = str(PROJECT_ROOT)
    # Use isolated state dir per test run to avoid debounce cross-pollution
    state_dir = f"/tmp/mempalace-test-{os.getpid()}"
    os.makedirs(state_dir, exist_ok=True)
    env["STATE_DIR"] = state_dir
    env["RECALL_DEBOUNCE_SECS"] = "0"
    env["FACT_CHECK_DEBOUNCE_SECS"] = "0"
    if env_extras:
        env.update(env_extras)

    cmd = [str(script)] if not script_name.endswith(".sh") else ["bash", str(script)]
    if args:
        cmd.extend(args)

    result = subprocess.run(
        cmd,
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    return result


def _validate_bridge_output(stdout, event_name):
    """Validate bridge hook output matches Claude Code schema."""
    stripped = stdout.strip()
    if not stripped:
        return  # empty output is valid (graceful degradation)

    data = json.loads(stripped)
    assert "hookSpecificOutput" in data, (
        f"Missing hookSpecificOutput key. Got: {data}"
    )
    hso = data["hookSpecificOutput"]
    assert hso["hookEventName"] == event_name, (
        f"hookEventName should be {event_name}, got {hso['hookEventName']}"
    )
    assert isinstance(hso.get("additionalContext", ""), str), (
        f"additionalContext must be a string"
    )


def _validate_stop_output(stdout):
    """Validate Stop hook output matches Claude Code schema."""
    stripped = stdout.strip()
    if not stripped:
        return

    data = json.loads(stripped)
    allowed_keys = {"continue", "suppressOutput", "stopReason", "decision",
                    "reason", "systemMessage", "permissionDecision", "hookSpecificOutput"}
    unknown = set(data.keys()) - allowed_keys
    assert not unknown, f"Unknown keys in Stop output: {unknown}"

    if "hookSpecificOutput" in data:
        hso = data["hookSpecificOutput"]
        assert hso.get("hookEventName") != "Stop", (
            "Stop hooks must NOT use hookSpecificOutput with hookEventName='Stop' — "
            "only PreToolUse/UserPromptSubmit/PostToolUse support hookSpecificOutput"
        )

    if "decision" in data:
        assert data["decision"] in ("approve", "block"), (
            f"decision must be 'approve' or 'block', got {data['decision']}"
        )

    if "systemMessage" in data:
        assert isinstance(data["systemMessage"], str)


# ---------------------------------------------------------------------------
# Bridge hook tests
# ---------------------------------------------------------------------------

class TestSessionStartSchema:
    """SessionStart hook output schema validation."""

    PORT = 18701

    @pytest.fixture(autouse=True)
    def _server(self):
        server, _ = _start_mock_server(self.PORT, populated=True)
        yield
        server.shutdown()

    def test_populated_output_matches_schema(self):
        result = _run_hook("session-start", {"cwd": str(PROJECT_ROOT)}, self.PORT)
        assert result.returncode == 0
        _validate_bridge_output(result.stdout, "SessionStart")

    def test_populated_output_has_additional_context(self):
        result = _run_hook("session-start", {"cwd": str(PROJECT_ROOT)}, self.PORT)
        data = json.loads(result.stdout.strip())
        assert data["hookSpecificOutput"]["additionalContext"] != ""


class TestSessionStartEmptySchema:
    """SessionStart hook with empty server response."""

    PORT = 18702

    @pytest.fixture(autouse=True)
    def _server(self):
        server, _ = _start_mock_server(self.PORT, populated=False)
        yield
        server.shutdown()

    def test_empty_response_graceful(self):
        result = _run_hook("session-start", {"cwd": str(PROJECT_ROOT)}, self.PORT)
        assert result.returncode == 0
        stripped = result.stdout.strip()
        if stripped:
            _validate_bridge_output(stripped, "SessionStart")


class TestUserPromptSubmitSchema:
    """UserPromptSubmit hook output schema validation."""

    PORT = 18703

    @pytest.fixture(autouse=True)
    def _server(self):
        server, _ = _start_mock_server(self.PORT, populated=True)
        yield
        server.shutdown()

    def test_populated_output_matches_schema(self):
        result = _run_hook("user-prompt-submit", {
            "cwd": str(PROJECT_ROOT),
            "prompt": "Tell me about the hook architecture and how bridge hooks work with the memory server",
        }, self.PORT)
        assert result.returncode == 0
        _validate_bridge_output(result.stdout, "UserPromptSubmit")

    def test_populated_output_has_additional_context(self):
        result = _run_hook("user-prompt-submit", {
            "cwd": str(PROJECT_ROOT),
            "prompt": "Explain the full hook schema validation approach in detail for all four hooks",
        }, self.PORT)
        data = json.loads(result.stdout.strip())
        assert data["hookSpecificOutput"]["additionalContext"] != ""


class TestUserPromptSubmitEmptySchema:
    """UserPromptSubmit with empty server response or gated-out prompt."""

    PORT = 18704

    @pytest.fixture(autouse=True)
    def _server(self):
        server, _ = _start_mock_server(self.PORT, populated=False)
        yield
        server.shutdown()

    def test_empty_response_graceful(self):
        result = _run_hook("user-prompt-submit", {
            "cwd": str(PROJECT_ROOT),
            "prompt": "A sufficiently long prompt to pass the minimum character gate for testing purposes",
        }, self.PORT)
        assert result.returncode == 0
        stripped = result.stdout.strip()
        if stripped:
            _validate_bridge_output(stripped, "UserPromptSubmit")

    def test_short_prompt_gated_out(self):
        result = _run_hook("user-prompt-submit", {
            "cwd": str(PROJECT_ROOT),
            "prompt": "ok",
        }, self.PORT)
        assert result.returncode == 0
        assert result.stdout.strip() == ""


class TestPostToolUseSchema:
    """PostToolUse hook output schema validation."""

    PORT = 18705

    @pytest.fixture(autouse=True)
    def _server(self):
        server, _ = _start_mock_server(self.PORT, populated=True)
        yield
        server.shutdown()

    def test_populated_output_matches_schema(self):
        result = _run_hook("post-tool-use", {
            "cwd": str(PROJECT_ROOT),
            "tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/test.py", "new_string": "x = 1"},
        }, self.PORT)
        assert result.returncode == 0
        _validate_bridge_output(result.stdout, "PostToolUse")

    def test_non_write_tool_no_output(self):
        result = _run_hook("post-tool-use", {
            "cwd": str(PROJECT_ROOT),
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/test.py"},
        }, self.PORT)
        assert result.returncode == 0
        assert result.stdout.strip() == ""


class TestPostToolUseEmptySchema:
    """PostToolUse with empty server response."""

    PORT = 18706

    @pytest.fixture(autouse=True)
    def _server(self):
        server, _ = _start_mock_server(self.PORT, populated=False)
        yield
        server.shutdown()

    def test_empty_fact_check_graceful(self):
        result = _run_hook("post-tool-use", {
            "cwd": str(PROJECT_ROOT),
            "tool_name": "Write",
            "tool_input": {"file_path": "/tmp/test.py", "content": "x = 1"},
        }, self.PORT)
        assert result.returncode == 0
        stripped = result.stdout.strip()
        if stripped:
            _validate_bridge_output(stripped, "PostToolUse")


# ---------------------------------------------------------------------------
# Wrapper (Stop + PreCompact) tests
# ---------------------------------------------------------------------------

class TestWrapperStopSchema:
    """Stop mode output schema validation."""

    WRAPPER = HOOKS_DIR / "mempalace-hook-wrapper.sh"

    @pytest.fixture(autouse=True)
    def _skip_if_missing(self):
        if not self.WRAPPER.exists():
            pytest.skip("wrapper not yet created")

    def _run_wrapper(self, hook_input, env_extras=None):
        return _run_hook("mempalace-hook-wrapper.sh", hook_input, 0,
                         env_extras={"MEMPALACE_STOP_BLOCK_INTERVAL_SECS": "0",
                                     **(env_extras or {})},
                         args=["stop"])

    def test_due_output_matches_schema(self):
        result = self._run_wrapper({"session_id": "schema-test-stop-due"})
        assert result.returncode == 0
        _validate_stop_output(result.stdout)

    def test_due_output_uses_system_message(self):
        result = self._run_wrapper({"session_id": "schema-test-stop-msg"})
        data = json.loads(result.stdout.strip())
        assert "systemMessage" in data
        assert "hookSpecificOutput" not in data

    def test_throttled_output_is_empty_json(self):
        result = self._run_wrapper(
            {"session_id": "schema-test-stop-throttle"},
            env_extras={"MEMPALACE_STOP_BLOCK_INTERVAL_SECS": "999999"},
        )
        # First call creates marker; this assertion applies to subsequent calls
        result2 = self._run_wrapper(
            {"session_id": "schema-test-stop-throttle"},
            env_extras={"MEMPALACE_STOP_BLOCK_INTERVAL_SECS": "999999"},
        )
        assert result2.stdout.strip() == "{}"

    def test_no_session_id_graceful(self):
        result = self._run_wrapper({})
        assert result.returncode == 0
        stripped = result.stdout.strip()
        assert stripped == "{}"


class TestWrapperPreCompactSchema:
    """PreCompact mode output schema validation (no fork — tests structure only)."""

    WRAPPER = HOOKS_DIR / "mempalace-hook-wrapper.sh"

    @pytest.fixture(autouse=True)
    def _skip_if_missing(self):
        if not self.WRAPPER.exists():
            pytest.skip("wrapper not yet created")

    def _run_wrapper(self, hook_input, env_extras=None):
        return _run_hook("mempalace-hook-wrapper.sh", hook_input, 19999,
                         env_extras=env_extras,
                         args=["precompact"])

    def test_no_session_id_blocks(self):
        result = self._run_wrapper({})
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["decision"] == "block"
        assert isinstance(data["reason"], str)

    def test_no_workspace_blocks(self):
        result = self._run_wrapper(
            {"session_id": "schema-test-precompact-nows"},
            env_extras={"MEMPALACE_CLAUDE_WORKSPACE": ""},
        )
        assert result.returncode == 0
        data = json.loads(result.stdout.strip())
        assert data["decision"] == "block"

    def test_recursion_guard_returns_empty(self):
        result = self._run_wrapper({"session_id": "x", "stop_hook_active": "true"})
        assert result.returncode == 0
        assert result.stdout.strip() == "{}"
