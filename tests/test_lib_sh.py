"""
Bash hook helper test suite — tests for lib.sh smart gate functions.

Tests should_search() and should_fact_check() by sourcing lib.sh and
running bash snippets via subprocess.run(). Each test uses a unique
STATE_DIR to avoid cross-test pollution of debounce files.
"""
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

# Resolve path to lib.sh relative to this test file
LIB_SH = str(Path(__file__).parent.parent / "hooks" / "lib.sh")


def run_bash(snippet: str, env_overrides: dict | None = None, state_dir: str | None = None) -> subprocess.CompletedProcess:
    """Source lib.sh and run a bash snippet. Returns CompletedProcess.

    Args:
        snippet: Bash code to run after sourcing lib.sh.
        env_overrides: Extra environment variables to pass.
        state_dir: Override STATE_DIR for debounce isolation.
    """
    env = {
        "HOME": str(Path.home()),
        "PATH": "/usr/bin:/bin",
        "MEMORY_NO_AUTOSTART": "1",
        "MEMORY_DEBUG": "0",
    }
    if state_dir:
        env["STATE_DIR"] = state_dir
    if env_overrides:
        env.update(env_overrides)

    script = textwrap.dedent(f"""
        source {LIB_SH}
        {snippet}
    """)

    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


class TestShouldSearch:
    """Tests for the should_search gate function in lib.sh."""

    def test_short_prompt_is_rejected(self, tmp_path):
        """Prompts shorter than RECALL_MIN_PROMPT_CHARS should be skipped."""
        result = run_bash(
            "should_search 'short' 'testproject' && echo ALLOWED || echo SKIPPED",
            state_dir=str(tmp_path),
        )
        assert result.returncode == 0  # bash script itself succeeds
        assert "SKIPPED" in result.stdout

    def test_long_prompt_is_accepted(self, tmp_path):
        """Prompts at or above the threshold should be allowed (first call, no debounce)."""
        result = run_bash(
            "should_search 'this is a longer prompt for testing purposes' 'testproject' && echo ALLOWED || echo SKIPPED",
            state_dir=str(tmp_path),
        )
        assert result.returncode == 0
        assert "ALLOWED" in result.stdout

    def test_slash_command_is_rejected(self, tmp_path):
        """Prompts starting with /cmd should always be skipped."""
        result = run_bash(
            "should_search '/commit foo bar baz qux quux' 'testproject' && echo ALLOWED || echo SKIPPED",
            state_dir=str(tmp_path),
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout

    def test_lgtm_stop_word_is_rejected(self, tmp_path):
        """Single-word ack 'LGTM' should be skipped (case-insensitive)."""
        result = run_bash(
            "should_search 'LGTM' 'testproject' && echo ALLOWED || echo SKIPPED",
            state_dir=str(tmp_path),
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout

    def test_looks_good_phrase_is_rejected(self, tmp_path):
        """Multi-word ack 'looks good' should be skipped."""
        result = run_bash(
            "should_search 'looks good' 'testproject' && echo ALLOWED || echo SKIPPED",
            state_dir=str(tmp_path),
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout

    def test_sounds_good_phrase_is_rejected(self, tmp_path):
        """Multi-word ack 'sounds good' should be skipped."""
        result = run_bash(
            "should_search 'sounds good' 'testproject' && echo ALLOWED || echo SKIPPED",
            state_dir=str(tmp_path),
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout

    def test_do_it_phrase_is_rejected(self, tmp_path):
        """Multi-word ack 'do it' should be skipped."""
        result = run_bash(
            "should_search 'do it' 'testproject' && echo ALLOWED || echo SKIPPED",
            state_dir=str(tmp_path),
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout

    def test_yes_ack_is_rejected(self, tmp_path):
        """Single-word ack 'yes' should be skipped."""
        result = run_bash(
            "should_search 'yes' 'testproject' && echo ALLOWED || echo SKIPPED",
            state_dir=str(tmp_path),
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout

    def test_debounce_blocks_second_call(self, tmp_path):
        """Second call within debounce window should be skipped."""
        script = textwrap.dedent("""
            # First call — sets debounce timestamp
            should_search 'this is a longer prompt for testing purposes one' 'testproject'
            # Second call immediately — debounce should block it
            should_search 'this is a longer prompt for testing purposes two' 'testproject' && echo ALLOWED || echo SKIPPED
        """)
        result = run_bash(
            script,
            state_dir=str(tmp_path),
            env_overrides={"RECALL_DEBOUNCE_SECS": "300"},
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout

    def test_debounce_zero_allows_repeated_calls(self, tmp_path):
        """With RECALL_DEBOUNCE_SECS=0, repeated calls should be allowed."""
        script = textwrap.dedent("""
            should_search 'this is a longer prompt for testing purposes one' 'testproject'
            should_search 'this is a longer prompt for testing purposes two' 'testproject' && echo ALLOWED || echo SKIPPED
        """)
        result = run_bash(
            script,
            state_dir=str(tmp_path),
            env_overrides={"RECALL_DEBOUNCE_SECS": "0"},
        )
        assert result.returncode == 0
        assert "ALLOWED" in result.stdout

    def test_ok_ack_case_insensitive(self, tmp_path):
        """Stop-word matching is case-insensitive — 'OK' should be rejected."""
        result = run_bash(
            "should_search 'OK' 'testproject' && echo ALLOWED || echo SKIPPED",
            state_dir=str(tmp_path),
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout


class TestShouldFactCheck:
    """Tests for the should_fact_check gate function in lib.sh."""

    def test_empty_path_is_rejected(self, tmp_path):
        """Empty file path should always be skipped."""
        result = run_bash(
            "should_fact_check '' 'testproject' && echo ALLOWED || echo SKIPPED",
            state_dir=str(tmp_path),
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout

    def test_valid_path_first_call_is_accepted(self, tmp_path):
        """A new file path on first call (no debounce state) should be allowed."""
        result = run_bash(
            "should_fact_check '/tmp/some/new/file.py' 'testproject' && echo ALLOWED || echo SKIPPED",
            state_dir=str(tmp_path),
        )
        assert result.returncode == 0
        assert "ALLOWED" in result.stdout

    def test_per_file_dedup_blocks_repeat(self, tmp_path):
        """Same file checked twice within debounce window should be blocked on second call."""
        script = textwrap.dedent("""
            # First call for this file
            should_fact_check '/tmp/dedup_test_file.py' 'testproject'
            # Second call immediately — per-file dedup should block
            should_fact_check '/tmp/dedup_test_file.py' 'testproject' && echo ALLOWED || echo SKIPPED
        """)
        result = run_bash(
            script,
            state_dir=str(tmp_path),
            env_overrides={"FACT_CHECK_DEBOUNCE_SECS": "300"},
        )
        assert result.returncode == 0
        assert "SKIPPED" in result.stdout

    def test_different_files_are_each_accepted(self, tmp_path):
        """Different file paths should each be accepted (per-file dedup is per-file)."""
        # Note: project-level debounce means second file might be blocked.
        # Use debounce=0 to isolate per-file behavior.
        script = textwrap.dedent("""
            should_fact_check '/tmp/file_alpha.py' 'testproject' && echo ALPHA_OK || echo ALPHA_SKIP
            should_fact_check '/tmp/file_beta.py' 'testproject' && echo BETA_OK || echo BETA_SKIP
        """)
        result = run_bash(
            script,
            state_dir=str(tmp_path),
            env_overrides={"FACT_CHECK_DEBOUNCE_SECS": "0"},
        )
        assert result.returncode == 0
        assert "ALPHA_OK" in result.stdout
        assert "BETA_OK" in result.stdout

    def test_new_file_accepted_after_dedup_window(self, tmp_path):
        """A previously checked file should be accepted after the dedup window expires."""
        # Pre-write old timestamps so both project and per-file debounces appear expired.
        old_ts = "1"
        (tmp_path / "memorypalace-factcheck-debounce-testproject").write_text(old_ts)

        # Compute what the md5-based marker file name would be for /tmp/expired_file.py
        # and write an old timestamp there too
        import hashlib
        file_hash = hashlib.md5(b"/tmp/expired_file.py").hexdigest()
        (tmp_path / f"memorypalace-factcheck-file-{file_hash}").write_text(old_ts)

        result = run_bash(
            "should_fact_check '/tmp/expired_file.py' 'testproject' && echo ALLOWED || echo SKIPPED",
            state_dir=str(tmp_path),
            env_overrides={"FACT_CHECK_DEBOUNCE_SECS": "1"},
        )
        assert result.returncode == 0
        assert "ALLOWED" in result.stdout
