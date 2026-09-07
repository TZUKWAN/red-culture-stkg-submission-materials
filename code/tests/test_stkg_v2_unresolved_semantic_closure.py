import importlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


closure = importlib.import_module("scripts.281_close_stkg_v2_unresolved_semantics")


class UnresolvedSemanticClosureTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tempdir.name) / "v2.sqlite"
        self.con = sqlite3.connect(self.db)
        self.con.row_factory = sqlite3.Row
        self.con.execute("pragma foreign_keys=on")
        self.con.executescript(
            """
            create table v2_entities(
              entity_id text primary key,canonical_name text,source_entity_type text,
              semantic_entity_type text,aliases_json text,semantic_status text,
              confidence real,risk_tier text,decision_sources_json text,
              risk_flags_json text,method_version text,updated_at text
            );
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
            create table v2_name_cluster_members(
              cluster_id text,entity_id text,source_entity_type text
            );
            create table v2_semantic_conflicts(
              conflict_id text primary key,unit_kind text,unit_id text,
              conflict_type text,severity text,details_json text,status text,
              resolution_decision_id text,detected_at text,resolved_at text
            );
            """
        )
        entities = [
            ("E1", "群众", "Concept", None, "[]", "model_review", None, None, "[]", "[]", "old", "now"),
            ("E2", "模糊物", "Artifact", None, "[\"旧称\"]", "manual_review", None, "D", "[]", "[]", "old", "now"),
            ("E3", "毛泽东", "Person", "Person", "[\"毛润之\"]", "auto_accepted", 0.99, "A", "[]", "[]", "old", "now"),
            ("E4", "游击队", "Organization", "Organization", "[]", "auto_accepted", 0.99, "A", "[]", "[]", "old", "now"),
        ]
        self.con.executemany(
            "insert into v2_entities values(?,?,?,?,?,?,?,?,?,?,?,?)", entities
        )
        self.con.executemany(
            "insert into v2_model_tasks values(?,?,?,?,?,?,?,?,?,?)",
            [
                ("T1", "entity", "E1", "entity_type", "{}", "pending", 0, 1, "now", "now"),
                ("T2", "entity", "E2", "entity_type", "{}", "manual_review", 1, 1, "now", "now"),
            ],
        )
        self.con.executemany(
            "insert into v2_semantic_conflicts values(?,?,?,?,?,?,?,?,?,?)",
            [
                ("C1", "entity", "E1", "same_name_multiple_source_types", "warning", "{}", "open", None, "now", None),
                ("C2", "entity", "E4", "identity_ambiguity", "warning", json.dumps({"reason": "generic_label"}), "open", None, "now", None),
            ],
        )
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self.tempdir.cleanup()

    def test_closes_unknowns_without_changing_aliases_or_merging_identity(self):
        types = closure.unresolved_type_candidates(self.con)
        identities = closure.identity_candidates(self.con)
        alias_hash = closure.aliases_digest(self.con)
        self.con.execute("begin immediate")
        changes = closure.apply_closure(self.con, types, identities, "later")
        self.con.commit()

        self.assertEqual(changes["closed_entity_types"], 2)
        self.assertEqual(changes["context_scoped_identities"], 1)
        row = self.con.execute(
            "select semantic_entity_type,semantic_status,risk_tier,aliases_json "
            "from v2_entities where entity_id='E2'"
        ).fetchone()
        self.assertEqual(tuple(row), (None, "manual_review", "D", '["旧称"]'))
        effective = self.con.execute(
            "select effective_entity_type,type_validation_status "
            "from v2_entity_type_effective where entity_id='E2'"
        ).fetchone()
        self.assertEqual(tuple(effective), ("Artifact", "fallback_unresolved"))
        identity = self.con.execute(
            "select resolution_type,global_merge_target from v2_identity_resolutions"
        ).fetchone()
        self.assertEqual(tuple(identity), ("context_scoped_reference", None))
        self.assertEqual(
            self.con.execute("select status from v2_semantic_conflicts where conflict_id='C2'").fetchone()[0],
            "accepted_unknown",
        )
        self.assertEqual(closure.aliases_digest(self.con), alias_hash)
        self.assertEqual(
            self.con.execute("select status from v2_model_tasks where task_id='T1'").fetchone()[0],
            "manual_review",
        )
        self.assertEqual(closure.unresolved_type_candidates(self.con), [])

    def test_validated_entities_are_not_closure_candidates(self):
        ids = {str(item["row"]["entity_id"]) for item in closure.unresolved_type_candidates(self.con)}
        self.assertEqual(ids, {"E1", "E2"})


if __name__ == "__main__":
    unittest.main()
