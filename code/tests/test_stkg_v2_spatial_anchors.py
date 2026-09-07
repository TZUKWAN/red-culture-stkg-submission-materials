import importlib
import sqlite3
import tempfile
import unittest
from pathlib import Path


anchors = importlib.import_module("scripts.268_materialize_stkg_v2_spatial_anchors")


class V2SpatialAnchorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tempdir.name) / "fixture.sqlite"
        self.report = Path(self.tempdir.name) / "report.json"
        con = sqlite3.connect(self.db)
        con.executescript(
            """
            pragma foreign_keys=on;
            create table v2_entities(
              entity_id text primary key,
              canonical_name text not null,
              source_entity_type text not null,
              semantic_entity_type text,
              semantic_status text not null
            ) without rowid;
            create table v2_assertion_scopes(
              fact_id text primary key,
              place_raw text,
              canonical_place_id text
            ) without rowid;
            create table v2_semantic_conflicts(
              conflict_id text primary key,
              unit_kind text not null,
              unit_id text not null,
              conflict_type text not null,
              severity text not null,
              details_json text not null,
              status text not null,
              resolution_decision_id text,
              detected_at text not null,
              resolved_at text
            ) without rowid;
            """
        )
        con.executemany(
            "insert into v2_entities values(?,?,?,?,?)",
            [
                ("P1", "南昌市", "Place", "Place", "auto_accepted"),
                ("C1", "会议旧址", "Place", "CulturalSite", "auto_accepted"),
                ("I1", "武汉中学", "Organization", "Institution", "auto_accepted"),
                ("E1", "丘北县蚌鹃战斗", "Place", "Event", "auto_accepted"),
                ("P2", "长征路线", "Place", "Place", "model_review"),
                ("A1", "烈士纪念碑", "Artifact", "Artifact", "auto_accepted"),
                ("O1", "某县委", "Organization", "Organization", "auto_accepted"),
            ],
        )
        con.executemany(
            "insert into v2_assertion_scopes values(?,?,?)",
            [
                ("F1", "南昌市", "P1"),
                ("F2", "会议旧址", "C1"),
                ("F3", "武汉中学", "I1"),
                ("F4", "丘北县蚌鹃战斗", "E1"),
                ("F5", "长征路线", "P2"),
                ("F6", "未知地点", None),
                ("F7", None, None),
                ("F8", "烈士纪念碑", "A1"),
                ("F9", "某县委", "O1"),
            ],
        )
        con.commit()
        con.close()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_classification_separates_entity_type_from_spatial_role(self):
        dry = anchors.run(self.db, self.report, apply=False)
        self.assertEqual(dry["assertion_count"], 9)
        con = sqlite3.connect(self.db)
        self.assertIsNone(con.execute(
            "select name from sqlite_master where name='v2_assertion_spatial_anchors'"
        ).fetchone())
        con.close()

        first = anchors.run(self.db, self.report, apply=True)
        self.assertEqual(first["materialized_count"], 9)
        self.assertEqual(first["validated_at_place"], 2)
        self.assertEqual(first["validated_at_named_site"], 2)
        self.assertEqual(first["open_spatial_conflicts"], 4)

        con = sqlite3.connect(self.db)
        indexes = {row[1] for row in con.execute("pragma index_list(v2_assertion_spatial_anchors)")}
        self.assertIn("idx_v2_spatial_anchor_source", indexes)
        rows = dict(con.execute(
            "select fact_id,anchor_kind || ':' || coalesce(edge_type,'') "
            "from v2_assertion_spatial_anchors"
        ))
        self.assertEqual(rows["F1"], "spatial_entity:AT_PLACE")
        self.assertEqual(rows["F2"], "spatial_entity:AT_PLACE")
        self.assertEqual(rows["F3"], "named_site:AT_NAMED_SITE")
        self.assertEqual(rows["F4"], "invalid_nonspatial:")
        self.assertEqual(rows["F5"], "pending_entity_type:")
        self.assertEqual(rows["F6"], "raw_only:")
        self.assertEqual(rows["F7"], "none:")
        self.assertEqual(rows["F8"], "named_cultural_object_site:AT_NAMED_SITE")
        self.assertEqual(rows["F9"], "invalid_nonspatial:")
        self.assertEqual(con.execute("pragma quick_check").fetchone()[0], "ok")
        self.assertEqual(con.execute("select count(*) from pragma_foreign_key_check").fetchone()[0], 0)
        con.close()

        second = anchors.run(self.db, self.report, apply=True)
        self.assertEqual(second["changed_rows"], 0)
        self.assertEqual(second["inserted_conflicts"], 0)
        self.assertEqual(second["open_spatial_conflicts"], 4)

    def test_label_normalization_is_conservative(self):
        self.assertEqual(anchors.normalize_label(" 武汉 中学 "), "武汉中学")
        self.assertEqual(anchors.normalize_label("Ａ／Ｂ"), "A/B")


if __name__ == "__main__":
    unittest.main()
