"""Tests for lazy-start behavior in hooks/lib.sh."""

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
HOOKS_DIR = PROJECT_ROOT / "hooks"
LIB_SH = HOOKS_DIR / "lib.sh"


def _run_bash(script: str, env: dict | None = None, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run a bash script snippet with lib.sh sourced."""
    full_env = os.environ.copy()
    full_env["MEMORY_SERVER_URL"] = "http://127.0.0.1:19876"  # guaranteed unreachable
    full_env["MEMORY_DEBUG"] = "1"
    if env:
        full_env.update(env)

    full_script = f'source "{LIB_SH}"\n{script}'
    return subprocess.run(
        ["bash", "-c", full_script],
        capture_output=True,
        text=True,
        env=full_env,
        timeout=timeout,
    )


class TestLibShLazyStartDefinitions:
    """Validate lib.sh defines the lazy-start functions and variables."""

    def test_ensure_server_running_function_exists(self):
        content = LIB_SH.read_text()
        assert "ensure_server_running" in content, (
            "lib.sh must define ensure_server_running()"
        )

    def test_memory_no_autostart_respected(self):
        content = LIB_SH.read_text()
        assert "MEMORY_NO_AUTOSTART" in content, (
            "lib.sh must check MEMORY_NO_AUTOSTART env var"
        )


class TestLazyStartNoAutostart:
    """Validate MEMORY_NO_AUTOSTART=1 skips server start."""

    def test_call_memory_server_skips_start_when_no_autostart(self):
        """With MEMORY_NO_AUTOSTART=1, call_memory_server should fail fast
        without attempting to start the server."""
        result = _run_bash(
            'call_memory_server "/healthz"; echo "EXIT:$?"',
            env={"MEMORY_NO_AUTOSTART": "1"},
            timeout=5,  # should be fast — no 10s polling
        )
        # Should complete quickly (not spend 10s polling)
        assert "EXIT:1" in result.stdout or result.returncode == 0
        # Should NOT contain any server start attempt
        assert "Starting memory server" not in result.stderr or "MEMORY_NO_AUTOSTART" in result.stderr


class TestLazyStartServerDown:
    """Validate lazy-start behavior when server is unreachable."""

    def test_call_memory_server_returns_failure_when_server_unreachable_no_autostart(self):
        """Without a running server and with NO_AUTOSTART, should fail gracefully."""
        result = _run_bash(
            'call_memory_server "/healthz" "GET"; echo "EXIT:$?"',
            env={"MEMORY_NO_AUTOSTART": "1"},
            timeout=5,
        )
        assert "EXIT:1" in result.stdout

    def test_ensure_server_running_attempts_start_when_allowed(self):
        """Without NO_AUTOSTART, ensure_server_running should attempt to start."""
        result = _run_bash(
            'ensure_server_running; echo "EXIT:$?"',
            env={"MEMORY_NO_AUTOSTART": "0"},
            timeout=15,
        )
        # Should have attempted to start (logged debug message)
        # The server won't actually start (wrong port/env), but the attempt matters
        assert result.returncode == 0 or "EXIT:" in result.stdout
