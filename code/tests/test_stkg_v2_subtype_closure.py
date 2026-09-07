import importlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


closure = importlib.import_module("scripts.259_resolve_compatible_stkg_v2_subtypes")


class V2SubtypeClosureTests(unittest.TestCase):
    def test_only_clean_name_collision_is_rule_candidate(self):
        self.assertTrue(
            closure.is_compatible_subtype_candidate(
                "AdministrativeRegion", json.dumps(["same_name_multiple_source_types"])
            )
        )
        self.assertFalse(
            closure.is_compatible_subtype_candidate(
                "AdministrativeRegion",
                json.dumps(["same_name_multiple_source_types", "lexical_source_type_conflict"]),
            )
        )
        self.assertFalse(
            closure.is_compatible_subtype_candidate(
                "Artifact", json.dumps(["same_name_multiple_source_types"])
            )
        )

    def test_append_unique_is_idempotent(self):
        once = closure.append_unique("[]", "rule")
        twice = closure.append_unique(once, "rule")
        self.assertEqual(json.loads(twice), ["rule"])

    def test_schema_migration_adds_hierarchy_columns_and_rule_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "v2.sqlite"
            con = sqlite3.connect(database)
            try:
                con.execute("create table v2_entities(entity_id text primary key)")
                closure.ensure_schema(con)
                con.commit()
                columns = {row[1] for row in con.execute("pragma table_info(v2_entities)")}
                tables = {row[0] for row in con.execute("select name from sqlite_master where type='table'")}
            finally:
                con.close()
            self.assertIn("semantic_family", columns)
            self.assertIn("type_facets_json", columns)
            self.assertIn("v2_rule_resolutions", tables)


if __name__ == "__main__":
    unittest.main()
