import importlib
import json
import unittest


closure = importlib.import_module("scripts.264_close_stkg_v2_classifier_same_type")


class V2ClassifierSameTypeTests(unittest.TestCase):
    def test_append_source_is_idempotent(self):
        first = closure.append_json_value("[]", "local_classifier:test")
        second = closure.append_json_value(first, "local_classifier:test")
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first), ["local_classifier:test"])

    def test_stable_resolution_id(self):
        self.assertEqual(
            closure.stable_id("V2RULE", "E1", closure.RULE_NAME),
            closure.stable_id("V2RULE", "E1", closure.RULE_NAME),
        )


if __name__ == "__main__":
    unittest.main()
