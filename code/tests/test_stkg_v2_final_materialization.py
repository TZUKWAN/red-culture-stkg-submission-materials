import importlib.util
import sqlite3
import unittest
from pathlib import Path


path = Path("scripts/290_materialize_stkg_v2_final.py")
spec = importlib.util.spec_from_file_location("stkg_v2_final_materialization", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StkgV2FinalMaterializationTests(unittest.TestCase):
    def test_schema_enforces_media_foreign_key_and_view(self):
        con = sqlite3.connect(":memory:")
        con.execute("pragma foreign_keys=on")
        con.executescript(
            "create table research_entities(entity_id text primary key,canonical_name text not null,"
            "entity_type text not null,aliases_json text not null);"
            "create table research_build_metadata(key text primary key,value_json text not null);"
        )
        con.executescript(module.SCHEMA)
        con.execute("insert into research_entities values('E1','作品','CreativeWork','[]')")
        con.execute("insert into research_creative_media_types values('歌曲')")
        con.execute(
            "insert into research_creative_work_media values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "E1", "作品", "歌曲", "qwen_v2_semantic_classification", "completed", 0.95,
                1, "Qwen", "v1", "title", "名称显示歌曲", "[]", "[]", "{}", "{}", "now",
            ),
        )
        self.assertEqual(con.execute("select media_type from v_research_creative_work_media").fetchone()[0], "歌曲")
        self.assertIn(
            "explicit_spirit_value_projection",
            con.execute("select sql from sqlite_master where name='research_culture_state_value_facets'").fetchone()[0],
        )
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute(
                "insert into research_creative_work_media values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "MISSING", "坏记录", "歌曲", "x", "completed", 1.0, 0, None, None,
                    "x", "x", "[]", "[]", "{}", None, "now",
                ),
            )
        con.close()

    def test_validate_detects_missing_media(self):
        con = sqlite3.connect(":memory:")
        con.execute("pragma foreign_keys=on")
        con.executescript(
            "create table research_entities(entity_id text primary key,canonical_name text not null,"
            "entity_type text not null,aliases_json text not null);"
            "create table research_build_metadata(key text primary key,value_json text not null);"
        )
        con.executescript(module.SCHEMA)
        con.execute("insert into research_entities values('E1','作品','CreativeWork','[]')")
        _, failures = module.validate(con, 0)
        self.assertTrue(any("creative_work_count" in item for item in failures))
        con.close()


if __name__ == "__main__":
    unittest.main()
