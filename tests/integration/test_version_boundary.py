"""Integration: adapter version boundary checks.

Uses unittest.mock.patch to simulate different mempalace versions against
the adapter's verify_behavioral_contract() method.

Version boundaries (from MempalaceAdapter):
  MIN_VERSION = "3.3.0"  -> versions below produce severity="error"
  MAX_VERSION = "4.0.0"  -> versions >= produce severity="warning"

Critical: version comparisons must use tuple-of-ints, not string comparison.
"3.10.0" < "3.3.0" is True lexically but False numerically.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from rawgentic_memory.adapter import MempalaceAdapter


@pytest.fixture
def adapter(isolated_palace):
    return MempalaceAdapter(palace_path=str(isolated_palace))


class TestVersionBoundary:
    def test_version_3_2_0_produces_error(self, adapter):
        """mempalace 3.2.0 is below MIN_VERSION (3.3.0) -> severity=error."""
        with patch("mempalace.version.__version__", "3.2.0"):
            violations = adapter.verify_behavioral_contract()
        version_violations = [v for v in violations if v.field == "mempalace_version"]
        assert len(version_violations) == 1
        assert version_violations[0].severity == "error"
        assert "3.2.0" in version_violations[0].actual

    def test_version_3_3_0_passes(self, adapter):
        """mempalace 3.3.0 is exactly MIN_VERSION -> no version violations."""
        with patch("mempalace.version.__version__", "3.3.0"):
            violations = adapter.verify_behavioral_contract()
        version_violations = [v for v in violations if v.field == "mempalace_version"]
        assert len(version_violations) == 0

    def test_version_4_0_0_produces_warning(self, adapter):
        """mempalace 4.0.0 is >= MAX_VERSION -> severity=warning (not error)."""
        with patch("mempalace.version.__version__", "4.0.0"):
            violations = adapter.verify_behavioral_contract()
        version_violations = [v for v in violations if v.field == "mempalace_version"]
        assert len(version_violations) == 1
        assert version_violations[0].severity == "warning"
        assert "4.0.0" in version_violations[0].actual

    def test_version_3_10_0_no_string_compare_bug(self, adapter):
        """mempalace 3.10.0 must NOT produce a version error.

        String comparison: "3.10.0" < "3.3.0" == True (wrong!)
        Tuple comparison: (3, 10, 0) < (3, 3, 0) == False (correct)
        This test guards against the string-comparison regression.
        """
        with patch("mempalace.version.__version__", "3.10.0"):
            violations = adapter.verify_behavioral_contract()
        version_violations = [v for v in violations if v.field == "mempalace_version"]
        # 3.10.0 is >= 3.3.0 and < 4.0.0 -> no version violations
        assert len(version_violations) == 0, (
            f"3.10.0 should pass version bounds but got: {version_violations}"
        )
