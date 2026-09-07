import importlib
import sqlite3
import unittest


preparer = importlib.import_module("scripts.275_prepare_stkg_v2_name_cluster_reviews")
worker = importlib.import_module("scripts.276_qwen_adjudicate_one_stkg_v2_name_cluster")


def member(entity_id, name, source_type):
    return {
        "entity_id": entity_id,
        "canonical_name": name,
        "source_entity_type": source_type,
    }


def assignment(entity_id, decision, final_type, confidence=0.98, explanation="上下文明确。"):
    return {
        "entity_id": entity_id,
        "decision": decision,
        "final_type": final_type,
        "confidence": confidence,
        "reason_code": "test",
        "explanation": explanation,
    }


class V2NameClusterReviewTests(unittest.TestCase):
    def test_priority_prefers_high_impact_clusters(self):
        self.assertEqual(preparer.priority_for(100), 10)
        self.assertEqual(preparer.priority_for(20), 20)
        self.assertEqual(preparer.priority_for(5), 30)
        self.assertEqual(preparer.priority_for(0), 40)

    def test_table_existence_check_does_not_create_schema(self):
        con = sqlite3.connect(":memory:")
        try:
            self.assertFalse(preparer.table_exists(con, "v2_name_clusters"))
            self.assertEqual(
                con.execute("select count(*) from sqlite_master where type='table'").fetchone()[0],
                0,
            )
        finally:
            con.close()

    def test_validation_requires_exact_member_partition(self):
        members = [member("E1", "民兵", "Concept"), member("E2", "民兵", "Event")]
        with self.assertRaisesRegex(ValueError, "every cluster member"):
            worker.validate_cluster_result(
                {"assignments": [assignment("E1", "keep", "Concept")]}, members
            )

    def test_short_member_keys_map_exactly_to_internal_ids(self):
        members = [member("LONG-ENTITY-ID-1", "反动武装", "Concept"),
                   member("LONG-ENTITY-ID-2", "反动武装", "Event")]
        result = worker.validate_cluster_result(
            {
                "assignments": [
                    {
                        **assignment("unused", "retype", "SocialGroup"),
                        "member_key": "M001",
                    },
                    {
                        **assignment("unused", "retype", "Concept"),
                        "member_key": "M002",
                    },
                ],
                "identity_groups": [["M001", "M002"]],
            },
            members,
        )
        self.assertEqual(
            [item["entity_id"] for item in result["assignments"]],
            ["LONG-ENTITY-ID-1", "LONG-ENTITY-ID-2"],
        )
        self.assertEqual(
            result["identity_groups"], [["LONG-ENTITY-ID-1", "LONG-ENTITY-ID-2"]]
        )

    def test_invalid_identity_suggestions_are_dropped_without_blocking_types(self):
        members = [member("E1", "昆明保卫战", "Artifact")]
        result = worker.validate_cluster_result(
            {
                "assignments": [assignment("E1", "retype", "Event")],
                "identity_groups": [["E1"]],
            },
            members,
        )
        self.assertEqual(result["assignments"][0]["final_type"], "Event")
        self.assertEqual(result["identity_groups"], [])
        self.assertEqual(result["identity_group_warnings"], ["invalid_identity_group_dropped"])

    def test_ambiguous_and_spatially_contradicted_results_become_unknown(self):
        ambiguous = worker.validate_cluster_result(
            {
                "assignments": [assignment(
                    "E1", "retype", "Organization", explanation="可能是组织，也可能属于概念。"
                )]
            },
            [member("E1", "民兵", "Concept")],
        )
        spatial = worker.validate_cluster_result(
            {"assignments": [assignment("E2", "retype", "Place")]},
            [member("E2", "永新调查", "Event")],
        )
        self.assertEqual(ambiguous["assignments"][0]["decision"], "unknown")
        self.assertEqual(spatial["assignments"][0]["decision"], "unknown")

    def test_two_high_confidence_reviews_accept_same_type(self):
        members = [member("E1", "民兵", "Concept")]
        first = worker.validate_cluster_result(
            {"assignments": [assignment("E1", "keep", "Concept")]}, members
        )
        second = worker.validate_cluster_result(
            {"assignments": [assignment("E1", "keep", "Concept")]}, members
        )
        accepted, unresolved = worker.compare_reviews(first, second, members)
        self.assertEqual(accepted, {"E1": "Concept"})
        self.assertEqual(unresolved, {})

    def test_review_disagreement_and_low_confidence_do_not_apply(self):
        members = [member("E1", "群众", "Event"), member("E2", "委员", "Person")]
        first = {
            "assignments": [
                assignment("E1", "retype", "Concept"),
                assignment("E2", "retype", "Position", 0.94),
            ]
        }
        second = {
            "assignments": [
                assignment("E1", "keep", "Event"),
                assignment("E2", "retype", "Position", 0.99),
            ]
        }
        accepted, unresolved = worker.compare_reviews(first, second, members)
        self.assertEqual(accepted, {})
        self.assertEqual(unresolved["E1"], "review_type_disagreement")
        self.assertEqual(unresolved["E2"], "review_confidence_below_gate")

    def test_specialized_cross_type_requires_separate_topic_audit(self):
        members = [member("E1", "南昌起义", "CreativeWork")]
        first = {"assignments": [assignment("E1", "retype", "Event", 0.99)]}
        second = {"assignments": [assignment("E1", "retype", "Event", 0.99)]}
        accepted, unresolved = worker.compare_reviews(first, second, members)
        self.assertEqual(accepted, {})
        self.assertEqual(
            unresolved["E1"], "specialized_cross_type_requires_topic_audit"
        )

    def test_non_specialized_cross_type_can_pass_double_review(self):
        members = [member("E1", "县工委", "Person")]
        first = {"assignments": [assignment("E1", "retype", "Organization", 0.99)]}
        second = {"assignments": [assignment("E1", "retype", "Organization", 0.99)]}
        accepted, unresolved = worker.compare_reviews(first, second, members)
        self.assertEqual(accepted, {"E1": "Organization"})
        self.assertEqual(unresolved, {})

    def test_social_group_is_an_allowed_cluster_type(self):
        members = [member("E1", "红军战士", "Organization")]
        validated = worker.validate_cluster_result(
            {"assignments": [assignment("E1", "retype", "SocialGroup", 0.99)]},
            members,
        )
        self.assertEqual(validated["assignments"][0]["final_type"], "SocialGroup")

    def test_strict_organization_name_cannot_cross_to_document(self):
        result = worker.validate_cluster_result(
            {"assignments": [assignment("E1", "retype", "Document", 0.99)]},
            [member("E1", "中国人民解放军", "Event")],
        )
        self.assertEqual(result["assignments"][0]["decision"], "unknown")
        self.assertEqual(
            result["assignments"][0]["reason_code"], "strict_name_type_family_conflict"
        )

    def test_generic_collective_cannot_be_person_or_formal_organization(self):
        for final_type in ("Person", "Organization"):
            with self.subTest(final_type=final_type):
                result = worker.validate_cluster_result(
                    {"assignments": [assignment("E1", "retype", final_type, 0.99)]},
                    [member("E1", "民兵", "Concept")],
                )
                self.assertEqual(result["assignments"][0]["decision"], "unknown")
                self.assertEqual(
                    result["assignments"][0]["reason_code"],
                    "generic_collective_requires_social_group_or_concept",
                )

    def test_person_name_collision_cannot_auto_confirm_event(self):
        members = [member("E1", "傅品三", "Person"), member("E2", "傅品三", "Event")]
        first = {
            "assignments": [
                assignment("E1", "keep", "Person", 0.99),
                assignment("E2", "keep", "Event", 0.99),
            ]
        }
        second = {
            "assignments": [
                assignment("E1", "keep", "Person", 0.99),
                assignment("E2", "keep", "Event", 0.99),
            ]
        }
        accepted, unresolved = worker.compare_reviews(first, second, members)
        self.assertEqual(accepted, {"E1": "Person"})
        self.assertEqual(
            unresolved["E2"], "person_name_collision_cannot_auto_confirm_event"
        )

    def test_strict_organization_cannot_downgrade_to_social_group(self):
        for name in ("土改工作组", "红护团"):
            with self.subTest(name=name):
                result = worker.validate_cluster_result(
                    {"assignments": [assignment("E1", "retype", "SocialGroup", 0.99)]},
                    [member("E1", name, "Organization")],
                )
                self.assertEqual(result["assignments"][0]["decision"], "unknown")
                self.assertEqual(
                    result["assignments"][0]["reason_code"],
                    "strict_name_subtype_cannot_be_downgraded",
                )

    def test_known_norm_and_soviet_names_cannot_be_social_groups(self):
        for name in ("三大纪律八项注意", "苏维埃"):
            with self.subTest(name=name):
                result = worker.validate_cluster_result(
                    {"assignments": [assignment("E1", "retype", "SocialGroup", 0.99)]},
                    [member("E1", name, "Person")],
                )
                self.assertEqual(result["assignments"][0]["decision"], "unknown")
                self.assertEqual(
                    result["assignments"][0]["reason_code"],
                    "known_name_semantic_family_conflict",
                )

    def test_polysemous_bare_radio_name_requires_scoped_split(self):
        result = worker.validate_cluster_result(
            {"assignments": [assignment("E1", "retype", "Organization", 0.99)]},
            [member("E1", "电台", "Concept")],
        )
        self.assertEqual(result["assignments"][0]["decision"], "unknown")
        self.assertEqual(
            result["assignments"][0]["reason_code"],
            "polysemous_bare_name_requires_scoped_split",
        )

    def test_generic_party_member_role_cannot_be_concrete_person(self):
        result = worker.validate_cluster_result(
            {"assignments": [assignment("E1", "retype", "Person", 0.99)]},
            [member("E1", "中共党员", "Concept")],
        )
        self.assertEqual(result["assignments"][0]["decision"], "unknown")
        self.assertEqual(
            result["assignments"][0]["reason_code"],
            "generic_role_cannot_be_concrete_person",
        )

    def test_returning_home_corps_remains_an_organization(self):
        result = worker.validate_cluster_result(
            {"assignments": [assignment("E1", "retype", "SocialGroup", 0.99)]},
            [member("E1", "还乡团", "Organization")],
        )
        self.assertEqual(result["assignments"][0]["decision"], "unknown")
        self.assertEqual(
            result["assignments"][0]["reason_code"],
            "strict_name_subtype_cannot_be_downgraded",
        )

    def test_quantified_capture_phrase_cannot_be_single_artifact(self):
        result = worker.validate_cluster_result(
            {"assignments": [assignment("E1", "retype", "Artifact", 0.99)]},
            [member("E1", "缴获长短枪60余支", "Concept")],
        )
        self.assertEqual(result["assignments"][0]["decision"], "unknown")
        self.assertEqual(
            result["assignments"][0]["reason_code"],
            "action_result_phrase_cannot_be_artifact",
        )

    def test_new_structural_guards_block_bad_cluster_accepts(self):
        cases = (
            ("三大队", "Concept", "SocialGroup", "strict_name_subtype_cannot_be_downgraded"),
            (
                "中共徐海蚌特委第一次成立",
                "Event",
                "Organization",
                "strict_name_type_family_conflict",
            ),
            ("日记读后感", "Event", "Person", "strict_name_type_family_conflict"),
            ("瓦寨", "Place", "Organization", "strict_name_type_family_conflict"),
        )
        for name, source_type, final_type, reason in cases:
            with self.subTest(name=name):
                result = worker.validate_cluster_result(
                    {"assignments": [assignment("E1", "retype", final_type, 0.99)]},
                    [member("E1", name, source_type)],
                )
                self.assertEqual(result["assignments"][0]["decision"], "unknown")
                self.assertEqual(result["assignments"][0]["reason_code"], reason)

    def test_person_collision_and_relation_context_guards(self):
        social = worker.validate_cluster_result(
            {
                "assignments": [
                    assignment("E1", "retype", "SocialGroup", 0.99),
                    assignment("E2", "keep", "Person", 0.99),
                ]
            },
            [member("E1", "杨永栋", "Concept"), member("E2", "杨永栋", "Person")],
        )
        social_item = next(item for item in social["assignments"] if item["entity_id"] == "E1")
        self.assertEqual(social_item["decision"], "unknown")
        self.assertEqual(
            social_item["reason_code"],
            "person_name_collision_cannot_auto_confirm_social_group",
        )
        for collective_name in ("学生群体", "妇女", "中农", "八百壮士", "游击队员"):
            with self.subTest(collective_name=collective_name):
                collective = worker.validate_cluster_result(
                    {
                        "assignments": [
                            assignment("E1", "retype", "SocialGroup", 0.99),
                            assignment("E2", "keep", "Person", 0.99),
                        ]
                    },
                    [
                        member("E1", collective_name, "Concept"),
                        member("E2", collective_name, "Person"),
                    ],
                )
                collective_item = next(
                    item for item in collective["assignments"] if item["entity_id"] == "E1"
                )
                self.assertEqual(collective_item["decision"], "retype")
        spatial = worker.validate_cluster_result(
            {"assignments": [assignment("E1", "retype", "Place", 0.99)]},
            [member("E1", "金马", "Person")],
            {"E1": [{"predicate": "stationed_at", "endpoint_role": "subject"}]},
        )
        self.assertEqual(spatial["assignments"][0]["decision"], "unknown")
        self.assertEqual(
            spatial["assignments"][0]["reason_code"],
            "controlled_relation_domain_conflicts_with_spatial_type",
        )


if __name__ == "__main__":
    unittest.main()
