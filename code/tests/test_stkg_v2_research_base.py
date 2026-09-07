import importlib
import unittest


base = importlib.import_module("scripts.284_materialize_stkg_v2_research_base")


class ResearchBaseTests(unittest.TestCase):
    def test_semantic_families_are_research_facing(self):
        self.assertEqual(base.semantic_family("AdministrativeRegion"), "SpatialEntity")
        self.assertEqual(base.semantic_family("Institution"), "CollectiveEntity")
        self.assertEqual(base.semantic_family("Spirit"), "ConceptualEntity")
        self.assertEqual(base.semantic_family("CreativeWork"), "InformationObject")
        self.assertEqual(base.semantic_family("Event"), "Event")

    def test_relation_contract_accepts_v2_subtypes(self):
        self.assertTrue(base.relation_domain_range_pass_v2("occurred_at", "Event", "AdministrativeRegion"))
        self.assertTrue(base.relation_domain_range_pass_v2("occurred_at", "Event", "CulturalSite"))
        self.assertTrue(base.relation_domain_range_pass_v2("participated_in", "Institution", "Event"))

    def test_relation_contract_rejects_incompatible_endpoints(self):
        self.assertFalse(base.relation_domain_range_pass_v2("occurred_at", "Event", "Institution"))
        self.assertFalse(base.relation_domain_range_pass_v2("has_value_facet", "Event", "Spirit"))
        self.assertFalse(base.relation_domain_range_pass_v2("raw:相关", "Person", "Event"))

    def test_final_identity_type_closes_stale_event_roles(self):
        self.assertEqual(
            base.close_time_scope_after_identity(
                "event_occurrence", "O1", "occurred_at", "1949-01-01",
                "O1", "Organization", "P1", "Place"
            ),
            ("relation_validity", None),
        )
        self.assertEqual(
            base.close_space_scope_after_identity(
                "event_location", "O1", "occurred_at", "P1",
                "O1", "Organization", "P1", "Place"
            ),
            ("relation_location", None),
        )

    def test_final_identity_type_preserves_valid_event_roles(self):
        self.assertEqual(
            base.close_time_scope_after_identity(
                "event_occurrence", "E1", "occurred_at", "1927-08-01",
                "E1", "Event", "P1", "AdministrativeRegion"
            ),
            ("event_occurrence", "E1"),
        )
        self.assertEqual(
            base.close_space_scope_after_identity(
                "event_location", "E1", "occurred_at", "P1",
                "E1", "Event", "P1", "AdministrativeRegion"
            ),
            ("event_location", "E1"),
        )

    def test_final_identity_type_closes_stale_biographical_owner(self):
        self.assertEqual(
            base.close_time_scope_after_identity(
                "biographical", "O1", "raw:发生于", "1935-01-01",
                "O1", "Organization", "P1", "Place"
            ),
            ("context_time", None),
        )

    def test_final_closure_never_promotes_existing_context_decisions(self):
        self.assertEqual(
            base.close_time_scope_after_identity(
                "context_time", None, "occurred_at", "1927-08-01",
                "E1", "Event", "P1", "Place"
            ),
            ("context_time", None),
        )
        self.assertEqual(
            base.close_space_scope_after_identity(
                "context_location", None, "raw:发生于", "P1",
                "E1", "Event", "P1", "Place"
            ),
            ("context_location", None),
        )


if __name__ == "__main__":
    unittest.main()
