import importlib
import unittest
from collections import Counter


rules = importlib.import_module("scripts.stkg_v2_semantics")


class V2SemanticRuleTests(unittest.TestCase):
    def test_participation_time_is_relation_validity_not_event_occurrence(self):
        label = rules.classify_time_scope(
            "participated_in", "1899-01-01", "P1", "Person", "E1", "Event"
        )
        self.assertEqual(label.role, "relation_validity")
        self.assertIsNone(label.owner_id)

    def test_controlled_event_occurrence_has_event_owner(self):
        label = rules.classify_time_scope(
            "occurred_at", "1927-08-01", "E1", "Event", "L1", "Place"
        )
        self.assertEqual((label.role, label.owner_id, label.risk_tier), ("event_occurrence", "E1", "A"))

    def test_generic_raw_time_is_context_only(self):
        label = rules.classify_time_scope(
            "raw:关联", "1923-01-01", "P1", "Person", "E1", "Event"
        )
        self.assertEqual(label.role, "context_time")
        self.assertIsNone(label.owner_id)

    def test_explicit_raw_event_time_is_risk_b(self):
        label = rules.classify_time_scope(
            "raw:事件时间", "1927-08-01", "E1", "Event", "T1", "TimePeriod"
        )
        self.assertEqual((label.role, label.owner_id, label.risk_tier), ("event_occurrence", "E1", "B"))

    def test_cross_type_same_name_requires_context(self):
        result = rules.fuse_entity_type("CreativeWork", "Event", Counter(), True)
        self.assertEqual((result.final_type, result.status, result.risk_tier), (None, "model_review", "C"))

    def test_strong_organization_hint_can_repair_bad_event_type(self):
        result = rules.fuse_entity_type("Event", "Organization", Counter(), False)
        self.assertEqual((result.final_type, result.status), ("Organization", "auto_accepted"))

    def test_schema_votes_can_resolve_cross_type_name(self):
        result = rules.fuse_entity_type("Event", "", Counter({"Person": 5, "Event": 1}), True)
        self.assertEqual((result.final_type, result.status, result.risk_tier), ("Person", "auto_accepted", "B"))

    def test_raw_event_place_does_not_make_its_date_event_time(self):
        time_label = rules.classify_time_scope(
            "raw:发生于", "1911-01-01", "E1", "Event", "L1", "Place"
        )
        place_label = rules.classify_space_scope(
            "raw:发生于", "L1", "E1", "Event", "L1", "Place"
        )
        self.assertEqual(time_label.role, "context_time")
        self.assertEqual((place_label.role, place_label.owner_id), ("event_location", "E1"))

    def test_administrative_region_is_not_downgraded_to_place(self):
        self.assertEqual(
            rules.refine_lexical_hint("安乡县", "AdministrativeRegion", "Place"),
            "AdministrativeRegion",
        )

    def test_short_person_name_ending_in_mountain_is_not_a_place_hint(self):
        self.assertEqual(rules.refine_lexical_hint("曾山", "Person", "Place"), "")

    def test_pioneer_team_is_an_organization_hint(self):
        self.assertEqual(rules.refine_lexical_hint("武汉人民解放先锋队", "Event", ""), "Organization")

    def test_embedded_red_army_token_does_not_make_artifact_an_organization(self):
        self.assertEqual(rules.refine_lexical_hint("红军树", "Artifact", "Organization"), "")

    def test_person_name_ending_red_army_does_not_become_organization(self):
        self.assertEqual(rules.refine_lexical_hint("王红军", "Person", "Organization"), "")

    def test_role_and_action_phrase_do_not_become_organizations(self):
        self.assertEqual(
            rules.refine_lexical_hint("支部书记", "Position", "Organization"), "Position"
        )
        self.assertEqual(
            rules.refine_lexical_hint("建立中共龙洲师范支部", "Event", "Organization"), ""
        )

    def test_strict_organization_suffix_still_resolves(self):
        self.assertEqual(rules.refine_lexical_hint("县工委", "Person", "Organization"), "Organization")
        self.assertEqual(
            rules.refine_lexical_hint("四川地下党组织", "Person", "Organization"),
            "Organization",
        )

    def test_red_army_document_and_place_get_specific_hints(self):
        self.assertEqual(rules.refine_lexical_hint("红军医书", "Document", "Organization"), "Document")
        self.assertEqual(rules.refine_lexical_hint("红军路", "Place", "Organization"), "Place")

    def test_military_issuer_does_not_hide_document_suffix(self):
        self.assertEqual(
            rules.strict_v2_entity_type_hint("中国人民解放军布告", "Event"),
            "Document",
        )

    def test_contained_event_or_document_tokens_do_not_override_structural_suffix(self):
        self.assertEqual(
            rules.refine_lexical_hint("战斗回忆录", "Artifact", "Event"), "Document"
        )
        self.assertEqual(
            rules.refine_lexical_hint("战斗报社", "Organization", "Event"), "Organization"
        )
        self.assertEqual(
            rules.refine_lexical_hint("四川暴动行动大纲", "Document", "Event"), "Document"
        )

    def test_generic_event_concept_and_student_phrase_abstain(self):
        self.assertEqual(rules.refine_lexical_hint("武装斗争", "Concept", "Event"), "")
        self.assertEqual(rules.refine_lexical_hint("南菁中学学生", "Concept", "Institution"), "")

    def test_narrative_title_file_bag_and_generic_site_are_not_overtyped(self):
        self.assertEqual(rules.refine_lexical_hint("金沙江上话长征", "Artifact", "Event"), "")
        self.assertEqual(rules.refine_lexical_hint("文件包", "Concept", "Document"), "Artifact")
        self.assertEqual(rules.refine_lexical_hint("旧址", "Concept", "Institution"), "")

    def test_military_designation_requires_full_structure(self):
        self.assertEqual(rules.strict_v2_entity_type_hint("七师", "Institution"), "Organization")
        self.assertEqual(rules.strict_v2_entity_type_hint("万县四师", "Institution"), "")

    def test_numbered_unit_formation_document_and_village_hints(self):
        self.assertEqual(rules.strict_v2_entity_type_hint("三大队", "Concept"), "Organization")
        self.assertEqual(
            rules.strict_v2_entity_type_hint("中共徐海蚌特委第一次成立", "Organization"),
            "Event",
        )
        self.assertEqual(rules.strict_v2_entity_type_hint("日记读后感", "Event"), "Document")
        self.assertEqual(rules.strict_v2_entity_type_hint("瓦寨", "Place"), "Place")
        self.assertEqual(rules.strict_v2_entity_type_hint("一大队", "Place"), "")
        self.assertEqual(rules.strict_v2_entity_type_hint("山寨精神", "Spirit"), "Spirit")

    def test_history_titles_and_context_endpoint_guards(self):
        self.assertEqual(rules.strict_v2_entity_type_hint("罢市救亡史", "Event"), "Document")
        self.assertEqual(rules.strict_v2_entity_type_hint("红军战史", "Concept"), "Document")
        self.assertEqual(rules.strict_v2_entity_type_hint("编纂革命斗争史", "Event"), "")
        self.assertEqual(
            rules.strict_v2_entity_type_hint("颁布第二号布告", "Event"), ""
        )
        self.assertEqual(
            rules.strict_v2_entity_type_hint("红军宣传革命主张张贴布告", "Event"), ""
        )
        self.assertEqual(
            rules.strict_v2_entity_type_hint("九江收回英租界", "Event"), "Event"
        )
        self.assertEqual(
            rules.strict_v2_entity_type_hint("追认烈士与修建墓碑", "Event"), "Event"
        )
        for action_name in (
            "交通站传递信件",
            "祖孙三代珍藏医书",
            "创办崇新小学",
            "办农民夜校",
            "高文华参加农讲所",
            "打入南报社",
            "北上联系江淮四地委",
            "选举中央执行委员及候补委员",
            "接管剑河工作队",
        ):
            with self.subTest(action_name=action_name):
                self.assertEqual(
                    rules.strict_v2_entity_type_hint(action_name, "Event"), ""
                )
        self.assertEqual(rules.strict_v2_entity_type_hint("中小学", "Concept"), "")
        self.assertEqual(
            rules.strict_v2_entity_type_hint("红一、四方面军", "Person"), ""
        )
        self.assertEqual(
            rules.entity_context_contraindication(
                "金马", "Person", "Place",
                [{"predicate": "stationed_at", "endpoint_role": "subject"}],
            ),
            "controlled_relation_domain_conflicts_with_spatial_type",
        )
        self.assertEqual(
            rules.entity_context_contraindication(
                "海瑞", "Person", "CreativeWork",
                [{"predicate": "depicts", "endpoint_role": "object"}],
            ),
            "depicted_person_cannot_be_retyped_as_information_object",
        )
        self.assertEqual(
            rules.entity_context_contraindication(
                "扎西", "Person", "Place",
                [
                    {"predicate": "organized", "endpoint_role": "subject"},
                    {"predicate": "occurred_at", "endpoint_role": "object"},
                ],
            ),
            "",
        )
        self.assertEqual(
            rules.entity_context_contraindication(
                "扎西", "Person", "Place",
                [
                    {"predicate": "organized", "endpoint_role": "subject"},
                    {"predicate": "raw:发生地", "endpoint_role": "object"},
                    {"predicate": "raw:active_at", "endpoint_role": "object"},
                ],
            ),
            "",
        )

    def test_type_facets_preserve_specific_type_and_parent(self):
        self.assertEqual(
            rules.type_facets("AdministrativeRegion"),
            ("AdministrativeRegion", "Place", "SpatialEntity"),
        )
        self.assertEqual(
            rules.type_facets("CulturalSite"),
            ("CulturalSite", "Place", "SpatialEntity"),
        )

    def test_cultural_sites_are_not_institutions_or_generic_sites(self):
        self.assertEqual(rules.strict_v2_entity_type_hint("广州起义旧址"), "CulturalSite")
        self.assertEqual(rules.strict_v2_entity_type_hint("雨花台烈士陵园"), "CulturalSite")
        self.assertEqual(rules.strict_v2_entity_type_hint("郭沫若故居"), "CulturalSite")
        self.assertEqual(rules.strict_v2_entity_type_hint("武汉中学"), "Institution")
        self.assertEqual(rules.strict_v2_entity_type_hint("中国革命博物馆"), "Institution")
        self.assertEqual(rules.strict_v2_entity_type_hint("旧址"), "")
        self.assertEqual(rules.strict_v2_entity_type_hint("修建烈士陵园"), "")
        self.assertEqual(rules.strict_v2_entity_type_hint("烈士墓/旧址"), "")
        self.assertEqual(rules.strict_v2_entity_type_hint("盘石, 石渡监狱旧址"), "")

    def test_cross_type_collision_preserves_uncontested_subtype(self):
        result = rules.fuse_entity_type("AdministrativeRegion", "", Counter(), True)
        self.assertEqual(result.final_type, "AdministrativeRegion")
        self.assertEqual(result.status, "auto_accepted")


if __name__ == "__main__":
    unittest.main()
