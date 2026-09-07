import importlib
import sqlite3
import tempfile
import unittest
from pathlib import Path


indexes = importlib.import_module("scripts.266_add_stkg_v2_semantic_query_indexes")


class V2SemanticQueryIndexTests(unittest.TestCase):
    def test_indexes_are_created_idempotently(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "v2.sqlite"
            report = root / "report.json"
            con = sqlite3.connect(database)
            con.execute(
                "create table v2_assertion_scopes("
                "fact_id text primary key,object_id text,canonical_place_id text)"
            )
            con.commit()
            con.close()
            first = indexes.run(database, report)
            second = indexes.run(database, report)
            self.assertEqual(set(first["created_indexes"]), set(indexes.INDEXES))
            self.assertEqual(second["created_indexes"], [])
            self.assertTrue(all(
                any("INDEX" in value.upper() for value in plan)
                for plan in second["query_plans"].values()
            ))


if __name__ == "__main__":
    unittest.main()
