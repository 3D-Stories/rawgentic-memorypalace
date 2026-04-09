"""Tests for lazy-start behavior in hooks/lib.sh."""

import os
import signal
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
HOOKS_DIR = PROJECT_ROOT / "hooks"
LIB_SH = HOOKS_DIR / "lib.sh"

# Each test class uses a unique port to avoid cross-test pollution
_PORT_NO_AUTOSTART = 19876
_PORT_FAILURE = 19877
_PORT_ATTEMPT = 19878


def _run_bash(script: str, env: dict | None = None, timeout: int = 15,
              port: int = _PORT_NO_AUTOSTART) -> subprocess.CompletedProcess:
    """Run a bash script snippet with lib.sh sourced."""
    full_env = os.environ.copy()
    full_env["MEMORY_SERVER_URL"] = f"http://127.0.0.1:{port}"
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


def _kill_server_on_port(port: int) -> None:
    """Kill any server process listening on the given port."""
    try:
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            capture_output=True, text=True, timeout=5,
        )
        if result.stdout.strip():
            for pid_str in result.stdout.strip().split():
                try:
                    os.kill(int(pid_str), signal.SIGTERM)
                except (ProcessLookupError, ValueError):
                    pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


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
        """With MEMORY_NO_AUTOSTART=1, call_memory_server should fail fast."""
        result = _run_bash(
            'call_memory_server "/healthz"; echo "EXIT:$?"',
            env={"MEMORY_NO_AUTOSTART": "1"},
            port=_PORT_NO_AUTOSTART,
            timeout=5,
        )
        # Should fail (exit 1) since server isn't running and no autostart
        assert "EXIT:1" in result.stdout
        # Should log the skip reason
        assert "MEMORY_NO_AUTOSTART" in result.stderr


class TestLazyStartServerDown:
    """Validate lazy-start behavior when server is unreachable."""

    def test_call_memory_server_returns_failure_when_server_unreachable_no_autostart(self):
        """Without a running server and with NO_AUTOSTART, should fail gracefully."""
        result = _run_bash(
            'call_memory_server "/healthz" "GET"; echo "EXIT:$?"',
            env={"MEMORY_NO_AUTOSTART": "1"},
            port=_PORT_FAILURE,
            timeout=5,
        )
        assert "EXIT:1" in result.stdout

    def test_ensure_server_running_attempts_start_when_allowed(self):
        """Without NO_AUTOSTART, ensure_server_running should attempt to start
        the server and log the attempt."""
        try:
            result = _run_bash(
                'ensure_server_running; echo "EXIT:$?"',
                env={"MEMORY_NO_AUTOSTART": "0"},
                port=_PORT_ATTEMPT,
                timeout=15,
            )
            # Should log the start attempt
            assert "Starting memory server" in result.stderr
        finally:
            # Clean up any server that was actually started
            _kill_server_on_port(_PORT_ATTEMPT)
