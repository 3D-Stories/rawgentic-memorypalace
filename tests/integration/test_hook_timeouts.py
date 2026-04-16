"""Integration: hook timeout compliance under cold-start conditions.

Measures wall-clock time of each hook when the server is unreachable.
With MEMORY_NO_AUTOSTART=1, hooks should fail-fast (curl connect-timeout).
Budgets: session-start < 10s, user-prompt-submit < 5s, post-tool-use < 5s.
"""
from __future__ import annotations

import json
import os
import subprocess
import time

import pytest

HOOKS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "hooks")
DEAD_SERVER_URL = "http://127.0.0.1:65535"


def _timed_hook(hook_name: str, stdin_data: str, tmp_dir: str) -> tuple[float, subprocess.CompletedProcess]:
    """Run a hook and measure wall-clock time."""
    env = {
        **os.environ,
        "MEMORY_SERVER_URL": DEAD_SERVER_URL,
        "MEMORY_NO_AUTOSTART": "1",
        "MEMORY_DEBUG": "0",
        "STATE_DIR": tmp_dir,
        "RECALL_DEBOUNCE_SECS": "0",
        "FACT_CHECK_DEBOUNCE_SECS": "0",
    }
    hook_path = os.path.join(HOOKS_DIR, hook_name)
    t0 = time.monotonic()
    result = subprocess.run(
        ["bash", hook_path],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )
    elapsed = time.monotonic() - t0
    return elapsed, result


class TestHookTimeouts:
    def test_session_start_under_10s(self, tmp_path):
        """session-start must complete within 10s when server is down."""
        hook_input = json.dumps({"cwd": "/tmp"})
        elapsed, result = _timed_hook("session-start", hook_input, str(tmp_path))
        assert result.returncode == 0
        assert elapsed < 10, f"session-start took {elapsed:.2f}s (budget: 10s)"

    def test_user_prompt_submit_under_5s(self, tmp_path):
        """user-prompt-submit must complete within 5s when server is down."""
        hook_input = json.dumps({
            "prompt": "Tell me about the server architecture and how it works in production",
            "cwd": "/tmp",
        })
        elapsed, result = _timed_hook("user-prompt-submit", hook_input, str(tmp_path))
        assert result.returncode == 0
        assert elapsed < 5, f"user-prompt-submit took {elapsed:.2f}s (budget: 5s)"

    def test_post_tool_use_under_5s(self, tmp_path):
        """post-tool-use must complete within 5s when server is down."""
        hook_input = json.dumps({
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/tmp/test.py",
                "new_string": "print('hello world')",
            },
            "cwd": "/tmp",
        })
        elapsed, result = _timed_hook("post-tool-use", hook_input, str(tmp_path))
        assert result.returncode == 0
        assert elapsed < 5, f"post-tool-use took {elapsed:.2f}s (budget: 5s)"
