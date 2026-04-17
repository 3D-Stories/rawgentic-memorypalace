"""Tests for portable hook infrastructure (Issue #41, Group 1).

AC1: wrapper lives in hooks/mempalace-hook-wrapper.sh
AC4: WORKSPACE_ROOT consolidated to MEMPALACE_CLAUDE_WORKSPACE
AC5: no hardcoded user paths in shipped files
AC6: wrapper recursion guard works
"""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
SHIPPED_DIRS = ["hooks", "rawgentic_memory", "skills"]
EXCLUDED_DIRS = {"docs", "tests", ".venv", "claude_docs", "__pycache__"}


def _shipped_files():
    """Yield all shipped source files (bash + python) in SHIPPED_DIRS."""
    for dir_name in SHIPPED_DIRS:
        dir_path = PROJECT_ROOT / dir_name
        if not dir_path.exists():
            continue
        for root, dirs, files in os.walk(dir_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            for f in files:
                path = Path(root) / f
                if path.suffix in (".py", ".sh", "") and not path.name.startswith("."):
                    yield path


class TestWrapperInPlugin:
    """AC1: wrapper script exists inside the plugin."""

    def test_wrapper_exists(self):
        wrapper = PROJECT_ROOT / "hooks" / "mempalace-hook-wrapper.sh"
        assert wrapper.exists(), "hooks/mempalace-hook-wrapper.sh must exist in plugin"

    def test_wrapper_is_executable(self):
        wrapper = PROJECT_ROOT / "hooks" / "mempalace-hook-wrapper.sh"
        assert os.access(wrapper, os.X_OK), "wrapper must be executable"

    def test_wrapper_has_no_set_e_comment(self):
        wrapper = PROJECT_ROOT / "hooks" / "mempalace-hook-wrapper.sh"
        content = wrapper.read_text()
        assert "# NO set -e" in content or "NO set -e" in content


class TestNoHardcodedPaths:
    """AC5: no /home/<user>/... or $HOME/rawgentic in shipped files."""

    HARDCODED_HOME_RE = re.compile(r"/home/[a-zA-Z0-9_.-]+/")
    HARDCODED_WORKSPACE = "$HOME/rawgentic"

    def test_no_literal_home_paths(self):
        violations = []
        for path in _shipped_files():
            content = path.read_text(errors="replace")
            for i, line in enumerate(content.splitlines(), 1):
                if self.HARDCODED_HOME_RE.search(line):
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}:{i}: {line.strip()}")
        assert not violations, (
            "Shipped files must not contain /home/<user>/ literals:\n"
            + "\n".join(violations)
        )

    def test_no_hardcoded_workspace_constant(self):
        violations = []
        for path in _shipped_files():
            content = path.read_text(errors="replace")
            for i, line in enumerate(content.splitlines(), 1):
                if self.HARDCODED_WORKSPACE in line:
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}:{i}: {line.strip()}")
        assert not violations, (
            "Shipped files must not contain $HOME/rawgentic:\n"
            + "\n".join(violations)
        )


class TestWorkspaceVarConsolidated:
    """AC4: only MEMPALACE_CLAUDE_WORKSPACE, not WORKSPACE_ROOT as config."""

    def test_no_workspace_root_config(self):
        """WORKSPACE_ROOT should not appear as a configurable variable in shipped files.

        Local variables or comments referencing workspace_root are fine;
        the pattern we reject is WORKSPACE_ROOT being used as an env-var default.
        """
        violations = []
        # Match: WORKSPACE_ROOT="${WORKSPACE_ROOT:- or WORKSPACE_ROOT= at line start
        config_re = re.compile(r'^\s*WORKSPACE_ROOT\s*=\s*"\$\{WORKSPACE_ROOT')
        for path in _shipped_files():
            content = path.read_text(errors="replace")
            for i, line in enumerate(content.splitlines(), 1):
                if config_re.search(line):
                    violations.append(f"{path.relative_to(PROJECT_ROOT)}:{i}: {line.strip()}")
        assert not violations, (
            "WORKSPACE_ROOT config lines found — use MEMPALACE_CLAUDE_WORKSPACE:\n"
            + "\n".join(violations)
        )


class TestWrapperRecursionGuard:
    """AC6: recursion guard exits 0 with {} on stop_hook_active=true."""

    WRAPPER = PROJECT_ROOT / "hooks" / "mempalace-hook-wrapper.sh"

    @pytest.fixture(autouse=True)
    def _skip_if_missing(self):
        if not self.WRAPPER.exists():
            pytest.skip("wrapper not yet created")

    def test_stop_hook_active_returns_empty_json(self):
        hook_input = json.dumps({
            "session_id": "test-session-123",
            "stop_hook_active": "true",
        })
        result = subprocess.run(
            [str(self.WRAPPER), "stop"],
            input=hook_input,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "{}"

    def test_mempalace_save_in_progress_returns_empty_json(self):
        hook_input = json.dumps({
            "session_id": "test-session-456",
        })
        env = os.environ.copy()
        env["MEMPALACE_SAVE_IN_PROGRESS"] = "1"
        result = subprocess.run(
            [str(self.WRAPPER), "stop"],
            input=hook_input,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "{}"

    def test_precompact_recursion_guard(self):
        hook_input = json.dumps({
            "session_id": "test-session-789",
            "stop_hook_active": "true",
        })
        result = subprocess.run(
            [str(self.WRAPPER), "precompact"],
            input=hook_input,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "{}"


class TestWrapperWorkspaceDetection:
    """AC3: wrapper auto-detects workspace from .cwd in hook input."""

    WRAPPER = PROJECT_ROOT / "hooks" / "mempalace-hook-wrapper.sh"

    @pytest.fixture(autouse=True)
    def _skip_if_missing(self):
        if not self.WRAPPER.exists():
            pytest.skip("wrapper not yet created")

    def test_wrapper_does_not_default_to_home_rawgentic(self):
        content = self.WRAPPER.read_text()
        assert "$HOME/rawgentic" not in content, (
            "wrapper must not default to $HOME/rawgentic"
        )
