import importlib
import sqlite3
import tempfile
import unittest
from pathlib import Path


initializer = importlib.import_module("scripts.255_initialize_stkg_v2_semantic_repair")


def create_source(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
    create table stkg_entities(
      entity_id text primary key, canonical_name text not null, entity_type text not null,
      member_count integer not null, aliases_json text not null, source_created_at text not null
    );
    create table stkg_assertions(
      fact_id text primary key, subject_id text not null, predicate text not null, object_id text not null,
      time_raw text, time_start text, time_end text, time_display text, time_key_raw_fallback text,
      time_precision text not null, source_time_precision text not null, canonical_place_id text,
      place_raw text, place_key_raw_fallback text, province_raw text, city_raw text, county_raw text,
      province text, city text, county text, basin_section_raw text, basin_section text, place_role_raw text,
      place_roles_json text not null, integration_status text not null, member_count integer not null,
      integration_version text not null, source_created_at text not null
    );
    create table stkg_assertion_provenance(provenance_id text primary key);
    create table stkg_assertion_place_links(fact_id text primary key);
    """)
    con.executemany(
        "insert into stkg_entities values(?,?,?,?,?,?)",
        [
            ("E1", "南昌起义", "Event", 1, "[]", "2026-01-01"),
            ("P1", "某人物", "Person", 1, "[]", "2026-01-01"),
        ],
    )
    con.execute(
        "insert into stkg_assertions values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "F1", "P1", "participated_in", "E1", "1899年", "1899-01-01", "1899-12-31",
            "1899年", None, "year", "year", None, None, None, None, None, None, None, None, None,
            None, None, None, "[]", "integrated", 1, "v1", "2026-01-01",
        ),
    )
    con.execute("insert into stkg_assertion_provenance values('R1')")
    con.commit()
    con.close()


class V2SemanticInitializationTests(unittest.TestCase):
    def test_source_and_destination_must_differ(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite"
            create_source(source)
            with self.assertRaisesRegex(ValueError, "must differ"):
                initializer.initialize(source, source, "test-v2", {})

    def test_initialization_preserves_source_and_does_not_promote_adjacent_time(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite"
            destination = Path(directory) / "v2.sqlite"
            create_source(source)
            before = initializer.sha256(source)
            result = initializer.initialize(
                source,
                destination,
                "test-v2",
                {
                    "entities": 2,
                    "assertions": 1,
                    "provenance": 1,
                    "event_entities": 1,
                    "timed_assertions": 1,
                    "assertions_with_place": 0,
                },
            )
            self.assertEqual(initializer.sha256(source), before)
            self.assertEqual(result["work_quick_check"], "ok")
            con = sqlite3.connect(destination)
            row = con.execute(
                "select source_object_type,time_start,time_role,time_owner_id,semantic_status "
                "from v2_assertion_scopes where fact_id='F1'"
            ).fetchone()
            self.assertEqual(row, ("Event", "1899-01-01", "unknown", None, "pending"))
            self.assertEqual(
                con.execute("select semantic_entity_type,semantic_status from v2_entities where entity_id='E1'").fetchone(),
                (None, "pending"),
            )
            self.assertEqual(con.execute("pragma foreign_key_check").fetchall(), [])
            con.close()

    def test_expected_count_mismatch_fails_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite"
            destination = Path(directory) / "v2.sqlite"
            create_source(source)
            with self.assertRaisesRegex(RuntimeError, "source baseline failed"):
                initializer.initialize(source, destination, "test-v2", {"entities": 99})
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
