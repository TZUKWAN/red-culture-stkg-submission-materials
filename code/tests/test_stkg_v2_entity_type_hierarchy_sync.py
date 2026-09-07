import importlib
import json
import unittest


sync = importlib.import_module("scripts.271_sync_stkg_v2_entity_type_hierarchy")


class V2EntityTypeHierarchySyncTests(unittest.TestCase):
    def test_effective_type_drives_family_and_facets(self):
        family, facets = sync.expected_metadata("Event", "Organization")
        self.assertEqual(family, "CollectiveAgent")
        self.assertEqual(json.loads(facets), ["Organization", "SocialGroup", "CollectiveAgent"])

        family, facets = sync.expected_metadata("Place", "AdministrativeRegion")
        self.assertEqual(family, "SpatialEntity")
        self.assertEqual(json.loads(facets), ["AdministrativeRegion", "Place", "SpatialEntity"])

    def test_null_semantic_type_uses_source_type(self):
        family, facets = sync.expected_metadata("Institution", None)
        self.assertEqual(family, "CollectiveAgent")
        self.assertEqual(
            json.loads(facets),
            ["Institution", "Organization", "SocialGroup", "CollectiveAgent"],
        )


if __name__ == "__main__":
    unittest.main()
