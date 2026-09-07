import importlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


closure = importlib.import_module("scripts.282_close_stkg_v2_event_time_semantics")


class EventTimeSemanticClosureTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tempdir.name) / "v2.sqlite"
        self.con = sqlite3.connect(self.db)
        self.con.row_factory = sqlite3.Row
        self.con.execute("pragma foreign_keys=on")
        self.con.executescript(
            """
            create table v2_entities(entity_id text primary key,canonical_name text);
            create table v2_model_tasks(
              task_id text primary key,unit_kind text,unit_id text,task_type text,
              payload_json text,status text,attempts integer,priority integer,
              created_at text,updated_at text
            );
            create table v2_model_decisions(
              decision_id text primary key,task_id text,model text,prompt_version text,
              raw_response text,decision_json text,validator_pass integer,
              confidence real,created_at text
            );
            create table v2_assertion_scopes(
              fact_id text primary key,time_raw text,time_start text,time_end text,
              time_precision text,time_role text,time_owner_id text,semantic_status text,
              confidence real,risk_tier text,decision_sources_json text,updated_at text
            );
            create table v2_semantic_conflicts(
              conflict_id text primary key,unit_kind text,unit_id text,conflict_type text,
              severity text,details_json text,status text,resolution_decision_id text,
              detected_at text,resolved_at text
            );
            """
        )
        self.con.execute("insert into v2_entities values('E1','南昌起义')")
        candidates = [{"fact_id": value} for value in ("F1", "F2", "F3")]
        self.con.execute(
            "insert into v2_model_tasks values(?,?,?,?,?,'manual_review',1,1,'now','now')",
            ("T1", "entity", "E1", closure.TASK_TYPE, json.dumps({"candidates": candidates})),
        )
        decision = {
            "accepted_fact_ids": ["F1", "F2"],
            "rejected_fact_ids": [],
            "unknown_fact_ids": ["F3"],
            "confidence": 0.95,
        }
        self.con.execute(
            "insert into v2_model_decisions values(?,?,?,?,?,?,?,?,?)",
            ("D1", "T1", "Qwen", "v", "{}", json.dumps(decision), 1, 0.95, "now"),
        )
        rows = [
            ("F1", "南昌起义", "1927-08-01", "1937-07-06", "period", "event_occurrence", "E1", "auto_accepted", 0.95, "B", "[]", "now"),
            ("F2", "1927-1928年", "1927-01-01", "1928-12-31", "period", "event_occurrence", "E1", "auto_accepted", 0.95, "B", "[]", "now"),
            ("F3", "一九四一年", "1941-01-01", "1941-12-31", "year", "event_occurrence", "E1", "manual_review", 0.1, "D", "[]", "now"),
        ]
        self.con.executemany("insert into v2_assertion_scopes values(?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        self.con.execute(
            "insert into v2_semantic_conflicts values('C1','entity','E1','controlled_event_time_year_conflict','warning','{}','open',null,'now',null)"
        )
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.tempdir.cleanup()

    def test_label_period_is_context_but_numeric_period_is_retained(self):
        units = closure.event_time_units(self.con)
        self.assertEqual([item["fact_id"] for item in units[0]["overrides"]], ["F1"])
        digest = closure.time_value_digest(self.con)
        self.con.execute("begin immediate")
        changes = closure.apply_units(self.con, units, "later")
        self.con.commit()
        self.assertEqual(changes["guard_overrides"], 1)
        self.assertEqual(
            tuple(self.con.execute("select time_role,time_owner_id from v2_assertion_scopes where fact_id='F1'").fetchone()),
            ("context_time", None),
        )
        self.assertEqual(
            tuple(self.con.execute("select time_role,time_owner_id from v2_assertion_scopes where fact_id='F2'").fetchone()),
            ("event_occurrence", "E1"),
        )
        self.assertEqual(
            tuple(self.con.execute("select time_role,time_owner_id from v2_assertion_scopes where fact_id='F3'").fetchone()),
            ("unknown", None),
        )
        self.assertEqual(closure.time_value_digest(self.con), digest)
        labels = dict(self.con.execute("select fact_id,normalized_time_label from v2_time_display"))
        self.assertEqual(labels["F2"], "1927年-1928年")
        self.assertEqual(labels["F3"], "1941年")
        self.assertTrue(closure.validate(self.con, units, digest)["pass"])


if __name__ == "__main__":
    unittest.main()
