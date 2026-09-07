import importlib
import json
import unittest


resolver = importlib.import_module("scripts.273_resolve_stkg_v2_strict_same_name_consensus")


class V2StrictSameNameConsensusTests(unittest.TestCase):
    def test_exact_type_and_compatible_spatial_subtype_resolve(self):
        self.assertEqual(
            resolver.choose_consensus_type("Event", {"Event"}),
            ("Event", "strict_and_exact_same_name_type"),
        )
        self.assertEqual(
            resolver.choose_consensus_type("Place", {"AdministrativeRegion"}),
            ("AdministrativeRegion", "strict_place_with_same_name_administrative_subtype"),
        )

    def test_incompatible_or_multi_type_consensus_abstains(self):
        self.assertIsNone(resolver.choose_consensus_type("Institution", {"Institution", "Place"}))
        self.assertIsNone(resolver.choose_consensus_type("Organization", {"Institution"}))
        self.assertIsNone(resolver.choose_consensus_type("", {"Person"}))

    def test_specialized_information_objects_are_not_retyped_by_name_only(self):
        self.assertIsNone(
            resolver.choose_consensus_type("Event", {"Event"}, "CreativeWork")
        )
        self.assertIsNone(
            resolver.choose_consensus_type("Place", {"Place"}, "Document")
        )
        self.assertEqual(
            resolver.choose_consensus_type("Document", {"Document"}, "Document"),
            ("Document", "strict_and_exact_same_name_type"),
        )

    def test_ledger_json_is_idempotent(self):
        first = resolver.append_json_value("[]", "rule:test")
        second = resolver.append_json_value(first, "rule:test")
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first), ["rule:test"])


if __name__ == "__main__":
    unittest.main()
