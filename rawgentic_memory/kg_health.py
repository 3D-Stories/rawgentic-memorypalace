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

    0  checked, nothing that is unambiguously wrong
    1  drift on a declared single-valued predicate, or the same fact open twice
    2  could not check — database absent, unreadable, or locked

Exit 2 is deliberately distinct from 0: an absent database must never read as a
clean bill of health. Exit 1 covers duplicate open rows as well as drift,
because the same fact stored twice is never intended by any caller — upstream's
``add_triple`` dedupes exactly that, so a duplicate means something bypassed it.

**Read-only, stated precisely.** This module never mutates the knowledge-graph
tables or the main database file: the connection is opened ``mode=ro``. SQLite
may still touch the ``-shm`` / ``-wal`` sidecar files when reading a database in
WAL mode. That is reader coordination state, not palace content, and claiming
"never writes anything" would be false.
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
#
# When membership is debatable, leave the predicate OUT. A wrong entry fails the
# check on valid data, which teaches everyone to ignore the check; a missing
# entry only means the case is reported instead of enforced. `publishes_via`,
# `provenance_is` and `uses_model` were dropped for exactly that reason — a
# subject can publish through several channels and use several models, even
# though the live graph happens to have superseded `publishes_via` as if it were
# singular.
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
    "python_package_manager",
    "repo_status",
    "review_seat_model",
    "reviewer_seat_model",
    "shipped_version",
    "status",
    "test_gate_command_is",
    "topology_is",
    "uses_output_style",
    "version",
    "voice_owned_by",
})


def connect_readonly(db_path: str) -> sqlite3.Connection:
    """Open the knowledge graph read-only. Never creates a missing database.

    The path is percent-encoded from its filesystem BYTES before it becomes a
    URI. Two reasons, both load-bearing:

    - Without encoding, a path containing ``?`` is parsed as URI parameters, so a
      caller passing ``foo.sqlite3?mode=rwc`` would silently get a writable
      connection to the very palace this module promises not to mutate.
    - Encoding the str directly raises ``UnicodeError`` on a path carrying
      undecodable filesystem bytes. That escapes as an uncaught exception whose
      process status collides with exit 1, which means "drift found" — a failure
      would be read as a finding. ``os.fsencode`` round-trips those bytes.
    """
    quoted = urllib.parse.quote_from_bytes(os.fsencode(db_path), safe="/")
    conn = sqlite3.connect(
        f"file:{quoted}?mode=ro", uri=True, timeout=CONNECT_TIMEOUT_SECONDS
    )
    conn.row_factory = sqlite3.Row
    return conn


def find_multi_valued(conn: sqlite3.Connection) -> list[dict]:
    """Every (subject, predicate) holding more than one CURRENT distinct object.

    SQL finds the offending groups, then a second query fetches the objects for
    those groups only. Neither the whole graph nor a whole group is held in
    memory to decide the question, and ``GROUP_CONCAT`` is avoided because object
    values here contain commas and ``GROUP_CONCAT(DISTINCT ...)`` cannot take a
    separator.
    """
    groups = conn.execute(
        "SELECT subject, predicate FROM triples WHERE valid_to IS NULL "
        "GROUP BY subject, predicate HAVING COUNT(DISTINCT object) > 1 "
        "ORDER BY subject, predicate"
    ).fetchall()

    found = []
    for group in groups:
        objects = [
            row["object"]
            for row in conn.execute(
                "SELECT DISTINCT object FROM triples "
                "WHERE valid_to IS NULL AND subject = ? AND predicate = ? "
                "ORDER BY object",
                (group["subject"], group["predicate"]),
            )
        ]
        found.append({
            "subject": group["subject"],
            "predicate": group["predicate"],
            "objects": objects,
            "declared_single_valued": group["predicate"] in SINGLE_VALUED_PREDICATES,
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
    """Run every check against one database. Raises ``sqlite3.Error`` if unreadable.

    All queries run inside ONE read transaction. The live graph is written by a
    long-running server while this reads it, so without an explicit ``BEGIN`` the
    totals, the drift list and the duplicate list could each come from a
    different snapshot and contradict one another.
    """
    conn = connect_readonly(db_path)
    try:
        conn.execute("BEGIN")
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
            conn.rollback()
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
            lines.append(f"  {item['subject']} | {item['predicate']}")
            # One value per line: object values in this graph contain commas, so
            # joining them would read as more values than there are.
            for obj in item["objects"]:
                lines.append(f"      {obj}")
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
    except (sqlite3.Error, ValueError, UnicodeError) as exc:
        # ValueError/UnicodeError cover a path whose bytes cannot be encoded into
        # a URI. Letting one escape would exit with a status that collides with
        # exit 1 — a failure read as a finding.
        reason = f"could not check {db_path}: {exc}"
        if args.json:
            print(json.dumps({"db_path": db_path, "error": reason}, indent=2))
        else:
            print(reason)
        return 2

    print(json.dumps(report, indent=2) if args.json else _render(report))
    return 1 if (report["drift"] or report["duplicate_rows"]) else 0


if __name__ == "__main__":
    sys.exit(main())
