"""Integration: concurrent canary writes must not corrupt the palace.

Requires a subprocess server on port 8421.
"""
from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
import requests

SERVER_PORT = 8421
SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}"
VENV_PYTHON = ".venv/bin/python"


@pytest.fixture(scope="module")
def server():
    """Start a subprocess server on 8421, yield, then terminate with kill fallback."""
    proc = subprocess.Popen(
        [VENV_PYTHON, "-m", "rawgentic_memory.server", "--port", str(SERVER_PORT), "--timeout", "60"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for /healthz to respond (up to 15s)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{SERVER_URL}/healthz", timeout=2)
            if r.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(0.5)
    else:
        proc.kill()
        proc.wait(timeout=5)
        pytest.fail("Server failed to start within 15 seconds")

    yield proc

    # Teardown with kill fallback
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


class TestConcurrentCanaryWrites:
    def test_concurrent_canary_writes_are_safe(self, server):
        """20 concurrent POST /canary_write requests must all return < 500."""
        def write_canary(i: int) -> int:
            resp = requests.post(
                f"{SERVER_URL}/canary_write",
                json={"wing": "canary", "fact": f"concurrent-fact-{i}-{time.time()}"},
                timeout=10,
            )
            return resp.status_code

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = {pool.submit(write_canary, i): i for i in range(20)}
            results = {}
            for fut in as_completed(futures):
                idx = futures[fut]
                results[idx] = fut.result()

        # All must return < 500 (200 expected, but 4xx is acceptable for validation)
        for idx, status in sorted(results.items()):
            assert status < 500, f"Request {idx} returned server error {status}"

        # Additionally, all should be 200
        assert all(s == 200 for s in results.values()), (
            f"Expected all 200, got: {results}"
        )
