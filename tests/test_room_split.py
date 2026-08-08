"""Tests for rawgentic_memory.room_split — the #77 documentation-room split.

Classification is pure and tested directly. The apply and revert paths are
exercised against a REAL ephemeral palace built by the `isolated_palace` fixture,
never against `~/.mempalace`: a migration tool whose write path has never run is
a claim, not a capability.
"""
import json

import pytest

from rawgentic_memory import room_split


class TestProjectRelative:
    def test_strips_the_restage_prefix_and_the_project(self):
        assert room_split.project_relative(
            "/tmp/mempalace-restage/millions/docs/plans/x.md"
        ) == "docs/plans/x.md"

    def test_lowercases(self):
        assert room_split.project_relative(
            "/tmp/mempalace-restage/chorestory/docs/Product/REPORTING.md"
        ) == "docs/product/reporting.md"

    def test_an_empty_source_is_empty(self):
        assert room_split.project_relative("") == ""

    def test_an_ordinary_absolute_path_still_anchors_on_docs(self):
        """The next bulk mine will not come from the April staging directory. If
        only that shape classified, the catch-all would rebuild itself."""
        assert room_split.project_relative("/repo/docs/plans/x.md") == "docs/plans/x.md"
        assert room_split.classify("/repo/docs/plans/x.md") == "plans"

    def test_a_relative_path_anchors_too(self):
        assert room_split.classify("myproject/docs/product/x.md") == "product"

    def test_a_repeated_restage_component_does_not_break_the_anchor(self):
        assert room_split.classify(
            "/tmp/mempalace-restage/a/tmp/mempalace-restage/b/docs/plans/x.md"
        ) == "plans"

    def test_a_path_with_no_docs_component_stays_put(self):
        assert room_split.classify("/repo/src/plans/x.md") == room_split.RESIDUE_ROOM


class TestClassify:
    @pytest.mark.parametrize("path,room", [
        ("/tmp/mempalace-restage/p/docs/archive/features/x.md", "archive"),
        ("/tmp/mempalace-restage/p/docs/archive/sessions/x.md", "archive"),
        ("/tmp/mempalace-restage/p/docs/superpowers/plans/x.md", "specs"),
        ("/tmp/mempalace-restage/p/docs/plans/x.md", "plans"),
        ("/tmp/mempalace-restage/p/docs/planning/x.md", "plans"),
        ("/tmp/mempalace-restage/p/docs/product/x.md", "product"),
        ("/tmp/mempalace-restage/p/docs/features/x.md", "features"),
        ("/tmp/mempalace-restage/p/docs/reference/x.md", "reference"),
        ("/tmp/mempalace-restage/p/docs/design/x.md", "design"),
        ("/tmp/mempalace-restage/p/docs/architecture/x.md", "design"),
        ("/tmp/mempalace-restage/p/docs/migration/x.md", "migration"),
        ("/tmp/mempalace-restage/p/docs/monitoring/x.md", "operations"),
        ("/tmp/mempalace-restage/p/docs/TDD/x.md", "testing"),
    ])
    def test_known_folders_map_to_their_kind(self, path, room):
        assert room_split.classify(path) == room

    def test_archive_wins_over_a_later_broader_rule(self):
        """`docs/archive/analysis` is archive, not analysis — order matters."""
        assert room_split.classify(
            "/tmp/mempalace-restage/p/docs/archive/analysis/x.md"
        ) == "archive"

    def test_an_unrecognized_folder_stays_in_documentation(self):
        assert room_split.classify(
            "/tmp/mempalace-restage/p/docs/something-nobody-mapped/x.md"
        ) == room_split.RESIDUE_ROOM

    def test_a_missing_source_file_stays_put(self):
        assert room_split.classify("") == room_split.RESIDUE_ROOM

    @pytest.mark.parametrize("path", [
        "/tmp/mempalace-restage/p/docs/archived/x.md",
        "/tmp/mempalace-restage/p/docs/plans-old/x.md",
        "/tmp/mempalace-restage/p/docs/productivity/x.md",
        "/tmp/mempalace-restage/p/docs/designers/x.md",
    ])
    def test_a_sibling_folder_sharing_a_prefix_is_not_swept_in(self, path):
        """Matching is on component boundaries. Raw prefix matching would pull
        `docs/archived` into `archive` and break the promise that an
        unrecognized path stays put."""
        assert room_split.classify(path) == room_split.RESIDUE_ROOM

    def test_the_folder_itself_matches_without_a_child(self):
        assert room_split.classify("/repo/docs/archive") == "archive"


def _moves(*specs):
    return [
        {"id": f"d{i}", "wing": wing, "source_file": src,
         "from_room": room_split.SOURCE_ROOM, "to_room": room_split.classify(src)}
        for i, (wing, src) in enumerate(specs)
    ]


