"""Palace linter — a health check over the shape of the memory palace.

Issue #73. Every finding in epic #71 was discovered by accident, while measuring
our own system to compare it against a competitor. That is the wrong way to learn
that 84.8% of your memory is one room. This is the instrument that would have
found it on purpose.

It **reports shape and enforces almost nothing.** Skew is a judgment call: a room
holding most of the palace may be a defect or may be correct, and a linter that
fails the build over it would simply be switched off. Only two conditions are
hard enough to fail:

- **wing-name fragmentation** — the same project filed under two spellings, so a
  scoped search against one silently misses everything under the other;
- **a SQLite integrity error**, as reported by upstream.

Usage::

    python -m rawgentic_memory.palace_lint [--json] [--max-items N]

Exit codes:

    0  checked; no hard problem
    1  a hard problem: wing-name fragmentation, or a SQLite integrity error
    2  could not check — the palace could not be read

The palace and integrity numbers come from upstream's own
``mempalace.mcp_server.tool_status()`` — the same call ``mempalace_status`` makes —
so the integrity check is consumed rather than reimplemented. Knowledge-graph
coverage reuses ``rawgentic_memory.kg_health`` rather than opening the graph a
second way.

Every check below is a pure function over a status dict. Only ``load_status`` and
``load_kg`` touch anything live, which is what makes the checks testable without
a palace.
"""
from __future__ import annotations

import argparse
import json
import sys

NEAR_EMPTY_THRESHOLD = 3
DEFAULT_MAX_ITEMS = 20

# Wing names are spelled three ways in the live palace at once: bare
# (`rawgentic`), `wing_`-prefixed (`wing_rawgentic`), and hyphen-versus-underscore
# variants of the same name (`herdr-dashboard` / `herdr_dashboard`).
_WING_PREFIX = "wing_"


class PalaceUnreadable(Exception):
    """The palace could not be read, or its status came back in an unusable shape."""


def normalize_wing(name: str) -> str:
    """Reduce a wing name to the identity its three spellings share.

    Deliberately NOT a similarity score. Two wings collide only when these
    normalized forms are EXACTLY equal, which is what keeps `rawgentic` and
    `rawgentic-next` apart — a checker that cannot tell those apart is worse than
    no checker at all (#73 AC3).

    Case folding happens FIRST, before the prefix is stripped. The other order
    leaves `Wing_rawgentic` normalizing to `wing_rawgentic`, so it never meets
    `rawgentic` and the fragmentation is missed.

    The assumption this rule makes, stated out loud: two wings whose names differ
    only by `wing_`, by a hyphen versus an underscore, or by case are the same
    project. If they ever were two genuinely different projects, the collision is
    still worth failing on — a scoped search could not tell them apart either,
    and neither could a person reading the list.
    """
    folded = name.casefold()
    stripped = folded[len(_WING_PREFIX):] if folded.startswith(_WING_PREFIX) else folded
    return stripped.replace("-", "_")


def find_fragmented_wings(wings: dict) -> list[dict]:
    """Groups where one project is filed under more than one spelling."""
    groups: dict[str, list[tuple[str, int]]] = {}
    for wing, drawers in wings.items():
        groups.setdefault(normalize_wing(wing), []).append((wing, drawers))

    found = []
    for normalized, spellings in sorted(groups.items()):
        if len(spellings) > 1:
            ordered = sorted(spellings, key=lambda pair: (-pair[1], pair[0]))
            found.append({
                "normalized": normalized,
                "spellings": [{"wing": w, "drawers": n} for w, n in ordered],
                "drawers": sum(n for _, n in ordered),
            })
    return sorted(found, key=lambda g: -g["drawers"])


def _largest(counts: dict, total: int, label: str) -> dict:
    if not counts:
        return {"name": None, "drawers": 0, "share": 0.0, "kind": label}
    name, drawers = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
    return {
        "name": name,
        "drawers": drawers,
        "share": (drawers / total) if total else 0.0,
        "kind": label,
    }


