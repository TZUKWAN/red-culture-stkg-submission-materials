import importlib
import unittest


worker = importlib.import_module("scripts.257_qwen_adjudicate_one_stkg_v2_task")


class V2QwenAdjudicationTests(unittest.TestCase):
    def test_parse_json_object_ignores_thinking_wrapper(self):
        value = worker.parse_json_object('<think>hidden</think> {"decision":"keep"}')
        self.assertEqual(value, {"decision": "keep"})

    def test_different_final_type_normalizes_keep_to_retype(self):
        result = worker.validate_entity_result(
            {"decision": "keep", "final_type": "Event", "confidence": 0.99},
            "Organization",
        )
        self.assertEqual((result[0], result[1]), ("retype", "Event"))

    def test_low_confidence_entity_decision_becomes_unknown(self):
        result = worker.validate_entity_result(
            {"decision": "retype", "final_type": "Organization", "confidence": 0.72},
            "Event",
        )
        self.assertEqual((result[0], result[1]), ("unknown", None))

    def test_same_type_retype_is_normalized_to_keep(self):
        result = worker.validate_entity_result(
            {"decision": "retype", "final_type": "Artifact", "confidence": 0.95},
            "Artifact",
        )
        self.assertEqual((result[0], result[1]), ("keep", "Artifact"))

    def test_parent_type_does_not_downgrade_specific_source_type(self):
        result = worker.validate_entity_result(
            {"decision": "retype", "final_type": "Place", "confidence": 0.95},
            "AdministrativeRegion",
        )
        self.assertEqual((result[0], result[1]), ("keep", "AdministrativeRegion"))

    def test_strict_structure_can_correct_bad_subtype_to_parent(self):
        result = worker.validate_entity_result(
            {"decision": "retype", "final_type": "Organization", "confidence": 0.95},
            "Institution",
            "七师",
        )
        self.assertEqual((result[0], result[1]), ("retype", "Organization"))

    def test_organization_can_be_corrected_to_social_group(self):
        result = worker.validate_entity_result(
            {"decision": "retype", "final_type": "SocialGroup", "confidence": 0.98},
            "Organization",
            "红军战士",
        )
        self.assertEqual((result[0], result[1]), ("retype", "SocialGroup"))

    def test_ambiguous_high_confidence_explanation_becomes_unknown(self):
        result = worker.validate_entity_result(
            {
                "decision": "retype", "final_type": "Organization", "confidence": 0.95,
                "explanation": "该词属于组织或概念范畴。",
            },
            "Concept",
        )
        self.assertEqual((result[0], result[1], result[2]), ("unknown", None, 0.5))

    def test_classifier_review_requires_independent_high_confidence_consensus(self):
        accepted = worker.validate_classifier_review(
            ("retype", "Organization", 0.97, "specific_unit", ""), "Organization"
        )
        disagreement = worker.validate_classifier_review(
            ("keep", "Institution", 0.99, "school", ""), "Organization"
        )
        low_confidence = worker.validate_classifier_review(
            ("retype", "Organization", 0.94, "specific_unit", ""), "Organization"
        )
        self.assertEqual(accepted, (True, "classifier_model_consensus"))
        self.assertEqual(disagreement, (False, "classifier_model_disagreement"))
        self.assertEqual(low_confidence, (False, "model_confidence_below_review_gate"))

    def test_model_second_review_requires_same_final_type(self):
        accepted = worker.validate_model_second_review(
            ("keep", "Concept", 0.98, "generic_group", ""), "Concept"
        )
        disagreement = worker.validate_model_second_review(
            ("retype", "Organization", 0.98, "specific_unit", ""), "Concept"
        )
        weak_prior = worker.validate_model_second_review(
            ("keep", "Concept", 0.99, "generic_group", ""), "Concept", 0.90
        )
        self.assertEqual(accepted, (True, "model_model_consensus"))
        self.assertEqual(disagreement, (False, "model_model_disagreement"))
        self.assertEqual(weak_prior, (False, "prior_model_confidence_below_review_gate"))

    def test_multiple_plausible_types_are_unknown(self):
        result = worker.validate_entity_result(
            {
                "decision": "keep", "final_type": "Place", "confidence": 0.95,
                "explanation": "该名称符合组织或机构定义，两种解释均合理。",
            },
            "Place",
        )
        self.assertEqual((result[0], result[1], result[2]), ("unknown", None, 0.5))

    def test_event_time_result_must_partition_every_candidate(self):
        with self.assertRaisesRegex(ValueError, "partition"):
            worker.validate_event_time_result(
                {"accepted_fact_ids": ["F1"], "rejected_fact_ids": [], "unknown_fact_ids": []},
                {"F1", "F2"},
            )

    def test_event_time_result_lists_must_be_disjoint(self):
        with self.assertRaisesRegex(ValueError, "disjoint"):
            worker.validate_event_time_result(
                {
                    "accepted_fact_ids": ["F1"],
                    "rejected_fact_ids": ["F1"],
                    "unknown_fact_ids": [],
                },
                {"F1"},
            )

    def test_low_confidence_event_time_partition_becomes_all_unknown(self):
        accepted, rejected, unknown, *_ = worker.validate_event_time_result(
            {
                "accepted_fact_ids": ["F1"], "rejected_fact_ids": ["F2"],
                "unknown_fact_ids": [], "confidence": 0.6,
            },
            {"F1", "F2"},
        )
        self.assertEqual(accepted, [])
        self.assertEqual(rejected, [])
        self.assertEqual(unknown, ["F1", "F2"])


if __name__ == "__main__":
    unittest.main()
