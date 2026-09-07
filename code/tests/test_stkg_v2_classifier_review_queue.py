import importlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


prepare_module = importlib.import_module("scripts.261_prepare_stkg_v2_classifier_review")


class V2ClassifierReviewQueueTests(unittest.TestCase):
    def test_only_eligible_type_changes_enter_queue_and_repeat_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "v2.sqlite"
            predictions = root / "predictions.sqlite"
            report = root / "report.json"
            con = sqlite3.connect(database)
            con.executescript(
                """
                create table v2_entities(
                  entity_id text primary key, semantic_status text not null
                );
                create table v2_model_tasks(
                  task_id text primary key, unit_kind text not null, unit_id text not null,
                  task_type text not null, payload_json text not null, status text not null,
                  attempts integer not null, priority integer not null, created_at text not null,
                  updated_at text not null, unique(unit_kind,unit_id,task_type)
                );
                """
            )
            con.executemany(
                "insert into v2_entities values(?,?)",
                [("E1", "model_review"), ("E2", "model_review"), ("E3", "auto_accepted")],
            )
            con.executemany(
                "insert into v2_model_tasks values(?,?,?,?,?,'pending',0,100,'t','t')",
                [
                    ("T1", "entity", "E1", "entity_type", '{"schema_votes":{"Organization":2}}'),
                    ("T2", "entity", "E2", "entity_type", '{}'),
                    ("T3", "entity", "E3", "entity_type", '{}'),
                ],
            )
            con.commit()
            con.close()
            con = sqlite3.connect(predictions)
            con.executescript(
                """
                create table classifier_metadata(key text primary key,value_json text not null);
                create table entity_predictions(
                  entity_id text primary key, canonical_name text not null, source_type text not null,
                  predicted_type text not null, confidence real not null, margin real not null,
                  lexical_hint text, schema_top_type text, eligible_rule_candidate integer not null
                );
                """
            )
            con.execute(
                "insert into classifier_metadata values('metadata',?)",
                (json.dumps({"model_version": "test-model"}),),
            )
            con.executemany(
                "insert into entity_predictions values(?,?,?,?,?,?,?,?,?)",
                [
                    ("E1", "七师", "Institution", "Organization", 0.99, 0.9, "Organization", None, 1),
                    ("E2", "甲", "Person", "Person", 0.99, 0.9, None, "Person", 1),
                    ("E3", "乙", "Concept", "Event", 0.99, 0.9, "Event", None, 1),
                ],
            )
            con.commit()
            con.close()

            first = prepare_module.prepare(database, predictions, report)
            second = prepare_module.prepare(database, predictions, report)
            self.assertEqual(first["inserted"], 1)
            self.assertEqual(second["inserted"], 0)
            self.assertEqual(second["already_present"], 1)
            con = sqlite3.connect(database)
            row = con.execute(
                "select payload_json,status from v2_model_tasks "
                "where task_type='entity_type_classifier_review'"
            ).fetchone()
            con.close()
            payload = json.loads(row[0])
            self.assertEqual(payload["classifier_predicted_type"], "Organization")
            self.assertEqual(payload["schema_votes"], {"Organization": 2})
            self.assertEqual(row[1], "pending")


if __name__ == "__main__":
    unittest.main()