def room_skew(rooms: dict, total: int) -> dict:
    """The largest room's share of the palace. Reported, never enforced."""
    return _largest(rooms, total, "room")


def wing_skew(wings: dict, total: int) -> dict:
    """The largest wing's share of the palace. Reported, never enforced."""
    return _largest(wings, total, "wing")


def near_empty_wings(wings: dict, threshold: int = NEAR_EMPTY_THRESHOLD) -> list[dict]:
    """Wings holding at or below `threshold` drawers, smallest first."""
    return [
        {"wing": wing, "drawers": drawers}
        for wing, drawers in sorted(wings.items(), key=lambda kv: (kv[1], kv[0]))
        if drawers <= threshold
    ]


def kg_coverage(triples: int, drawers: int) -> dict:
    """Knowledge-graph triples as a share of drawers. Reported, never enforced."""
    return {
        "triples": triples,
        "drawers": drawers,
        "ratio": (triples / drawers) if drawers else 0.0,
    }


def lint(status: dict, kg: dict | None, max_items: int = DEFAULT_MAX_ITEMS) -> dict:
    """Run every check over one status dict. Pure — no palace access."""
    if not isinstance(status, dict):
        raise PalaceUnreadable(f"status is {type(status).__name__}, not a dict")
    for key in ("total_drawers", "wings", "rooms"):
        if key not in status:
            raise PalaceUnreadable(
                f"status is missing '{key}' — upstream returned an unusable shape"
            )

    wings = status["wings"]
    rooms = status["rooms"]
    total = status["total_drawers"]

    # A partial response that carried wings and rooms but no usable total would
    # otherwise report vacuous zero shares and exit 0 — a broken read presented
    # as a healthy palace.
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        raise PalaceUnreadable(f"total_drawers is not a count: {total!r}")
    for label, counts in (("wings", wings), ("rooms", rooms)):
        if not isinstance(counts, dict):
            raise PalaceUnreadable(f"'{label}' is {type(counts).__name__}, not a dict")
        for name, drawers in counts.items():
            if not isinstance(name, str):
                raise PalaceUnreadable(f"'{label}' has a non-string key: {name!r}")
            if not isinstance(drawers, int) or isinstance(drawers, bool) or drawers < 0:
                raise PalaceUnreadable(f"'{label}[{name}]' is not a count: {drawers!r}")

    fragmented = find_fragmented_wings(wings)
    empty = near_empty_wings(wings)

    hard_problems = []
    if fragmented:
        hard_problems.append("wing_name_fragmentation")
    if status.get("sqlite_integrity_failed"):
        hard_problems.append("sqlite_integrity")

    def cap(items):
        return items[:max_items], max(0, len(items) - max_items)

    capped_fragmented, withheld_fragmented = cap(fragmented)
    capped_empty, withheld_empty = cap(empty)

    return {
        "totals": {"drawers": total, "wings": len(wings), "rooms": len(rooms)},
        "room_skew": room_skew(rooms, total),
        "wing_skew": wing_skew(wings, total),
        "fragmented_wings": capped_fragmented,
        "near_empty_wings": capped_empty,
        "kg_coverage": (
            kg_coverage(kg["totals"]["triples"], total) if kg else None
        ),
        "sqlite_integrity": status.get("sqlite_integrity"),
        "hard_problems": hard_problems,
        # AC6: a cap that hides its own effect reads as "covered everything".
        "withheld": {
            "fragmented_wings": withheld_fragmented,
            "near_empty_wings": withheld_empty,
        },
    }


def load_status() -> dict:
    """Read palace status from upstream. The ONLY live palace access here.

    Uses the public ``tool_status()`` rather than upstream's private fast-path
    helper, so this does not couple to an implementation detail of a third-party
    package. Upstream attaches ``sqlite_integrity`` only when the check FAILS, so
    its absence is the clean case.
    """
    from mempalace.mcp_server import tool_status

    return tool_status()


