import importlib
import unittest
from pathlib import Path


evolution = importlib.import_module("scripts.286_build_stkg_v2_evolution")


class V2EvolutionTests(unittest.TestCase):
    def test_stable_ids_are_dimension_sensitive(self):
        first = evolution.stable_id("STATE", "E1", "F1", "S1", "R1")
        self.assertEqual(first, evolution.stable_id("STATE", "E1", "F1", "S1", "R1"))
        self.assertNotEqual(first, evolution.stable_id("STATE", "E1", "F1", "S2", "R1"))

    def test_evidence_tiers_do_not_promote_single_assertion(self):
        self.assertEqual(evolution.evidence_tier("model_adjudicated", True), "trusted_event_spacetime")
        self.assertEqual(evolution.evidence_tier("source_consensus", True), "trusted_event_spacetime")
        self.assertEqual(evolution.evidence_tier("asserted_candidate", True), "asserted_event_spacetime")
        self.assertEqual(evolution.evidence_tier("model_adjudicated", False), "relation_context")

    def test_frozen_rules_forbid_sequence_inference(self):
        contract = evolution.load_yaml(Path("stkg/schema/evolution_rules_v1.yaml"))
        forms = {"HistoricalPractice", "InstitutionalPractice", "MaterialCulture", "DocumentaryCulture",
                 "CreativeNarrative", "SpiritValue", "MemoryTransmission"}
        self.assertEqual(evolution.validate_rules(contract, forms), [])
        contract["rules"]["sequence_alone_never_creates_transition"] = False
        self.assertTrue(any("sequence_alone" in item for item in evolution.validate_rules(contract, forms)))

    def test_transition_dimension_gate_requires_one_state_pair(self):
        rows = [
            {"candidate_id": "A", "region_id": "R1", "stage_code": "S1"},
            {"candidate_id": "B", "region_id": "R2", "stage_code": "S1"},
        ]
        self.assertEqual(evolution.select_unique_candidate_ids(rows, {"R2"}, {"S1"}), {"B"})
        self.assertEqual(evolution.select_unique_candidate_ids(rows, set(), {"S1"}), set())
        self.assertEqual(evolution.select_unique_candidate_ids([rows[0]], set(), set()), {"A"})


if __name__ == "__main__":
    unittest.main()
