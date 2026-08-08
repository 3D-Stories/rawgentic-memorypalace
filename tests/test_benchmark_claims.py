"""Guard: the 96.6% figure never appears without its metric label (#75).

96.6% is R@5 — retrieval recall at five, no LLM in the loop. It reads as an
accuracy figure, and it becomes one in a reader's head the moment it sits beside
somebody else's accuracy number. The label is what stops that, so the label is
pinned by a test rather than by everyone remembering.

Scope note, stated rather than left implicit: this checks tracked markdown. It
does not check the rendered `.html` artifacts, because those are generated
snapshots of a doc at a moment — the source is the thing to keep honest.
"""
import re
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FIGURE = "96.6"
LABEL = re.compile(r"R@5", re.IGNORECASE)
# The label has to be near the figure, not merely somewhere in a long document.
NEARBY_LINES = 4


def tracked_markdown():
    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
    )
    return [PROJECT_ROOT / p for p in out.stdout.split("\n") if p.strip()]


def sites():
    """Every (path, line number) where the figure appears in tracked markdown."""
    found = []
    for path in tracked_markdown():
        lines = path.read_text(encoding="utf-8").split("\n")
        for i, line in enumerate(lines):
            if FIGURE in line:
                found.append((path, i, lines))
    return found


class TestFigureIsAlwaysLabelled:
    def test_the_figure_still_appears_somewhere(self):
        """If this fails the guard has nothing to guard, and silently passing
        would be worse than failing."""
        assert sites(), "no tracked markdown states 96.6% — has the guard gone stale?"

    def test_every_mention_carries_its_metric_label(self):
        unlabelled = []
        for path, i, lines in sites():
            window = "\n".join(lines[max(0, i - NEARBY_LINES): i + NEARBY_LINES + 1])
            if not LABEL.search(window):
                rel = path.relative_to(PROJECT_ROOT)
                unlabelled.append(f"{rel}:{i + 1}: {lines[i].strip()[:90]}")
        assert not unlabelled, (
            "96.6% stated without R@5 within "
            f"{NEARBY_LINES} lines:\n  " + "\n  ".join(unlabelled)
        )


class TestReadmeCarriesTheRule:
    @pytest.fixture
    def readme(self):
        # Whitespace-normalized: prose is hard-wrapped, and a guard that breaks
        # when a sentence rewraps would be retired within a month.
        raw = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        return re.sub(r"\s+", " ", raw)

    def test_the_rule_has_its_own_section(self, readme):
        assert "Benchmark numbers" in readme

    def test_the_rule_names_the_metric_and_denies_it_is_accuracy(self, readme):
        assert "R@5" in readme
        assert "not an accuracy figure" in readme

    def test_the_rule_says_we_have_no_head_to_head(self, readme):
        """The comparison doc declines to manufacture one; the README must not
        quietly imply otherwise."""
        assert "no head-to-head" in readme