def load_kg() -> dict | None:
    """Knowledge-graph totals via #72's checker. None when the graph is unreadable."""
    import sqlite3

    from rawgentic_memory import kg_health

    try:
        return kg_health.check(kg_health.DEFAULT_DB_PATH)
    except (sqlite3.Error, ValueError, UnicodeError):
        return None


def _pct(share: float) -> str:
    return f"{share * 100:.1f}%"


def render(report: dict) -> str:
    totals = report["totals"]
    lines = [
        f"palace: {totals['drawers']} drawers, {totals['wings']} wings, "
        f"{totals['rooms']} rooms",
        "",
        f"room skew:  {report['room_skew']['name']} "
        f"{report['room_skew']['drawers']} ({_pct(report['room_skew']['share'])})",
        f"wing skew:  {report['wing_skew']['name']} "
        f"{report['wing_skew']['drawers']} ({_pct(report['wing_skew']['share'])})",
    ]

    coverage = report["kg_coverage"]
    if coverage:
        lines.append(
            f"kg coverage: {coverage['triples']} triples over "
            f"{coverage['drawers']} drawers ({_pct(coverage['ratio'])})"
        )
    else:
        lines.append("kg coverage: knowledge graph unreadable — not checked")

    lines.append("")
    if report["fragmented_wings"]:
        lines.append(f"HARD — one project under more than one wing name "
                     f"({len(report['fragmented_wings'])}):")
        for group in report["fragmented_wings"]:
            spellings = ", ".join(
                f"{s['wing']} ({s['drawers']})" for s in group["spellings"]
            )
            lines.append(f"  {group['normalized']}: {spellings}")
        withheld = report["withheld"]["fragmented_wings"]
        if withheld:
            lines.append(f"  ... {withheld} more withheld by --max-items")
    else:
        lines.append("wing names: no fragmentation")

    if report["near_empty_wings"]:
        lines.append("")
        lines.append(f"near-empty wings ({len(report['near_empty_wings'])}):")
        for wing in report["near_empty_wings"]:
            lines.append(f"  {wing['wing']} ({wing['drawers']})")
        withheld = report["withheld"]["near_empty_wings"]
        if withheld:
            lines.append(f"  ... {withheld} more withheld by --max-items")

    if "sqlite_integrity" in report["hard_problems"]:
        lines.append("")
        lines.append(f"HARD — sqlite integrity: {report['sqlite_integrity']}")

    lines.append("")
    lines.append(
        "no hard problem" if not report["hard_problems"]
        else f"hard problems: {', '.join(report['hard_problems'])}"
    )
    return "\n".join(lines)


def _positive_int(raw: str) -> int:
    """Reject a cap below 1.

    ``--max-items 0`` would empty every list while the hard-problem list stayed
    populated, so the human output would say "no fragmentation" and the process
    would still exit 1. A negative cap additionally produces impossible withheld
    counts.
    """
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not an integer")
    if value < 1:
        raise argparse.ArgumentTypeError(f"--max-items must be at least 1, got {value}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rawgentic_memory.palace_lint",
        description="Report the shape of the memory palace. Enforces only hard problems.",
    )
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    parser.add_argument(
        "--max-items", type=_positive_int, default=DEFAULT_MAX_ITEMS,
        help=(
            f"cap each list (default {DEFAULT_MAX_ITEMS}, minimum 1). "
            "Withheld counts are always reported."
        ),
    )
    args = parser.parse_args(argv)

    try:
        status = load_status()
        kg = load_kg()
        report = lint(status, kg, max_items=args.max_items)
    except Exception as exc:
        # Upstream is a third-party API. A surprise from it must not escape as a
        # traceback whose process status collides with exit 1, which means
        # "hard problem found" — a failure would be read as a finding.
        reason = f"could not check the palace: {exc}"
        print(json.dumps({"error": reason}, indent=2) if args.json else reason)
        return 2

    print(json.dumps(report, indent=2) if args.json else render(report))
    return 1 if report["hard_problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
