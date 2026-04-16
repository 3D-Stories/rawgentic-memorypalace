#!/usr/bin/env python3
"""Canary test — continuous memory pipeline health probe.

Standalone script (not pytest). Writes a timestamped canary fact via
POST /canary_write, then polls POST /search until the fact is recalled.

Usage:
    MEMORY_SERVER_URL=http://127.0.0.1:8421 python tests/canary.py

Exit codes: 0 = PASS, 1 = FAIL
"""
from __future__ import annotations

import fcntl
import os
import sys
import time

import requests

MEMORY_SERVER_URL = os.environ.get("MEMORY_SERVER_URL", "http://127.0.0.1:8420")
LOCK_FILE = "/tmp/memorypalace-canary.lock"
POLL_INTERVAL = 2  # seconds
MAX_POLL_SECS = 30


def main() -> int:
    # Single-instance safety: flock a lockfile
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("CANARY FAIL: another canary instance is running", file=sys.stderr)
        return 1

    try:
        return _run_canary()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _run_canary() -> int:
    canary_id = f"canary-{int(time.time())}"
    fact = f"The canary sang at {canary_id}"

    # Write the canary fact
    try:
        resp = requests.post(
            f"{MEMORY_SERVER_URL}/canary_write",
            json={"wing": "canary", "fact": fact},
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"CANARY FAIL: write returned {resp.status_code}: {resp.text}", file=sys.stderr)
            return 1
        data = resp.json()
        if not data.get("ok"):
            print(f"CANARY FAIL: write returned ok=false: {data}", file=sys.stderr)
            return 1
    except requests.RequestException as e:
        print(f"CANARY FAIL: write error: {e}", file=sys.stderr)
        return 1

    # Poll /search until the fact is recalled
    deadline = time.monotonic() + MAX_POLL_SECS
    while time.monotonic() < deadline:
        try:
            resp = requests.post(
                f"{MEMORY_SERVER_URL}/search",
                json={"prompt": canary_id, "min_similarity": 0.3},
                timeout=10,
            )
            if resp.status_code == 200:
                ctx = resp.json().get("additionalContext", "")
                if canary_id in ctx:
                    print("CANARY PASS")
                    return 0
        except requests.RequestException:
            pass
        time.sleep(POLL_INTERVAL)

    print(f"CANARY FAIL: fact not recalled within {MAX_POLL_SECS}s", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
