import importlib
import json
import unittest


semantics = importlib.import_module("scripts.stkg_v2_semantics")
restore = importlib.import_module("scripts.269_restore_stkg_v2_strict_place_descriptors")


class V2StrictPlaceDescriptorTests(unittest.TestCase):
    def test_restores_unambiguous_source_place_descriptors(self):
        names = [
            "中原解放区",
            "南昌解放行动途经地点",
            "宁都起义发生地",
            "长征路线",
            "革命武装起义与苏区创建核心区域",
            "云南贵州交界处军团部山坡",
            "红军长征过江后作战地点",
            "大革命时期中国共产党战略转移的重要起点",
        ]
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(semantics.strict_v2_entity_type_hint(name, "Place"), "Place")

    def test_does_not_convert_events_organizations_or_compounds(self):
        self.assertEqual(semantics.strict_v2_entity_type_hint("丘北县蚌鹃战斗", "Place"), "Event")
        self.assertEqual(semantics.strict_v2_entity_type_hint("万安党组织", "Place"), "Organization")
        self.assertEqual(semantics.strict_v2_entity_type_hint("南宜保中心县委", "Place"), "Organization")
        self.assertEqual(
            semantics.strict_v2_entity_type_hint(
                "怀玉山区为红军突围牺牲地,闽浙赣苏区为休整补充根据地", "Place"
            ),
            "",
        )

    def test_ledger_helpers_are_idempotent(self):
        first = restore.append_json_value("[]", "rule:test")
        second = restore.append_json_value(first, "rule:test")
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first), ["rule:test"])
        self.assertEqual(
            restore.stable_id("V2RULE", "E1", restore.RULE_NAME),
            restore.stable_id("V2RULE", "E1", restore.RULE_NAME),
        )


if __name__ == "__main__":
    unittest.main()
