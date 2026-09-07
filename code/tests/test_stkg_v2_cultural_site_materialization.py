import importlib
import json
import unittest


materialize = importlib.import_module("scripts.267_materialize_stkg_v2_cultural_sites")


class V2CulturalSiteMaterializationTests(unittest.TestCase):
    def test_ledger_helpers_are_idempotent(self):
        first = materialize.append_json_value("[]", "deterministic_rule:test")
        second = materialize.append_json_value(first, "deterministic_rule:test")
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first), ["deterministic_rule:test"])
        self.assertEqual(
            materialize.stable_id("V2RULE", "E1", materialize.RULE_NAME),
            materialize.stable_id("V2RULE", "E1", materialize.RULE_NAME),
        )


if __name__ == "__main__":
    unittest.main()
