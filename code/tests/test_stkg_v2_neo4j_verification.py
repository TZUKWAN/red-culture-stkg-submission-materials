import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


path = Path("scripts/288_verify_stkg_v2_neo4j.py")
spec = importlib.util.spec_from_file_location("verify_stkg_v2_neo4j", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class V2Neo4jVerificationTests(unittest.TestCase):
    def test_safe_identifier(self):
        self.assertEqual(module.safe_identifier("STATE_EVENT"), "STATE_EVENT")
        with self.assertRaises(ValueError):
            module.safe_identifier("Entity) DETACH DELETE n")

    def test_all_true_is_strict(self):
        self.assertTrue(module.all_true({"a": True, "b": True}))
        self.assertFalse(module.all_true({"a": True, "b": False}))
        self.assertFalse(module.all_true({}))

    def test_verifier_requires_creative_media_contract(self):
        source = path.read_text(encoding="utf-8")
        self.assertIn("creative_work_media_v2", source)
        self.assertIn("creative_media_complete", source)
        self.assertIn("media_qwen_v2", source)

    def test_capability_expectations_come_from_sqlite(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "final.sqlite"
            con = sqlite3.connect(database)
            con.executescript(
                "create table research_assertions(research_tier text);"
                "insert into research_assertions values('strict_semantic'),('contextual');"
                "create table research_culture_states(observation_tier text);"
                "insert into research_culture_states values('trusted_event_spacetime');"
                "create table research_evolution_transitions(id text);"
                "insert into research_evolution_transitions values('T1');"
                "create table research_evolution_transition_support(id text);"
                "insert into research_evolution_transition_support values('S1'),('S2');"
            )
            con.close()
            expected = module.read_sqlite_expectations(database)
        self.assertEqual(
            expected,
            {
                "assertion_tiers": {"contextual": 1, "strict_semantic": 1},
                "trusted_culture_states": 1,
                "published_transitions": 1,
                "published_transition_supports": 2,
            },
        )


if __name__ == "__main__":
    unittest.main()
