"""Tests for rawgentic_memory.palace_lint — the palace health linter (#73).

Every check is a pure function over a status dict, so each one is driven by a
fixture that HAS the defect and a fixture that does not. Nothing here reads the
live palace.
"""
import json

import pytest

from rawgentic_memory import palace_lint


def status(total, wings, rooms, **extra):
    payload = {"total_drawers": total, "wings": dict(wings), "rooms": dict(rooms)}
    payload.update(extra)
    return payload


@pytest.fixture
def healthy():
    return status(
        400,
        {"alpha": 200, "beta": 120, "gamma": 80},
        {"decisions": 150, "reference": 140, "gotchas": 110},
    )


@pytest.fixture
def skewed():
    """One room and one wing hold nearly everything — the shape epic #71 found."""
    return status(
        1000,
        {"chorestory": 850, "rawgentic": 100, "saystory": 50},
        {"documentation": 880, "decisions": 70, "diary": 50},
    )


class TestNormalizeWing:
    def test_strips_the_wing_prefix(self):
        assert palace_lint.normalize_wing("wing_rawgentic") == "rawgentic"

    def test_hyphen_and_underscore_are_the_same(self):
        assert palace_lint.normalize_wing("herdr-dashboard") == "herdr_dashboard"

    def test_case_is_ignored(self):
        assert palace_lint.normalize_wing("Herdr-Dashboard") == "herdr_dashboard"

    def test_case_folding_happens_before_the_prefix_is_stripped(self):
        """The other order leaves `Wing_rawgentic` as `wing_rawgentic`, so it never
        meets `rawgentic` and the fragmentation is missed."""
        assert palace_lint.normalize_wing("Wing_rawgentic") == "rawgentic"
        assert palace_lint.find_fragmented_wings({"Wing_rawgentic": 5, "rawgentic": 90})

    def test_a_distinct_project_keeps_a_distinct_key(self):
        """The check AC3 is sharpest about: these two must never collide."""
        assert palace_lint.normalize_wing("rawgentic") != palace_lint.normalize_wing(
            "rawgentic-next"
        )


class TestFragmentation:
    def test_detects_hyphen_versus_underscore(self):
        found = palace_lint.find_fragmented_wings({"herdr-dashboard": 134, "herdr_dashboard": 6})
        assert len(found) == 1
        assert found[0]["normalized"] == "herdr_dashboard"
        assert found[0]["drawers"] == 140

    def test_detects_the_wing_prefix_scheme(self):
        found = palace_lint.find_fragmented_wings({"rawgentic": 2290, "wing_rawgentic": 52})
        assert len(found) == 1
        assert [s["wing"] for s in found[0]["spellings"]] == ["rawgentic", "wing_rawgentic"]

    def test_does_not_merge_a_genuinely_different_project(self):
        """`rawgentic` and `rawgentic-next` are different projects. A checker that
        cannot tell them apart is worse than none (AC3)."""
        assert palace_lint.find_fragmented_wings({"rawgentic": 2290, "rawgentic-next": 40}) == []

    def test_does_not_merge_a_shared_prefix(self):
        assert palace_lint.find_fragmented_wings(
            {"rawgentic": 10, "rawgentic_memorypalace": 10, "wing_rawgentic-epic756": 1}
        ) == []

    def test_clean_wing_names_report_nothing(self, healthy):
        assert palace_lint.find_fragmented_wings(healthy["wings"]) == []

    def test_spellings_are_ordered_by_size(self):
        found = palace_lint.find_fragmented_wings({"a_b": 5, "wing_a-b": 90})
        assert [s["drawers"] for s in found[0]["spellings"]] == [90, 5]


