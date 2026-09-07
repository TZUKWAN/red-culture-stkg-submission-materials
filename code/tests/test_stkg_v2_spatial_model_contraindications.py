import importlib
import unittest


semantics = importlib.import_module("scripts.stkg_v2_semantics")
audit = importlib.import_module("scripts.272_audit_stkg_v2_spatial_model_contraindications")


class V2SpatialModelContraindicationTests(unittest.TestCase):
    def test_action_and_composite_names_block_spatial_model_types(self):
        self.assertEqual(
            semantics.spatial_model_contraindication("过草地", "Place"),
            "strict_nonspatial_name_conflicts_with_spatial_type",
        )
        self.assertEqual(
            semantics.spatial_model_contraindication("永新调查", "Place"),
            "action_nominalization_cannot_be_accepted_as_place",
        )
        self.assertEqual(
            semantics.spatial_model_contraindication("乐安、宜黄", "AdministrativeRegion"),
            "composite_place_cannot_be_single_administrative_region",
        )
        self.assertEqual(
            semantics.spatial_model_contraindication("赣南", "AdministrativeRegion"),
            "administrative_region_requires_explicit_admin_structure",
        )
        self.assertEqual(
            semantics.spatial_model_contraindication("汉口英租界", "AdministrativeRegion"),
            "",
        )
        self.assertEqual(semantics.spatial_model_contraindication("武汉", "Place"), "")

    def test_only_unambiguous_contraindications_get_rule_corrections(self):
        self.assertEqual(audit.correction_for("过草地", "Place"), "Event")
        self.assertEqual(audit.correction_for("乐安、宜黄", "AdministrativeRegion"), "Place")
        self.assertIsNone(audit.correction_for("永新调查", "Place"))

    def test_historical_concession_is_administrative_region(self):
        self.assertEqual(
            semantics.strict_v2_entity_type_hint("汉口英租界", "Place"),
            "AdministrativeRegion",
        )


if __name__ == "__main__":
    unittest.main()
