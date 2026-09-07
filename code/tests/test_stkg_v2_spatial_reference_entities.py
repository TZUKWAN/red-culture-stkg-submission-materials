import importlib
import json
import unittest


semantics = importlib.import_module("scripts.stkg_v2_semantics")
resolver = importlib.import_module("scripts.270_resolve_stkg_v2_spatial_reference_entities")


class V2SpatialReferenceEntityTests(unittest.TestCase):
    def test_strict_suffixes_distinguish_spatial_reference_pollution(self):
        expected = {
            "铜仁军分区": "Organization",
            "中共四川省军委": "Organization",
            "贵定地委": "Organization",
            "罗平中学": "Institution",
            "泸西师范": "Institution",
            "北碚图书馆": "Institution",
            "将军山之役纪念碑": "Artifact",
            "红军路": "Place",
        }
        for name, expected_type in expected.items():
            with self.subTest(name=name):
                self.assertEqual(semantics.strict_v2_entity_type_hint(name, "Place"), expected_type)
        self.assertEqual(semantics.strict_v2_entity_type_hint("林基路", "Place"), "")
        self.assertEqual(
            semantics.strict_v2_entity_type_hint("东固会师与传达六大精神", "Event"), ""
        )

    def test_resolution_requires_strict_or_spatial_consensus(self):
        self.assertEqual(
            resolver.choose_resolution("Organization", set(), False),
            ("Organization", "strict_structural_nonspatial_type", 0.99),
        )
        self.assertEqual(
            resolver.choose_resolution("", {"Place", "AdministrativeRegion"}, False),
            ("AdministrativeRegion", "same_name_spatial_family_consensus", 0.98),
        )
        self.assertEqual(
            resolver.choose_resolution("", set(), True),
            ("AdministrativeRegion", "administrative_gazetteer_exact_match", 0.99),
        )
        self.assertIsNone(resolver.choose_resolution("", {"Person"}, False))
        self.assertIsNone(resolver.choose_resolution("", {"Event", "Place"}, False))

    def test_ledger_helpers_are_idempotent(self):
        first = resolver.append_json_value("[]", "rule:test")
        second = resolver.append_json_value(first, "rule:test")
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first), ["rule:test"])


if __name__ == "__main__":
    unittest.main()
