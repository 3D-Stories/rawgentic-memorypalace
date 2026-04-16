"""Integration: hooks degrade gracefully when server is unavailable.

Each hook is run as a subprocess against a non-existent server (port 65535).
All must return exit code 0 with empty stdout (no hookSpecificOutput).
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "hooks")
DEAD_SERVER_URL = "http://127.0.0.1:65535"


def _run_hook(hook_name: str, stdin_data: str, tmp_dir: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    """Run a hook script as a subprocess against a dead server."""
    env = {
        **os.environ,
        "MEMORY_SERVER_URL": DEAD_SERVER_URL,
        "MEMORY_NO_AUTOSTART": "1",
        "MEMORY_DEBUG": "0",
        "STATE_DIR": tmp_dir,
        # Ensure debounce doesn't interfere
        "RECALL_DEBOUNCE_SECS": "0",
        "FACT_CHECK_DEBOUNCE_SECS": "0",
    }
    if extra_env:
        env.update(extra_env)

    hook_path = os.path.join(HOOKS_DIR, hook_name)
    return subprocess.run(
        ["bash", hook_path],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )


class TestGracefulDegradation:
    def test_session_start_degrades_gracefully(self, tmp_path):
        """session-start must exit 0 with no stdout when server is down."""
        hook_input = json.dumps({"cwd": "/tmp"})
        result = _run_hook("session-start", hook_input, str(tmp_path))
        assert result.returncode == 0, f"exit={result.returncode} stderr={result.stderr}"
        assert result.stdout.strip() == "", f"stdout should be empty, got: {result.stdout!r}"

    def test_user_prompt_submit_degrades_gracefully(self, tmp_path):
        """user-prompt-submit must exit 0 with no stdout when server is down."""
        hook_input = json.dumps({
            "prompt": "Tell me about the server architecture and how it works in production",
            "cwd": "/tmp",
        })
        result = _run_hook("user-prompt-submit", hook_input, str(tmp_path))
        assert result.returncode == 0, f"exit={result.returncode} stderr={result.stderr}"
        assert result.stdout.strip() == "", f"stdout should be empty, got: {result.stdout!r}"

    def test_post_tool_use_degrades_gracefully(self, tmp_path):
        """post-tool-use must exit 0 with no stdout when server is down."""
        hook_input = json.dumps({
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/tmp/test.py",
                "new_string": "print('hello world')",
            },
            "cwd": "/tmp",
        })
        result = _run_hook("post-tool-use", hook_input, str(tmp_path))
        assert result.returncode == 0, f"exit={result.returncode} stderr={result.stderr}"
        assert result.stdout.strip() == "", f"stdout should be empty, got: {result.stdout!r}"
