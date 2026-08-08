"""Knowledge-graph drift detector — read-only health check over the KG store.

Issue #72. A single-valued fact (the model in use, an employer, an address) must
hold at most ONE current value. The rule lives in CLAUDE.md as a protocol the
model follows; nothing in the store refuses a violation, because the store is the
upstream third-party ``mempalace`` package and its ``add_triple`` only dedupes an
exact ``(subject, predicate, object)`` that is still open. Two DIFFERENT objects
for one ``(subject, predicate)`` both stay current, and an as-of query then
returns two values for a fact that can only have one.

This module does not prevent that — it *detects* it, repeatably, so the claim
"there is no drift" stays checkable instead of being asserted once and trusted
forever. The refusing constraint belongs in the upstream store; see the issue.

Usage::

    python -m rawgentic_memory.kg_health [--db PATH] [--json]

Exit codes:

    0  checked, no drift on a declared single-valued predicate
    1  drift found on a declared single-valued predicate
    2  could not check — database absent, unreadable, or locked

Exit 2 is deliberately distinct from 0: an absent database must never read as a
clean bill of health.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.parse

DEFAULT_DB_PATH = os.path.expanduser("~/.mempalace/knowledge_graph.sqlite3")

CONNECT_TIMEOUT_SECONDS = 10

# Predicates where a subject can hold at most ONE true value at a time (#72 AC4).
#
# Declared as data rather than inferred at call time, so the set can be read,
# argued with, and extended in one place. The membership rule is exactly the
# sentence above: if a subject can truthfully hold two of these at once, the
# predicate does not belong here. `requires` and `blocked_by` are deliberately
# absent — a thing legitimately requires many things.
#
# Drift on a predicate that is NOT in this set is still reported, but it never
# fails the check: which free-text predicates are single-valued is a judgment
# call, and this tool reports shape rather than enforcing judgment.
SINGLE_VALUED_PREDICATES = frozenset({
    "at_version",
    "authoritative_store_is",
    "baseline_effort_is",
    "canonical_home_is",
    "default_architecture",
    "default_model",
    "enablement_state",
    "gate_status",
    "has_version",
    "plugin_version",
    "provenance_is",
    "publishes_via",
    "python_package_manager",
    "repo_status",
    "review_seat_model",
    "reviewer_seat_model",
    "shipped_version",
    "status",
    "test_gate_command_is",
    "topology_is",
    "uses_model",
    "uses_output_style",
    "version",
    "voice_owned_by",
})


def connect_readonly(db_path: str) -> sqlite3.Connection:
    """Open the knowledge graph read-only. Never creates a missing database.

    The path is percent-encoded before it becomes a URI. Without that, a path
    containing ``?`` would be parsed as URI parameters, so a caller passing
    ``foo.sqlite3?mode=rwc`` would silently get a writable connection to the very
    palace this module promises never to touch.
    """
    quoted = urllib.parse.quote(db_path, safe="/")
    conn = sqlite3.connect(
        f"file:{quoted}?mode=ro", uri=True, timeout=CONNECT_TIMEOUT_SECONDS
    )
    conn.row_factory = sqlite3.Row
    return conn


def find_multi_valued(conn: sqlite3.Connection) -> list[dict]:
    """Every (subject, predicate) holding more than one CURRENT distinct object.

    Grouping happens in Python rather than via ``GROUP_CONCAT``: object values in
    this graph contain commas, and ``GROUP_CONCAT(DISTINCT ...)`` cannot take a
    separator, so a SQL-side concatenation would split them wrongly.
    """
    groups: dict[tuple[str, str], list[str]] = {}
    for row in conn.execute(
        "SELECT subject, predicate, object FROM triples WHERE valid_to IS NULL"
    ):
        key = (row["subject"], row["predicate"])
        objects = groups.setdefault(key, [])
        if row["object"] not in objects:
            objects.append(row["object"])

    found = []
    for (subject, predicate), objects in sorted(groups.items()):
        if len(objects) > 1:
            found.append({
                "subject": subject,
                "predicate": predicate,
                "objects": sorted(objects),
                "declared_single_valued": predicate in SINGLE_VALUED_PREDICATES,
            })
    return found


def find_duplicate_rows(conn: sqlite3.Connection) -> list[dict]:
    """The same (subject, predicate, object) open more than once."""
    return [
        {
            "subject": row["subject"],
            "predicate": row["predicate"],
            "object": row["object"],
            "rows": row["n"],
        }
        for row in conn.execute(
            "SELECT subject, predicate, object, COUNT(*) AS n FROM triples "
            "WHERE valid_to IS NULL "
            "GROUP BY subject, predicate, object HAVING COUNT(*) > 1 "
            "ORDER BY n DESC, subject, predicate"
        )
    ]


def _totals(conn: sqlite3.Connection) -> dict:
    def scalar(sql: str) -> int:
        return conn.execute(sql).fetchone()[0]

    return {
        "entities": scalar("SELECT COUNT(*) FROM entities"),
        "triples": scalar("SELECT COUNT(*) FROM triples"),
        "current": scalar("SELECT COUNT(*) FROM triples WHERE valid_to IS NULL"),
        "expired": scalar("SELECT COUNT(*) FROM triples WHERE valid_to IS NOT NULL"),
        "predicates": scalar("SELECT COUNT(DISTINCT predicate) FROM triples"),
    }


def check(db_path: str) -> dict:
    """Run every check against one database. Raises ``sqlite3.Error`` if unreadable."""
    conn = connect_readonly(db_path)
    try:
        multi_valued = find_multi_valued(conn)
        return {
            "db_path": db_path,
            "totals": _totals(conn),
            "multi_valued": multi_valued,
            "drift": [m for m in multi_valued if m["declared_single_valued"]],
            "duplicate_rows": find_duplicate_rows(conn),
        }
    finally:
        conn.close()


def _render(report: dict) -> str:
    totals = report["totals"]
    lines = [
        f"knowledge graph: {report['db_path']}",
        f"  entities {totals['entities']}  triples {totals['triples']}  "
        f"current {totals['current']}  expired {totals['expired']}  "
        f"predicates {totals['predicates']}",
        "",
    ]

    if report["drift"]:
        lines.append(f"DRIFT — declared single-valued, more than one current value "
                     f"({len(report['drift'])}):")
        for item in report["drift"]:
            lines.append(f"  {item['subject']} | {item['predicate']} | "
                         f"{', '.join(item['objects'])}")
    else:
        lines.append("no drift on a declared single-valued predicate")

    undeclared = [m for m in report["multi_valued"] if not m["declared_single_valued"]]
    if undeclared:
        lines.append("")
        lines.append(f"multi-valued, predicate not declared single-valued "
                     f"({len(undeclared)}) — reported, not enforced:")
        for item in undeclared:
            lines.append(f"  {item['subject']} | {item['predicate']} | "
                         f"{len(item['objects'])} values")

    if report["duplicate_rows"]:
        lines.append("")
        lines.append(f"duplicate open rows ({len(report['duplicate_rows'])}):")
        for item in report["duplicate_rows"]:
            lines.append(f"  {item['subject']} | {item['predicate']} | "
                         f"{item['object']} | {item['rows']} rows")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rawgentic_memory.kg_health",
        description="Read-only drift check over the mempalace knowledge graph.",
    )
    parser.add_argument(
        "--db", default=None,
        help=f"knowledge-graph database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit the report as JSON",
    )
    args = parser.parse_args(argv)
    db_path = args.db or DEFAULT_DB_PATH

    try:
        report = check(db_path)
    except sqlite3.Error as exc:
        reason = f"could not check {db_path}: {exc}"
        if args.json:
            print(json.dumps({"db_path": db_path, "error": reason}, indent=2))
        else:
            print(reason)
        return 2

    print(json.dumps(report, indent=2) if args.json else _render(report))
    return 1 if report["drift"] else 0


if __name__ == "__main__":
    sys.exit(main())
