import importlib
import sqlite3
import tempfile
import unittest
from pathlib import Path


repair = importlib.import_module("scripts.265_reopen_identity_conflicts_closed_by_type_review")


class V2IdentityConflictStatusRepairTests(unittest.TestCase):
    def test_only_identity_conflicts_closed_by_type_tasks_are_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "v2.sqlite"
            con = sqlite3.connect(database)
            con.executescript(
                """
                create table v2_entities(entity_id text primary key,canonical_name text);
                create table v2_model_tasks(task_id text primary key,task_type text);
                create table v2_model_decisions(decision_id text primary key,task_id text);
                create table v2_semantic_conflicts(
                  conflict_id text primary key,unit_id text,conflict_type text,status text,
                  resolution_decision_id text,resolved_at text
                );
                insert into v2_entities values('E1','二十五师'),('E2','另一节点');
                insert into v2_model_tasks values('T1','entity_type'),('T2','identity_resolution');
                insert into v2_model_decisions values('D1','T1'),('D2','T2');
                insert into v2_semantic_conflicts values
                  ('C1','E1','identity_ambiguity','resolved','D1','t'),
                  ('C2','E2','identity_ambiguity','resolved','D2','t');
                """
            )
            con.row_factory = sqlite3.Row
            rows = repair.candidates(con)
            con.close()
            self.assertEqual([row["conflict_id"] for row in rows], ["C1"])


if __name__ == "__main__":
    unittest.main()
