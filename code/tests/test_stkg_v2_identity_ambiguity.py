import importlib
import unittest


identity = importlib.import_module("scripts.262_flag_stkg_v2_identity_ambiguity")


class V2IdentityAmbiguityTests(unittest.TestCase):
    def test_generic_labels_are_flagged(self):
        self.assertEqual(identity.identity_ambiguity_reason("县委"), "generic_label")
        self.assertEqual(identity.identity_ambiguity_reason("地下党组织"), "generic_label")
        self.assertEqual(identity.identity_ambiguity_reason("旧址"), "generic_label")

    def test_incomplete_military_designations_are_flagged(self):
        self.assertEqual(
            identity.identity_ambiguity_reason("七师"), "incomplete_military_designation"
        )
        self.assertEqual(
            identity.identity_ambiguity_reason("红十团"), "incomplete_military_designation"
        )

    def test_qualified_names_are_not_flagged(self):
        self.assertIsNone(identity.identity_ambiguity_reason("中共兴国县委"))
        self.assertIsNone(identity.identity_ambiguity_reason("红七军第四连"))
        self.assertIsNone(identity.identity_ambiguity_reason("安徽革命博物馆"))

    def test_json_flag_append_is_idempotent(self):
        first = identity.append_json_value("[]", "identity_ambiguous:generic_label")
        second = identity.append_json_value(first, "identity_ambiguous:generic_label")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
