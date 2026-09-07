import importlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


prepare_module = importlib.import_module("scripts.263_prepare_stkg_v2_model_second_review")


class V2ModelSecondReviewQueueTests(unittest.TestCase):
    def test_only_current_completed_single_model_decisions_are_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "v2.sqlite"
            report = root / "report.json"
            con = sqlite3.connect(database)
            con.executescript(
                """
                create table v2_entities(
                  entity_id text primary key, source_entity_type text not null,
                  semantic_entity_type text, semantic_status text not null
                );
                create table v2_model_tasks(
                  task_id text primary key, unit_kind text not null, unit_id text not null,
                  task_type text not null, payload_json text not null, status text not null,
                  attempts integer not null, priority integer not null, created_at text not null,
                  updated_at text not null, unique(unit_kind,unit_id,task_type)
                );
                create table v2_model_decisions(
                  decision_id text primary key,task_id text not null,model text not null,
                  prompt_version text not null,raw_response text not null,decision_json text not null,
                  validator_pass integer not null,confidence real,created_at text not null
                );
                """
            )
            con.executemany(
                "insert into v2_entities values(?,?,?,?)",
                [
                    ("E1", "Event", "Organization", "auto_accepted"),
                    ("E2", "Person", None, "manual_review"),
                ],
            )
            con.executemany(
                "insert into v2_model_tasks values(?,?,?,?,?,'completed',1,100,'t','t')",
                [("T1", "entity", "E1", "entity_type", '{}'), ("T2", "entity", "E2", "entity_type", '{}')],
            )
            con.execute(
                "insert into v2_model_decisions values(?,?,?,?,?,?,?,?,?)",
                (
                    "D1", "T1", "Qwen", "v2", "{}",
                    json.dumps({"decision": "retype", "final_type": "Organization"}),
                    1, 0.95, "t",
                ),
            )
            con.commit()
            con.close()

            first = prepare_module.prepare(database, report)
            second = prepare_module.prepare(database, report)
            self.assertEqual(first["inserted"], 1)
            self.assertEqual(second["inserted"], 0)
            con = sqlite3.connect(database)
            payload = json.loads(con.execute(
                "select payload_json from v2_model_tasks where task_type=?",
                (prepare_module.TASK_TYPE,),
            ).fetchone()[0])
            con.close()
            self.assertEqual(payload["prior_model_type"], "Organization")
            self.assertEqual(payload["prior_decision_id"], "D1")


if __name__ == "__main__":
    unittest.main()
