import importlib
import json
import unittest


resolver = importlib.import_module("scripts.274_resolve_stkg_v2_strict_structure")


class V2StrictStructureResolutionTests(unittest.TestCase):
    def choose(self, name, source_type, hint):
        return resolver.choose_strict_structure_type(name, source_type, hint)

    def test_clear_structures_resolve(self):
        self.assertEqual(
            self.choose("遵义会议决议", "Event", "Document"),
            ("Document", "document_suffix_structure"),
        )
        self.assertEqual(
            self.choose("洪湖革命烈士纪念碑", "Person", "Artifact"),
            ("Artifact", "fixed_physical_artifact_structure"),
        )
        self.assertEqual(
            self.choose("安徽人民出版社", "Person", "Organization"),
            ("Organization", "explicit_organization_suffix_structure"),
        )
        self.assertEqual(
            self.choose("湖南省立第二女师", "Place", "Institution"),
            ("Institution", "institution_suffix_structure"),
        )
        self.assertEqual(
            self.choose("中央政治局委员", "Person", "Position"),
            ("Position", "position_suffix_structure"),
        )

    def test_specialized_information_and_culture_types_are_preserved(self):
        self.assertIsNone(self.choose("南昌起义", "CreativeWork", "Event"))
        self.assertIsNone(self.choose("长江", "Document", "Place"))
        self.assertIsNone(self.choose("长征行军日记", "Artifact", "Document"))
        self.assertIsNone(self.choose("人民战争", "Spirit", "Event"))
        self.assertIsNone(self.choose("团结战斗", "ValueFacet", "Event"))

    def test_action_phrases_and_composites_abstain(self):
        self.assertIsNone(self.choose("担任民兵队长", "Concept", "Position"))
        self.assertIsNone(self.choose("办夜校", "Concept", "Institution"))
        self.assertIsNone(self.choose("国民党二届三中、全会", "Concept", "Event"))
        self.assertIsNone(self.choose("抢修铁路", "Place", "Place"))
        self.assertIsNone(self.choose("围攻区政府", "Event", "Organization"))
        self.assertIsNone(self.choose("接管县政府", "Organization", "Organization"))

    def test_incomplete_military_designations_are_not_retyped(self):
        self.assertIsNone(self.choose("一乡师", "Concept", "Organization"))
        self.assertIsNone(self.choose("九团", "Person", "Organization"))
        self.assertEqual(
            self.choose("三大队", "Concept", "Organization"),
            ("Organization", "numbered_unit_structure"),
        )
        self.assertEqual(
            self.choose("红三十四师", "Organization", "Organization"),
            ("Organization", "strict_structure_confirms_source_type"),
        )

    def test_formation_phrase_is_an_event_not_the_organization(self):
        self.assertEqual(
            self.choose("农民协会成立", "Organization", "Event"),
            ("Event", "formation_event_structure"),
        )

    def test_ambiguous_admin_suffixes_do_not_confirm_places(self):
        self.assertIsNone(self.choose("朱晓村", "Place", "Place"))
        self.assertIsNone(self.choose("魏镇", "Place", "Place"))
        self.assertEqual(
            self.choose("沪宁铁路", "Place", "Place"),
            ("Place", "strict_structure_confirms_source_type"),
        )

    def test_ledger_json_is_idempotent(self):
        first = resolver.append_json_value("[]", "rule:test")
        second = resolver.append_json_value(first, "rule:test")
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first), ["rule:test"])


if __name__ == "__main__":
    unittest.main()
