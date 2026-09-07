import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


path = Path("scripts/292_run_stkg_v2_competency_queries.py")
spec = importlib.util.spec_from_file_location("stkg_v2_competency", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StkgV2CompetencyQueryTests(unittest.TestCase):
    def test_contract_has_26_distinct_query_files(self):
        contract = module.load_yaml(module.CONTRACT)
        self.assertEqual(len(contract["queries"]), 26)
        files = [item["file"] for item in contract["queries"].values()]
        self.assertEqual(len(files), len(set(files)))
        query_dir = module.ROOT / contract["query_directory"]
        self.assertTrue(all((query_dir / filename).exists() for filename in files))

    def test_read_only_authorizer_blocks_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "read_only.sqlite"
            con = sqlite3.connect(db)
            con.execute("create table t(value integer)")
            con.execute("insert into t values(1)")
            con.commit()
            con.close()
            read_only = module.open_read_only(db)
            self.assertEqual(read_only.execute("select value from t").fetchone()[0], 1)
            with self.assertRaises(sqlite3.DatabaseError):
                read_only.execute("delete from t")
            read_only.close()

    def test_execute_query_records_digest_and_preview(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("create table t(id integer,value text)")
        con.executemany("insert into t values(?,?)", [(1, "甲"), (2, "乙")])
        result = module.execute_query(con, "select * from t order by id", ["id", "value"])
        con.close()
        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["missing_required_columns"], [])
        self.assertEqual(result["preview"][0]["value"], "甲")
        self.assertEqual(len(result["rows_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