class TestSummarize:
    def test_counts_movers_and_stayers_separately(self):
        summary = room_split.summarize(_moves(
            ("millions", "/tmp/mempalace-restage/millions/docs/plans/a.md"),
            ("millions", "/tmp/mempalace-restage/millions/docs/archive/b.md"),
            ("millions", "/tmp/mempalace-restage/millions/docs/mystery/c.md"),
        ))
        assert summary["total"] == 3
        assert summary["moving"] == 2
        assert summary["staying"] == 1

    def test_breaks_down_per_wing(self):
        summary = room_split.summarize(_moves(
            ("millions", "/tmp/mempalace-restage/millions/docs/plans/a.md"),
            ("chorestory", "/tmp/mempalace-restage/chorestory/docs/product/b.md"),
        ))
        assert summary["by_wing"]["millions"] == {"plans": 1}
        assert summary["by_wing"]["chorestory"] == {"product": 1}

    def test_render_names_the_unchanged_room(self):
        summary = room_split.summarize(_moves(
            ("m", "/tmp/mempalace-restage/m/docs/mystery/c.md"),
        ))
        assert "(unchanged)" in room_split.render(summary)


class TestManifest:
    def test_records_only_real_moves(self, tmp_path):
        path = tmp_path / "revert.json"
        count = room_split.write_manifest(str(path), _moves(
            ("m", "/tmp/mempalace-restage/m/docs/plans/a.md"),
            ("m", "/tmp/mempalace-restage/m/docs/mystery/b.md"),
        ))
        assert count == 1
        payload = json.loads(path.read_text())
        assert payload["moves"][0]["to_room"] == "plans"
        assert payload["moves"][0]["from_room"] == "documentation"

    def test_never_overwrites_an_existing_manifest(self, tmp_path):
        """Overwriting would strand the drawers the old manifest describes."""
        path = tmp_path / "revert.json"
        path.write_text("{}")
        with pytest.raises(FileExistsError):
            room_split.write_manifest(str(path), _moves(
                ("m", "/tmp/mempalace-restage/m/docs/plans/a.md"),
            ))

    def test_records_a_version_and_a_count(self, tmp_path):
        path = tmp_path / "revert.json"
        room_split.write_manifest(str(path), _moves(
            ("m", "/tmp/mempalace-restage/m/docs/plans/a.md"),
        ))
        payload = json.loads(path.read_text())
        assert payload["manifest_version"] == room_split.MANIFEST_VERSION
        assert payload["move_count"] == 1


class TestReadManifest:
    def test_an_empty_object_is_refused(self, tmp_path):
        """It would otherwise revert nothing and report success — a recovery
        command claiming it worked while the palace stays migrated."""
        path = tmp_path / "m.json"
        path.write_text("{}")
        with pytest.raises(room_split.ManifestInvalid):
            room_split.read_manifest(str(path))

    def test_a_count_mismatch_is_refused(self, tmp_path):
        path = tmp_path / "m.json"
        path.write_text(json.dumps({
            "manifest_version": room_split.MANIFEST_VERSION,
            "source_room": "documentation",
            "move_count": 5,
            "moves": [{"id": "a", "from_room": "documentation", "to_room": "plans"}],
        }))
        with pytest.raises(room_split.ManifestInvalid):
            room_split.read_manifest(str(path))

    def test_a_wrong_version_is_refused(self, tmp_path):
        path = tmp_path / "m.json"
        path.write_text(json.dumps({
            "manifest_version": 99, "source_room": "documentation",
            "move_count": 0, "moves": [],
        }))
        with pytest.raises(room_split.ManifestInvalid):
            room_split.read_manifest(str(path))

    def test_a_row_missing_its_id_is_refused(self, tmp_path):
        path = tmp_path / "m.json"
        path.write_text(json.dumps({
            "manifest_version": room_split.MANIFEST_VERSION,
            "source_room": "documentation", "move_count": 1,
            "moves": [{"from_room": "documentation", "to_room": "plans"}],
        }))
        with pytest.raises(room_split.ManifestInvalid):
            room_split.read_manifest(str(path))

    def test_malformed_json_is_refused(self, tmp_path):
        path = tmp_path / "m.json"
        path.write_text("not json")
        with pytest.raises(room_split.ManifestInvalid):
            room_split.read_manifest(str(path))


class TestReadFromAnUnreadablePalace:
    def test_a_missing_palace_raises_rather_than_reporting_nothing(self, tmp_path):
        with pytest.raises(room_split.PalaceUnreadable):
            room_split.read_documentation_drawers(str(tmp_path / "nope"))

    def test_main_reports_exit_2_not_a_clean_run(self, tmp_path, capsys):
        rc = room_split.main(["--palace", str(tmp_path / "nope")])
        assert rc == 2
        assert "could not complete" in capsys.readouterr().out


