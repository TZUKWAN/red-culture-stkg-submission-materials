import importlib
import json
import unittest
from pathlib import Path


builder = importlib.import_module("scripts.285_build_stkg_v2_event_culture")


class V2EventCultureTests(unittest.TestCase):
    def test_v2_event_roles_accept_safe_subtypes(self):
        self.assertTrue(builder.counterpart_allowed("AdministrativeRegion", json.dumps(["Place"])))
        self.assertTrue(builder.counterpart_allowed("CulturalSite", json.dumps(["Place"])))
        self.assertTrue(builder.counterpart_allowed("Institution", json.dumps(["Organization"])))

    def test_v2_event_roles_reject_incompatible_types(self):
        self.assertFalse(builder.counterpart_allowed("Institution", json.dumps(["Place"])))
        self.assertFalse(builder.counterpart_allowed("Event", json.dumps(["Person", "Organization"])))

    def test_direct_event_support_requires_strict_semantics(self):
        self.assertTrue(builder.direct_support_eligible("Event", "strict_semantic"))
        self.assertFalse(builder.direct_support_eligible("Event", "contextual"))
        self.assertTrue(builder.direct_support_eligible("CreativeWork", "contextual"))
        self.assertFalse(builder.direct_support_eligible("CreativeWork", "unresolved"))

    def test_only_adjudicated_or_consensus_time_is_trusted(self):
        self.assertTrue(builder.occurrence_time_is_trusted("model_adjudicated"))
        self.assertTrue(builder.occurrence_time_is_trusted("source_consensus"))
        self.assertFalse(builder.occurrence_time_is_trusted("asserted_candidate"))

    def test_frozen_mappings_satisfy_v2_guards(self):
        event = builder.load_yaml(Path("stkg/schema/event_role_mapping_v1.yaml"))
        culture = builder.load_yaml(Path("stkg/schema/culture_form_mapping_v1.yaml"))
        self.assertEqual(builder.validate_mappings(event, culture), [])


if __name__ == "__main__":
    unittest.main()
