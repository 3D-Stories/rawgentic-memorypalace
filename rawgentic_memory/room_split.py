"""Split the `documentation` room by KIND, using the taxonomy already in the data.

Issue #77, on the finding from #74. `documentation` holds 18,731 of 22,110 drawers
(84.7%) across 14 wings. The palace's retrieval premise is that a search can be
scoped — wings for projects, rooms for topics — and a room spanning 14 projects
and 85% of everything scopes to nothing.

**Why the room carries the KIND and not the project.** The issue proposed
per-project rooms. The per-wing breakdown argues against it: for 11 of the 14
wings the `documentation` room is 95-100% of the whole wing (`millions` is
2704 of 2705). A per-project room would restate the wing, which already scopes
the project, and the room dimension would still carry no information. The wing
keeps the project; the room becomes what a room is for. Owner decision,
2026-08-08.

The taxonomy is not invented. Every drawer's `source_file` records the folder it
was mined from, and those folders already sort the content: `docs/plans` 3357,
`docs/archive/**` 5251, `docs/superpowers/**` 1954, `docs/product` 852, and so on
across 59 distinct folders.

Usage::

    python -m rawgentic_memory.room_split                 # dry run — the default
    python -m rawgentic_memory.room_split --json
    python -m rawgentic_memory.room_split --apply --manifest revert.json \\
        --i-have-a-verified-backup
    python -m rawgentic_memory.room_split --revert --manifest revert.json \\
        --i-have-a-verified-backup

**Both `--apply` and `--revert` write to the palace, and both require
`--manifest` and `--i-have-a-verified-backup`.** Revert is the recovery path, but
it is still a write.

**Nothing here deletes a drawer.** The only mutation is a drawer's `room`
metadata value, and `--apply` writes the reversal manifest BEFORE it changes
anything, so every move can be undone by `--revert` with that file.

**A partial write is refused, not reported as success.** Every drawer id is
checked before anything is written, and a mismatch between what was asked for and
what was changed raises rather than exiting 0 — a half-migrated palace that
automation reads as clean is the worst outcome available here.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sqlite3
import sys
import urllib.parse

# Drawers per get/update round trip. One call per drawer put a full split past
# ten minutes and got it killed mid-write.
BATCH_SIZE = 500

SOURCE_ROOM = "documentation"
RESIDUE_ROOM = "documentation"

# Ordered; the FIRST matching prefix wins, so `docs/archive/...` is archive even
# though `docs/a...` would also match a later, broader rule. Matching is on the
# path AFTER the project directory, lowercased.
ROOM_RULES: tuple[tuple[str, str], ...] = (
    ("docs/archive", "archive"),
    ("docs/superpowers", "specs"),
    ("docs/specs", "specs"),
    ("docs/plans", "plans"),
    ("docs/planning", "plans"),
    ("docs/roadmap", "plans"),
    ("docs/product", "product"),
    ("docs/features", "features"),
    ("docs/reference", "reference"),
    ("docs/domain", "reference"),
    ("docs/design", "design"),
    ("docs/ux-review", "design"),
    ("docs/analysis", "analysis"),
    ("docs/reviews", "reviews"),
    ("docs/code-reviews", "reviews"),
    ("docs/runbooks", "operations"),
    ("docs/operations", "operations"),
    ("docs/monitoring", "operations"),
    ("docs/deploy", "operations"),
    ("docs/hardware", "operations"),
    ("docs/infrastructure", "operations"),
    ("docs/migration", "migration"),
    ("docs/sessions", "sessions"),
    ("docs/architecture", "design"),
    ("docs/tdd", "testing"),
    ("docs/testing", "testing"),
    ("docs/sdlc", "process"),
    ("docs/quickstart", "reference"),
)

DEFAULT_PALACE = os.path.expanduser("~/.mempalace/palace")


class PalaceUnreadable(Exception):
    """The palace store could not be read."""


def project_relative(source_file: str) -> str:
    """The path from the project's `docs` directory down, lowercased.

    The April 2026 bulk mine wrote paths like
    `/tmp/mempalace-restage/<project>/docs/plans/x.md`, from a staging directory
    that no longer exists. Anchoring on that prefix alone would classify only
    that one historical shape, so the NEXT bulk mine — from an ordinary path like
    `/repo/docs/plans/x.md` — would fall through to the residue room and rebuild
    the catch-all this tool exists to prevent.

    So the anchor is the first path COMPONENT named `docs`, whatever sits above
    it. A path with no such component returns lowercased and unanchored, which
    matches no rule and therefore keeps the residue room — the safe direction.
    """
    if not source_file:
        return ""
    parts = [p for p in source_file.replace("\\", "/").lower().split("/") if p]
    if "docs" in parts:
        parts = parts[parts.index("docs"):]
    return "/".join(parts)


def classify(source_file: str) -> str:
    """The room a drawer belongs in. Unrecognized paths keep the residue room.

    Matching is on COMPONENT boundaries, never a raw prefix. A raw prefix would
    pull `docs/archived`, `docs/plans-old` and `docs/productivity` into rooms
    they do not belong to, which would break the promise that an unrecognized
    path stays put.
    """
    relative = project_relative(source_file)
    for prefix, room in ROOM_RULES:
        if relative == prefix or relative.startswith(prefix + "/"):
            return room
    return RESIDUE_ROOM


def _connect(chroma_db: str) -> sqlite3.Connection:
    quoted = urllib.parse.quote_from_bytes(os.fsencode(chroma_db), safe="/")
    conn = sqlite3.connect(f"file:{quoted}?mode=ro", uri=True, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def read_documentation_drawers(palace_path: str) -> list[dict]:
    """Every drawer currently in the source room, with its id, wing and source."""
    chroma_db = os.path.join(palace_path, "chroma.sqlite3")
    try:
        conn = _connect(chroma_db)
    except sqlite3.Error as exc:
        raise PalaceUnreadable(f"{chroma_db}: {exc}") from exc

    try:
        names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM collections")}
        drawers_collection = next(
            (cid for cid, name in names.items() if name == "mempalace_drawers"), None
        )
        if drawers_collection is None:
            raise PalaceUnreadable("no mempalace_drawers collection in this palace")

        segments = {
            r["id"]: r["collection"] for r in conn.execute("SELECT id, collection FROM segments")
        }
        of_collection = {
            r["id"]: segments.get(r["segment_id"])
            for r in conn.execute("SELECT id, segment_id FROM embeddings")
        }
        # embeddings.id is the integer rowid; embedding_id is the drawer's own id.
        drawer_id = {
            r["id"]: r["embedding_id"]
            for r in conn.execute("SELECT id, embedding_id FROM embeddings")
        }

        def meta(key):
            return {
                r["id"]: r["string_value"]
                for r in conn.execute(
                    "SELECT id, string_value FROM embedding_metadata WHERE key = ?", (key,)
                )
            }

        rooms, wings, sources = meta("room"), meta("wing"), meta("source_file")
        return [
            {
                "id": drawer_id.get(row_id),
                "wing": wings.get(row_id, ""),
                "source_file": sources.get(row_id, ""),
                "from_room": SOURCE_ROOM,
                "to_room": classify(sources.get(row_id, "")),
            }
            for row_id, room in rooms.items()
            if room == SOURCE_ROOM and of_collection.get(row_id) == drawers_collection
        ]
    except sqlite3.Error as exc:
        raise PalaceUnreadable(f"{chroma_db}: {exc}") from exc
    finally:
        conn.close()


def summarize(moves: list[dict]) -> dict:
    """Counts per target room, per wing, and what stays put."""
    by_room: dict[str, int] = {}
    by_wing_room: dict[str, dict[str, int]] = {}
    for move in moves:
        by_room[move["to_room"]] = by_room.get(move["to_room"], 0) + 1
        wing = by_wing_room.setdefault(move["wing"], {})
        wing[move["to_room"]] = wing.get(move["to_room"], 0) + 1

    staying = by_room.get(RESIDUE_ROOM, 0)
    return {
        "total": len(moves),
        "moving": len(moves) - staying,
        "staying": staying,
        "by_room": dict(sorted(by_room.items(), key=lambda kv: (-kv[1], kv[0]))),
        "by_wing": {
            wing: dict(sorted(rooms.items(), key=lambda kv: (-kv[1], kv[0])))
            for wing, rooms in sorted(by_wing_room.items(), key=lambda kv: -sum(kv[1].values()))
        },
    }


MANIFEST_VERSION = 1


class ManifestInvalid(Exception):
    """The manifest is missing, malformed, or does not describe what it claims."""


class MoveIncomplete(Exception):
    """Some drawers could not be moved. The palace is now partly migrated."""


def write_manifest(path: str, moves: list[dict]) -> int:
    """Record every move so `--revert` can put each drawer back.

    Created with exclusive mode. Checking `os.path.exists` and then opening for
    write leaves a window in which another process can create the file and have
    it truncated here — which is exactly the "a manifest is never overwritten"
    promise failing quietly.
    """
    real = [
        {"id": m["id"], "from_room": m["from_room"], "to_room": m["to_room"]}
        for m in moves
        if m["to_room"] != m["from_room"] and m["id"]
    ]
    payload = {
        "manifest_version": MANIFEST_VERSION,
        "source_room": SOURCE_ROOM,
        "move_count": len(real),
        "moves": real,
    }
    try:
        handle = open(path, "x", encoding="utf-8")
    except FileExistsError as exc:
        raise FileExistsError(
            f"{path} exists. A manifest is a one-time record of one apply; "
            "overwriting it would strand the drawers it describes."
        ) from exc
    with handle:
        json.dump(payload, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    return len(real)


def read_manifest(path: str) -> dict:
    """Load a manifest and refuse anything that does not describe a real apply.

    An empty-but-valid JSON object would otherwise revert nothing and report
    success — a recovery command that says it worked while the palace stays
    migrated is worse than one that fails.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestInvalid(f"{path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ManifestInvalid(f"{path}: top level is not an object")
    if payload.get("manifest_version") != MANIFEST_VERSION:
        raise ManifestInvalid(
            f"{path}: manifest_version is {payload.get('manifest_version')!r}, "
            f"expected {MANIFEST_VERSION}"
        )
    if payload.get("source_room") != SOURCE_ROOM:
        raise ManifestInvalid(f"{path}: source_room is {payload.get('source_room')!r}")
    moves = payload.get("moves")
    if not isinstance(moves, list):
        raise ManifestInvalid(f"{path}: 'moves' is missing or not a list")
    if payload.get("move_count") != len(moves):
        raise ManifestInvalid(
            f"{path}: move_count {payload.get('move_count')!r} does not match "
            f"{len(moves)} recorded moves"
        )
    for move in moves:
        if not isinstance(move, dict) or not move.get("id") or not move.get("from_room"):
            raise ManifestInvalid(f"{path}: a move row is missing 'id' or 'from_room'")
    return payload


def _set_rooms(palace_path: str, pairs: list[tuple[str, str]]) -> int:
    """Set `room` on each (drawer id, room). Preserves every other metadata key.

    Every id is checked BEFORE anything is written. Skipping a missing id and
    exiting 0 would leave a partly migrated palace that automation reads as a
    clean run.
    """
    from mempalace.palace import get_collection

    collection = get_collection(palace_path, create=False)

    ids = [drawer for drawer, _ in pairs]
    seen = collections.Counter(ids)
    duplicates = [i for i, n in seen.items() if n > 1]
    if duplicates:
        raise MoveIncomplete(f"duplicate drawer ids requested: {sorted(duplicates)[:10]}")

    # Batched. One round trip per drawer — a get AND an update — is ~34,000 calls
    # for a full split, which ran past ten minutes and was killed part-way. That
    # left the palace half-migrated, which is the state every other guard here
    # exists to prevent.
    existing: dict[str, dict] = {}
    for start in range(0, len(ids), BATCH_SIZE):
        chunk = ids[start:start + BATCH_SIZE]
        found = collection.get(ids=chunk, include=["metadatas"])
        for drawer, meta in zip(found.get("ids") or [], found.get("metadatas") or []):
            existing[drawer] = dict(meta)

    missing = [drawer for drawer in ids if drawer not in existing]
    if missing:
        raise MoveIncomplete(
            f"{len(missing)} of {len(ids)} drawers are not in the palace; "
            f"nothing was written. First few: {missing[:5]}"
        )

    changed = 0
    for start in range(0, len(pairs), BATCH_SIZE):
        chunk = pairs[start:start + BATCH_SIZE]
        metadatas = []
        for drawer, room in chunk:
            updated = existing[drawer]
            updated["room"] = room
            metadatas.append(updated)
        collection.update(ids=[d for d, _ in chunk], metadatas=metadatas)
        changed += len(chunk)
    if changed != len(pairs):
        raise MoveIncomplete(f"wrote {changed} of {len(pairs)} drawers")
    return changed


def apply_moves(palace_path: str, moves: list[dict]) -> int:
    return _set_rooms(
        palace_path,
        [(m["id"], m["to_room"]) for m in moves if m["to_room"] != m["from_room"] and m["id"]],
    )


def revert_manifest(palace_path: str, manifest_path: str) -> int:
    payload = read_manifest(manifest_path)
    restored = _set_rooms(
        palace_path, [(m["id"], m["from_room"]) for m in payload["moves"]]
    )
    if restored != payload["move_count"]:
        raise MoveIncomplete(
            f"restored {restored} of {payload['move_count']} recorded moves"
        )
    return restored


def render(summary: dict) -> str:
    lines = [
        f"documentation drawers: {summary['total']}",
        f"  moving to a kind room: {summary['moving']}",
        f"  staying in documentation (unrecognized source path): {summary['staying']}",
        "",
        "target rooms:",
    ]
    for room, count in summary["by_room"].items():
        marker = "  (unchanged)" if room == RESIDUE_ROOM else ""
        lines.append(f"  {count:>6}  {room}{marker}")
    lines.append("")
    lines.append("per wing:")
    for wing, rooms in summary["by_wing"].items():
        total = sum(rooms.values())
        spread = ", ".join(f"{room} {n}" for room, n in rooms.items())
        lines.append(f"  {wing} ({total}): {spread}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rawgentic_memory.room_split",
        description="Split the documentation room by kind. Dry run unless --apply.",
    )
    parser.add_argument("--palace", default=DEFAULT_PALACE)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--apply", action="store_true", help="perform the move")
    parser.add_argument("--revert", action="store_true", help="undo a manifest")
    parser.add_argument("--manifest", help="reversal manifest path")
    parser.add_argument(
        "--i-have-a-verified-backup", action="store_true",
        help="required by --apply; the palace is 308 MB and a restore must have been tried",
    )
    args = parser.parse_args(argv)

    if args.apply and args.revert:
        print("--apply and --revert are mutually exclusive")
        return 2

    # Argument guards run BEFORE the palace is touched. Checking them after the
    # read would tell someone who forgot the backup flag only once the work was
    # done, and on an unreadable palace it would report the wrong problem.
    # --revert writes too. Saying "--apply is the only writing path" and then
    # letting --revert mutate without the backup flag is the contract failing.
    if (args.apply or args.revert) and not args.i_have_a_verified_backup:
        print(
            "refusing to write: pass --i-have-a-verified-backup. Both --apply and "
            "--revert change the palace, which is 308 MB, and a backup nobody has "
            "restored is not a backup."
        )
        return 2
    if args.apply and not args.manifest:
        print("refusing to apply: --manifest is required, so the move can be undone")
        return 2
    if args.revert and not args.manifest:
        print("--revert needs --manifest")
        return 2

    try:
        if args.revert:
            restored = revert_manifest(args.palace, args.manifest)
            print(f"reverted {restored} drawers to {SOURCE_ROOM}")
            return 0

        moves = read_documentation_drawers(args.palace)
        summary = summarize(moves)

        if args.apply:
            recorded = write_manifest(args.manifest, moves)
            moved = apply_moves(args.palace, moves)
            print(f"recorded {recorded} moves in {args.manifest}, applied {moved}")
            return 0

        print(json.dumps(summary, indent=2) if args.json else render(summary))
        return 0
    except (PalaceUnreadable, ManifestInvalid, MoveIncomplete,
            FileExistsError, OSError, ValueError) as exc:
        print(f"could not complete: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
