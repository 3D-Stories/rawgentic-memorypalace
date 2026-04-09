"""Tests for hook scripts — existence, executability, and graceful degradation."""

import json
import os
import stat
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
HOOKS_DIR = PROJECT_ROOT / "hooks"


class TestLibSh:
    """Validate hooks/lib.sh shared library."""

    def test_lib_sh_exists(self):
        assert (HOOKS_DIR / "lib.sh").exists(), "Missing hooks/lib.sh"

    def test_lib_sh_defines_server_url_default(self):
        content = (HOOKS_DIR / "lib.sh").read_text()
        assert "MEMORY_SERVER_URL" in content, "lib.sh must define MEMORY_SERVER_URL"

    def test_lib_sh_defines_call_memory_server(self):
        content = (HOOKS_DIR / "lib.sh").read_text()
        assert "call_memory_server" in content, "lib.sh must define call_memory_server()"

    def test_lib_sh_defines_debug_logging(self):
        content = (HOOKS_DIR / "lib.sh").read_text()
        assert "MEMORY_DEBUG" in content, "lib.sh must support MEMORY_DEBUG env var"


class TestHookScripts:
    """Validate hook scripts are executable and degrade gracefully."""

    HOOK_NAMES = ["session-start", "user-prompt-submit", "stop"]

    def test_hook_scripts_exist(self):
        for name in self.HOOK_NAMES:
            path = HOOKS_DIR / name
            assert path.exists(), f"Missing hooks/{name}"

    def test_hook_scripts_are_executable(self):
        for name in self.HOOK_NAMES:
            path = HOOKS_DIR / name
            mode = path.stat().st_mode
            assert mode & stat.S_IXUSR, f"hooks/{name} must be executable"

    def test_hook_scripts_have_shebang(self):
        for name in self.HOOK_NAMES:
            content = (HOOKS_DIR / name).read_text()
            assert content.startswith("#!/bin/bash"), (
                f"hooks/{name} must start with #!/bin/bash"
            )

    def test_hook_scripts_source_lib(self):
        for name in self.HOOK_NAMES:
            content = (HOOKS_DIR / name).read_text()
            assert "lib.sh" in content, (
                f"hooks/{name} must source lib.sh"
            )

    def test_hooks_exit_zero_when_server_unreachable(self):
        """All hooks must exit 0 when memory server is not running."""
        env = os.environ.copy()
        # Point to a port that definitely has no server
        env["MEMORY_SERVER_URL"] = "http://127.0.0.1:19999"
        # Disable lazy-start to avoid 10s polling delay per hook
        env["MEMORY_NO_AUTOSTART"] = "1"
        # Provide minimal JSON stdin that hooks expect
        stdin_data = json.dumps({
            "cwd": str(PROJECT_ROOT),
            "session_id": "test-session",
        })
        for name in self.HOOK_NAMES:
            path = HOOKS_DIR / name
            result = subprocess.run(
                [str(path)],
                input=stdin_data,
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
            assert result.returncode == 0, (
                f"hooks/{name} must exit 0 when server is unreachable, "
                f"got {result.returncode}. stderr: {result.stderr}"
            )


class TestUserPromptSubmitTimer:
    """Validate user-prompt-submit has timer state management."""

    def test_user_prompt_submit_references_timer_state(self):
        content = (HOOKS_DIR / "user-prompt-submit").read_text()
        assert "last-ingest" in content or "LAST_INGEST" in content, (
            "user-prompt-submit must manage timer state for 2h ingest trigger"
        )
