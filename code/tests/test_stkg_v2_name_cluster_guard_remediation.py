import importlib
import sqlite3
import unittest


remediation = importlib.import_module(
    "scripts.278_remediate_stkg_v2_name_cluster_guard_violations"
)


class V2NameClusterGuardRemediationTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript(
            """
            create table v2_entities(
              entity_id text primary key,canonical_name text,source_entity_type text,
              semantic_entity_type text,semantic_status text,confidence real,risk_tier text,
              semantic_family text,type_facets_json text,decision_sources_json text,
              risk_flags_json text,method_version text,updated_at text);
            create table v2_name_cluster_members(
              cluster_id text,entity_id text,source_entity_type text,
              primary key(cluster_id,entity_id));
            """
        )

    def tearDown(self):
        self.con.close()

    def add_entity(self, entity_id, name, source_type, final_type, cluster_id):
        self.con.execute(
            "insert into v2_entities values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                entity_id, name, source_type, final_type, "auto_accepted", 0.95, "B",
                "Agent", "[]", "[]", "[]",
                "stkg-v2-name-cluster-adjudication-3", "now",
            ),
        )
        self.con.execute(
            "insert into v2_name_cluster_members values(?,?,?)",
            (cluster_id, entity_id, source_type),
        )

    def test_detects_only_active_guard_violations(self):
        self.add_entity("E1", "民兵", "Person", "Person", "C1")
        self.add_entity("E2", "傅品三", "Person", "Person", "C2")
        self.add_entity("E3", "傅品三", "Event", "Event", "C2")
        self.add_entity("E4", "中国人民解放军布告", "Event", "Document", "C3")
        rows = remediation.active_guard_violations(self.con)
        self.assertEqual({row["entity_id"] for row in rows}, {"E1", "E3"})
        reasons = {row["entity_id"]: row["guard_reason"] for row in rows}
        self.assertEqual(
            reasons["E1"], "generic_collective_requires_social_group_or_concept"
        )
        self.assertEqual(
            reasons["E3"], "person_name_collision_cannot_auto_confirm_event"
        )


if __name__ == "__main__":
    unittest.main()
