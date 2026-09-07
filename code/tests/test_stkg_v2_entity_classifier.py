import importlib
import unittest


classifier = importlib.import_module("scripts.260_train_evaluate_stkg_v2_entity_classifier")


class V2EntityClassifierTests(unittest.TestCase):
    def test_same_name_always_uses_same_split(self):
        self.assertEqual(
            classifier.stable_validation_split("南昌起义"),
            classifier.stable_validation_split("南昌起义"),
        )

    def test_relation_token_preserves_direction_and_neighbor_type(self):
        self.assertEqual(
            classifier.relation_token("OUT", "raw:held_position_in", "Institution"),
            "OUT::raw:held_position_in::Institution",
        )

    def test_class_gate_rejects_small_or_inaccurate_samples(self):
        self.assertIsNone(classifier.choose_class_gate([(0.999, True)] * 49))
        self.assertIsNone(
            classifier.choose_class_gate([(0.999, True)] * 95 + [(0.999, False)] * 5)
        )

    def test_class_gate_accepts_large_high_precision_samples(self):
        gate = classifier.choose_class_gate(
            [(0.99, True)] * 400 + [(0.99, False)] * 2
        )
        self.assertIsNotNone(gate)
        self.assertGreaterEqual(gate["precision"], 0.98)
        self.assertGreaterEqual(gate["wilson_lower_95"], 0.95)


if __name__ == "__main__":
    unittest.main()
