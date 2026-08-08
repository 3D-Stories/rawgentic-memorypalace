"""Tests for rawgentic_memory.kg_health — the knowledge-graph drift detector (#72).

Every test runs against a throwaway SQLite file carrying the upstream mempalace
schema. No test touches ~/.mempalace: writing drift into the live palace to test
a drift detector would defeat the point.
"""
import json
import sqlite3

import pytest

from rawgentic_memory import kg_health


# Mirrors mempalace/knowledge_graph.py _init_db — the two tables this reads.
SCHEMA = """
CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT DEFAULT 'unknown',
    properties TEXT DEFAULT '{}',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE triples (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    confidence REAL DEFAULT 1.0,
    source_closet TEXT,
    source_file TEXT,
    source_drawer_id TEXT,
    adapter_name TEXT,
    extracted_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def _make_db(path, triples):
    """Build a KG database holding `triples` as (id, subject, predicate, object, valid_to)."""
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    for tid, subject, predicate, obj, valid_to in triples:
        for eid in (subject, obj):
            conn.execute(
                "INSERT OR IGNORE INTO entities (id, name) VALUES (?, ?)", (eid, eid)
            )
        conn.execute(
            "INSERT INTO triples (id, subject, predicate, object, valid_from, valid_to) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (tid, subject, predicate, obj, "2026-01-01", valid_to),
        )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def clean_db(tmp_path):
    """One current value per (subject, predicate), plus a correctly superseded pair."""
    return _make_db(
        tmp_path / "clean.sqlite3",
        [
            ("t1", "rawgentic", "status", "shipped", None),
            ("t2", "hermes", "version", "v0.14.0", "2026-06-28"),
            ("t3", "hermes", "version", "v0.15.0", None),
            ("t4", "rawgentic", "requires", "pytest", None),
        ],
    )


@pytest.fixture
def declared_drift_db(tmp_path):
    """Two CURRENT values for `status`, which is a declared single-valued predicate."""
    return _make_db(
        tmp_path / "drift.sqlite3",
        [
            ("t1", "rawgentic", "status", "shipped", None),
            ("t2", "rawgentic", "status", "blocked", None),
        ],
    )


@pytest.fixture
def undeclared_drift_db(tmp_path):
    """Two CURRENT values for `requires`, which is legitimately multi-valued."""
    return _make_db(
        tmp_path / "undeclared.sqlite3",
        [
            ("t1", "rawgentic", "requires", "pytest", None),
            ("t2", "rawgentic", "requires", "chromadb", None),
        ],
    )


class TestDeclaredPredicates:
    def test_single_valued_set_is_not_empty(self):
        """An empty set would make exit code 1 unreachable while still exiting 0 —
        the gate would look clean because it had been silently disarmed."""
        assert len(kg_health.SINGLE_VALUED_PREDICATES) > 0

    def test_status_and_version_are_declared_single_valued(self):
        assert "status" in kg_health.SINGLE_VALUED_PREDICATES
        assert "version" in kg_health.SINGLE_VALUED_PREDICATES

    def test_genuinely_multi_valued_predicates_are_not_declared(self):
        """A subject legitimately requires many things and is blocked by many things."""
        assert "requires" not in kg_health.SINGLE_VALUED_PREDICATES
        assert "blocked_by" not in kg_health.SINGLE_VALUED_PREDICATES

    def test_debatable_predicates_are_left_out(self):
        """A wrong entry fails the check on valid data, which teaches everyone to
        ignore the check. A subject can publish through several channels and use
        several models, so these are reported rather than enforced."""
        for predicate in ("publishes_via", "provenance_is", "uses_model"):
            assert predicate not in kg_health.SINGLE_VALUED_PREDICATES

    def test_declared_set_is_immutable(self):
        assert isinstance(kg_health.SINGLE_VALUED_PREDICATES, frozenset)


class TestFindMultiValued:
    def test_clean_graph_reports_nothing(self, clean_db):
        with kg_health.connect_readonly(str(clean_db)) as conn:
            assert kg_health.find_multi_valued(conn) == []

    def test_detects_two_current_values(self, declared_drift_db):
        with kg_health.connect_readonly(str(declared_drift_db)) as conn:
            found = kg_health.find_multi_valued(conn)
        assert len(found) == 1
        assert found[0]["subject"] == "rawgentic"
        assert found[0]["predicate"] == "status"
        assert sorted(found[0]["objects"]) == ["blocked", "shipped"]
        assert found[0]["declared_single_valued"] is True

    def test_superseded_value_is_not_drift(self, clean_db):
        """hermes|version has two rows, but the older one carries valid_to."""
        with kg_health.connect_readonly(str(clean_db)) as conn:
            found = kg_health.find_multi_valued(conn)
        assert [f["predicate"] for f in found] == []

    def test_undeclared_predicate_is_reported_but_flagged(self, undeclared_drift_db):
        with kg_health.connect_readonly(str(undeclared_drift_db)) as conn:
            found = kg_health.find_multi_valued(conn)
        assert len(found) == 1
        assert found[0]["declared_single_valued"] is False


class TestFindDuplicateRows:
    def test_detects_same_triple_open_twice(self, tmp_path):
        db = _make_db(
            tmp_path / "dup.sqlite3",
            [
                ("t1", "rawgentic", "status", "shipped", None),
                ("t2", "rawgentic", "status", "shipped", None),
            ],
        )
        with kg_health.connect_readonly(str(db)) as conn:
            dups = kg_health.find_duplicate_rows(conn)
        assert len(dups) == 1
        assert dups[0]["rows"] == 2

    def test_clean_graph_has_no_duplicates(self, clean_db):
        with kg_health.connect_readonly(str(clean_db)) as conn:
            assert kg_health.find_duplicate_rows(conn) == []


class TestReadOnlyGuarantee:
    def test_connection_refuses_writes(self, clean_db):
        with kg_health.connect_readonly(str(clean_db)) as conn:
            with pytest.raises(sqlite3.OperationalError):
                conn.execute("INSERT INTO entities (id, name) VALUES ('x', 'x')")

    def test_missing_database_is_not_created(self, tmp_path):
        missing = tmp_path / "does-not-exist.sqlite3"
        with pytest.raises(sqlite3.Error):
            kg_health.connect_readonly(str(missing))
        assert not missing.exists()

    def test_query_string_in_path_cannot_escape_read_only(self, tmp_path):
        """A path carrying `?mode=rwc` must not reach SQLite as a mode override —
        it is part of the filename, and the URI builder has to escape it."""
        hostile = str(tmp_path / "evil.sqlite3?mode=rwc")
        with pytest.raises(sqlite3.Error):
            kg_health.connect_readonly(hostile)
        assert not (tmp_path / "evil.sqlite3").exists()
        assert list(tmp_path.iterdir()) == []


class TestCheck:
    def test_clean_graph_reports_totals(self, clean_db):
        report = kg_health.check(str(clean_db))
        assert report["totals"]["triples"] == 4
        assert report["totals"]["current"] == 3
        assert report["totals"]["expired"] == 1
        assert report["drift"] == []

    def test_declared_drift_is_reported_as_drift(self, declared_drift_db):
        report = kg_health.check(str(declared_drift_db))
        assert len(report["drift"]) == 1
        assert report["drift"][0]["predicate"] == "status"

    def test_undeclared_drift_is_not_counted_as_drift(self, undeclared_drift_db):
        report = kg_health.check(str(undeclared_drift_db))
        assert report["drift"] == []
        assert len(report["multi_valued"]) == 1


class TestMainExitCodes:
    def test_exit_0_on_clean_graph(self, clean_db, capsys):
        assert kg_health.main(["--db", str(clean_db)]) == 0

    def test_exit_1_on_declared_drift(self, declared_drift_db, capsys):
        assert kg_health.main(["--db", str(declared_drift_db)]) == 1

    def test_exit_0_on_undeclared_multi_value(self, undeclared_drift_db, capsys):
        """Reported, never enforced — a predicate nobody declared is a judgment call."""
        assert kg_health.main(["--db", str(undeclared_drift_db)]) == 0

    def test_exit_1_on_duplicate_open_rows(self, tmp_path, capsys):
        """The same fact stored twice is never intended — upstream's add_triple
        dedupes exactly that, so a duplicate means something bypassed it."""
        db = _make_db(
            tmp_path / "dup.sqlite3",
            [
                ("t1", "rawgentic", "requires", "pytest", None),
                ("t2", "rawgentic", "requires", "pytest", None),
            ],
        )
        assert kg_health.main(["--db", str(db)]) == 1

    def test_exit_2_when_database_absent(self, tmp_path, capsys):
        """An absent database must never read as a clean bill of health."""
        assert kg_health.main(["--db", str(tmp_path / "nope.sqlite3")]) == 2

    def test_exit_2_when_triples_table_missing(self, tmp_path, capsys):
        empty = tmp_path / "empty.sqlite3"
        sqlite3.connect(str(empty)).close()
        assert kg_health.main(["--db", str(empty)]) == 2

    def test_exit_2_prints_a_named_reason(self, tmp_path, capsys):
        kg_health.main(["--db", str(tmp_path / "nope.sqlite3")])
        assert "could not check" in capsys.readouterr().out.lower()


class TestJsonOutput:
    def test_json_flag_emits_parseable_report(self, declared_drift_db, capsys):
        rc = kg_health.main(["--db", str(declared_drift_db), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert payload["drift"][0]["predicate"] == "status"
        assert payload["totals"]["current"] == 2

    def test_json_error_report_is_still_parseable(self, tmp_path, capsys):
        rc = kg_health.main(["--db", str(tmp_path / "nope.sqlite3"), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert payload["error"]


class TestDefaultPath:
    def test_default_path_points_at_the_live_palace(self):
        assert kg_health.DEFAULT_DB_PATH.endswith("knowledge_graph.sqlite3")

    def test_default_is_used_only_when_db_argument_is_absent(self, clean_db, monkeypatch):
        """Passing --db must not consult the default path at all."""
        monkeypatch.setattr(kg_health, "DEFAULT_DB_PATH", "/nonexistent/should-not-be-read")
        assert kg_health.main(["--db", str(clean_db)]) == 0
