"""Integration: concurrent canary writes must not corrupt the palace.

Requires a subprocess server on port 8421.
"""
from __future__ import annotations

import os
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
def server(tmp_path_factory):
    """Start a subprocess server on 8421 against an ISOLATED palace, yield, then
    terminate with kill fallback.

    The subprocess MUST NOT touch the real ~/.mempalace palace: it inherits this
    process's env, so pass an isolated MEMPALACE_PALACE_PATH. Otherwise the test
    both pollutes real memory with canary drawers and depends on the real palace's
    size — a large real palace makes each canary write slow enough to time out.
    """
    palace_dir = tmp_path_factory.mktemp("canary_palace")
    env = {**os.environ, "MEMPALACE_PALACE_PATH": str(palace_dir)}
    proc = subprocess.Popen(
        [VENV_PYTHON, "-m", "rawgentic_memory.server", "--port", str(SERVER_PORT), "--timeout", "120"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
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
        """Concurrent canary writes must all succeed safely — no server error and
        no lost/failed write.

        Canary writes serialize through the palace single-writer lock at ~1-2s
        each (embed + HNSW insert). We bound concurrency and give each request
        headroom well above the serialized completion time; asserting a tight
        per-request deadline would test write throughput, not the safety property
        this test exists for. A 200 alone is not enough — /canary_write returns
        200 with ``{"ok": false}`` when the underlying write fails, so we assert
        ``ok is True`` to prove every write actually persisted.
        """
        CONCURRENCY = 10

        def write_canary(i: int) -> tuple[int, object]:
            resp = requests.post(
                f"{SERVER_URL}/canary_write",
                json={"wing": "canary", "fact": f"concurrent-fact-{i}-{time.time()}"},
                timeout=60,
            )
            return resp.status_code, resp.json().get("ok")

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = {pool.submit(write_canary, i): i for i in range(CONCURRENCY)}
            results = {}
            for fut in as_completed(futures):
                idx = futures[fut]
                results[idx] = fut.result()

        for idx, (status, ok) in sorted(results.items()):
            assert status == 200, f"Request {idx} returned {status}, expected 200"
            assert ok is True, f"Request {idx} did not persist (ok={ok!r})"