class TestSkew:
    def test_room_skew_names_the_largest_room(self, skewed):
        skew = palace_lint.room_skew(skewed["rooms"], skewed["total_drawers"])
        assert skew["name"] == "documentation"
        assert skew["drawers"] == 880
        assert skew["share"] == pytest.approx(0.88)

    def test_wing_skew_names_the_largest_wing(self, skewed):
        skew = palace_lint.wing_skew(skewed["wings"], skewed["total_drawers"])
        assert skew["name"] == "chorestory"
        assert skew["share"] == pytest.approx(0.85)

    def test_a_balanced_palace_reports_a_low_share(self, healthy):
        assert palace_lint.room_skew(healthy["rooms"], healthy["total_drawers"])["share"] < 0.5

    def test_empty_palace_does_not_divide_by_zero(self):
        assert palace_lint.room_skew({}, 0)["share"] == 0.0


class TestNearEmptyWings:
    def test_finds_wings_at_or_below_the_threshold(self):
        found = palace_lint.near_empty_wings({"big": 500, "tiny": 1, "small": 3}, threshold=3)
        assert [w["wing"] for w in found] == ["tiny", "small"]

    def test_reports_nothing_when_every_wing_is_populated(self, healthy):
        assert palace_lint.near_empty_wings(healthy["wings"]) == []


class TestKgCoverage:
    def test_ratio_is_triples_over_drawers(self):
        cov = palace_lint.kg_coverage(158, 22110)
        assert cov["triples"] == 158
        assert cov["ratio"] == pytest.approx(158 / 22110)

    def test_no_drawers_does_not_divide_by_zero(self):
        assert palace_lint.kg_coverage(0, 0)["ratio"] == 0.0


class TestLint:
    def test_healthy_palace_has_no_hard_problem(self, healthy):
        report = palace_lint.lint(healthy, kg={"totals": {"triples": 40}})
        assert report["hard_problems"] == []

    def test_fragmentation_is_a_hard_problem(self, healthy):
        broken = dict(healthy)
        broken["wings"] = {"herdr-dashboard": 134, "herdr_dashboard": 6}
        report = palace_lint.lint(broken, kg=None)
        assert "wing_name_fragmentation" in report["hard_problems"]

    def test_sqlite_integrity_failure_is_a_hard_problem(self, healthy):
        broken = dict(healthy)
        broken["sqlite_integrity_failed"] = True
        broken["sqlite_integrity"] = {"error_count": 2}
        report = palace_lint.lint(broken, kg=None)
        assert "sqlite_integrity" in report["hard_problems"]

    def test_skew_is_reported_but_never_a_hard_problem(self, skewed):
        """AC1: exits non-zero only on a hard problem, never on a judgment call."""
        report = palace_lint.lint(skewed, kg=None)
        assert report["room_skew"]["share"] > 0.8
        assert report["hard_problems"] == []

    def test_missing_kg_is_reported_not_fatal(self, healthy):
        report = palace_lint.lint(healthy, kg=None)
        assert report["kg_coverage"] is None
        assert report["hard_problems"] == []


class TestTruncation:
    def test_a_cap_reports_how_many_it_withheld(self):
        """AC6: it never silently truncates a finding list."""
        wings = {f"tiny{i}": 1 for i in range(30)}
        wings["big"] = 5000
        report = palace_lint.lint(
            status(5030, wings, {"documentation": 5030}), kg=None, max_items=5
        )
        assert len(report["near_empty_wings"]) == 5
        assert report["withheld"]["near_empty_wings"] == 25

    def test_nothing_withheld_is_recorded_as_zero(self, healthy):
        report = palace_lint.lint(healthy, kg=None, max_items=50)
        assert report["withheld"]["near_empty_wings"] == 0

    def test_render_states_the_withheld_count(self):
        wings = {f"tiny{i}": 1 for i in range(30)}
        wings["big"] = 5000
        report = palace_lint.lint(
            status(5030, wings, {"documentation": 5030}), kg=None, max_items=5
        )
        assert "25 more withheld" in palace_lint.render(report)