class TestApplyGuards:
    def test_apply_refuses_without_the_backup_flag(self, tmp_path, capsys):
        rc = room_split.main([
            "--palace", str(tmp_path), "--apply", "--manifest", str(tmp_path / "m.json"),
        ])
        assert rc == 2
        assert "verified-backup" in capsys.readouterr().out

    def test_apply_refuses_without_a_manifest(self, tmp_path, capsys):
        rc = room_split.main([
            "--palace", str(tmp_path), "--apply", "--i-have-a-verified-backup",
        ])
        assert rc == 2
        assert "manifest" in capsys.readouterr().out

    def test_apply_and_revert_together_are_refused(self, tmp_path, capsys):
        assert room_split.main([
            "--palace", str(tmp_path), "--apply", "--revert", "--manifest", "x",
        ]) == 2

    def test_revert_needs_a_manifest(self, tmp_path, capsys):
        assert room_split.main([
            "--palace", str(tmp_path), "--revert", "--i-have-a-verified-backup",
        ]) == 2

    def test_revert_also_refuses_without_the_backup_flag(self, tmp_path, capsys):
        """--revert writes too. Documenting --apply as the only writing path and
        then letting --revert through would be the contract failing."""
        rc = room_split.main([
            "--palace", str(tmp_path), "--revert", "--manifest", str(tmp_path / "m.json"),
        ])
        assert rc == 2
        assert "verified-backup" in capsys.readouterr().out


@pytest.fixture
def seeded_palace(isolated_palace):
    """A REAL palace holding four documentation drawers with known source paths."""
    from mempalace.miner import add_drawer
    from mempalace.palace import get_collection

    collection = get_collection(str(isolated_palace), create=True)
    seeds = [
        ("docs/plans/roadmap.md", "plans"),
        ("docs/archive/features/old.md", "archive"),
        ("docs/product/spec.md", "product"),
        ("docs/mystery/unknown.md", "documentation"),
    ]
    for index, (relative, _) in enumerate(seeds):
        add_drawer(
            collection,
            wing="testwing",
            room="documentation",
            content=f"seed drawer {index} about {relative}",
            source_file=f"/tmp/mempalace-restage/testproj/{relative}",
            chunk_index=0,
            agent="test",
        )
    return isolated_palace


class TestApplyAndRevertOnARealPalace:
    def test_read_finds_the_seeded_drawers(self, seeded_palace):
        moves = room_split.read_documentation_drawers(str(seeded_palace))
        assert len(moves) == 4
        assert {m["to_room"] for m in moves} == {"plans", "archive", "product", "documentation"}

    def test_apply_moves_them_and_revert_puts_them_back(self, seeded_palace, tmp_path):
        from mempalace.palace import get_collection

        manifest = tmp_path / "revert.json"
        moves = room_split.read_documentation_drawers(str(seeded_palace))
        room_split.write_manifest(str(manifest), moves)
        applied = room_split.apply_moves(str(seeded_palace), moves)
        assert applied == 3  # the unmapped one does not move

        collection = get_collection(str(seeded_palace), create=False)
        rooms = {
            m["room"]
            for m in collection.get(include=["metadatas"])["metadatas"]
        }
        assert "plans" in rooms and "archive" in rooms and "product" in rooms

        restored = room_split.revert_manifest(str(seeded_palace), str(manifest))
        assert restored == 3
        after = {
            m["room"]
            for m in collection.get(include=["metadatas"])["metadatas"]
        }
        assert after == {"documentation"}

    def test_apply_preserves_every_other_metadata_key(self, seeded_palace, tmp_path):
        from mempalace.palace import get_collection

        collection = get_collection(str(seeded_palace), create=False)
        before = collection.get(include=["metadatas"])["metadatas"]
        keys_before = {frozenset(m.keys()) for m in before}

        moves = room_split.read_documentation_drawers(str(seeded_palace))
        room_split.apply_moves(str(seeded_palace), moves)

        after = collection.get(include=["metadatas"])["metadatas"]
        assert {frozenset(m.keys()) for m in after} == keys_before

    def test_a_missing_id_refuses_and_writes_nothing(self, seeded_palace):
        """Silently skipping a missing id and exiting 0 would leave a partly
        migrated palace that automation reads as a clean run."""
        from mempalace.palace import get_collection

        moves = room_split.read_documentation_drawers(str(seeded_palace))
        moves.append({
            "id": "does-not-exist", "wing": "testwing",
            "source_file": "/tmp/mempalace-restage/testproj/docs/plans/ghost.md",
            "from_room": "documentation", "to_room": "plans",
        })
        with pytest.raises(room_split.MoveIncomplete):
            room_split.apply_moves(str(seeded_palace), moves)

        collection = get_collection(str(seeded_palace), create=False)
        rooms = {m["room"] for m in collection.get(include=["metadatas"])["metadatas"]}
        assert rooms == {"documentation"}, "a refused move must write nothing at all"

    def test_duplicate_ids_are_refused(self, seeded_palace):
        moves = room_split.read_documentation_drawers(str(seeded_palace))
        movers = [m for m in moves if m["to_room"] != m["from_room"]]
        with pytest.raises(room_split.MoveIncomplete):
            room_split.apply_moves(str(seeded_palace), movers + [movers[0]])

    def test_no_drawer_is_lost(self, seeded_palace):
        from mempalace.palace import get_collection

        collection = get_collection(str(seeded_palace), create=False)
        before = collection.count()
        moves = room_split.read_documentation_drawers(str(seeded_palace))
        room_split.apply_moves(str(seeded_palace), moves)
        assert collection.count() == before