class TestStatusShape:
    def test_a_status_without_wings_is_rejected(self):
        with pytest.raises(palace_lint.PalaceUnreadable):
            palace_lint.lint({"total_drawers": 5}, kg=None)

    def test_a_non_dict_status_is_rejected(self):
        with pytest.raises(palace_lint.PalaceUnreadable):
            palace_lint.lint(None, kg=None)

    def test_a_status_without_a_total_is_rejected(self):
        """A partial response would otherwise report vacuous zero shares and exit
        0 — a broken read presented as a healthy palace."""
        with pytest.raises(palace_lint.PalaceUnreadable):
            palace_lint.lint({"wings": {"a": 1}, "rooms": {"r": 1}}, kg=None)

    def test_a_non_integer_total_is_rejected(self):
        with pytest.raises(palace_lint.PalaceUnreadable):
            palace_lint.lint(status("many", {"a": 1}, {"r": 1}), kg=None)

    def test_a_negative_count_is_rejected(self):
        with pytest.raises(palace_lint.PalaceUnreadable):
            palace_lint.lint(status(5, {"a": -1}, {"r": 5}), kg=None)

    def test_a_non_dict_wings_collection_is_rejected(self):
        # Built by hand: the `status` helper coerces with dict(), which would
        # turn a bad value into a valid empty dict and hide the defect.
        with pytest.raises(palace_lint.PalaceUnreadable):
            palace_lint.lint(
                {"total_drawers": 5, "wings": ["a"], "rooms": {"r": 5}}, kg=None
            )


class TestMaxItemsValidation:
    def test_zero_is_rejected(self, healthy, monkeypatch):
        """A cap of 0 would empty every list while the hard-problem list stayed
        populated: the output would say "no fragmentation" and still exit 1."""
        monkeypatch.setattr(palace_lint, "load_status", lambda: healthy)
        with pytest.raises(SystemExit):
            palace_lint.main(["--max-items", "0"])

    def test_a_negative_cap_is_rejected(self, healthy, monkeypatch):
        monkeypatch.setattr(palace_lint, "load_status", lambda: healthy)
        with pytest.raises(SystemExit):
            palace_lint.main(["--max-items", "-3"])


class TestMain:
    def test_exit_0_on_a_healthy_palace(self, healthy, monkeypatch, capsys):
        monkeypatch.setattr(palace_lint, "load_status", lambda: healthy)
        monkeypatch.setattr(palace_lint, "load_kg", lambda: {"totals": {"triples": 40}})
        assert palace_lint.main([]) == 0

    def test_exit_1_on_fragmentation(self, healthy, monkeypatch, capsys):
        broken = dict(healthy, wings={"herdr-dashboard": 134, "herdr_dashboard": 6})
        monkeypatch.setattr(palace_lint, "load_status", lambda: broken)
        monkeypatch.setattr(palace_lint, "load_kg", lambda: None)
        assert palace_lint.main([]) == 1

    def test_exit_2_when_the_palace_cannot_be_read(self, monkeypatch, capsys):
        def boom():
            raise palace_lint.PalaceUnreadable("no palace here")

        monkeypatch.setattr(palace_lint, "load_status", boom)
        assert palace_lint.main([]) == 2
        assert "could not check" in capsys.readouterr().out.lower()

    def test_exit_2_when_upstream_raises_anything(self, monkeypatch, capsys):
        """The upstream status call is a third-party API; a surprise from it must
        not escape as a traceback whose status collides with exit 1."""
        def boom():
            raise RuntimeError("upstream changed shape")

        monkeypatch.setattr(palace_lint, "load_status", boom)
        assert palace_lint.main([]) == 2

    def test_json_output_is_parseable(self, skewed, monkeypatch, capsys):
        monkeypatch.setattr(palace_lint, "load_status", lambda: skewed)
        monkeypatch.setattr(palace_lint, "load_kg", lambda: None)
        rc = palace_lint.main(["--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["room_skew"]["name"] == "documentation"
        assert "withheld" in payload

    def test_json_error_report_is_parseable(self, monkeypatch, capsys):
        def boom():
            raise palace_lint.PalaceUnreadable("nope")

        monkeypatch.setattr(palace_lint, "load_status", boom)
        rc = palace_lint.main(["--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert payload["error"]
