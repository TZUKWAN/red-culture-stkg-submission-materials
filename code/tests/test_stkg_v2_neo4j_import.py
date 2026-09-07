import importlib.util
import unittest
from pathlib import Path


path = Path("scripts/291_import_stkg_v2_neo4j.py")
spec = importlib.util.spec_from_file_location("stkg_v2_neo4j_import", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StkgV2Neo4jImportTests(unittest.TestCase):
    def test_schema_includes_all_unique_labels_and_media_index(self):
        text = "\n".join(module.SCHEMA_QUERIES)
        for label in module.UNIQUE_LABELS:
            self.assertIn(f"FOR (n:{label}) REQUIRE n.stable_id IS UNIQUE", text)
        self.assertIn("creative_work_media_v2", text)
        self.assertIn("entity_name_fulltext_v2", text)

    def test_final_and_candidate_ports_do_not_overlap(self):
        self.assertNotEqual(module.TEMP_HTTP_PORT, module.FINAL_HTTP_PORT)
        self.assertNotEqual(module.TEMP_BOLT_PORT, module.FINAL_BOLT_PORT)

    def test_reuse_mode_is_explicit(self):
        source = path.read_text(encoding="utf-8")
        self.assertIn("--reuse-imported-volume", source)
        self.assertIn("requested imported candidate volume is absent", source)

    def test_volume_token_uses_nodes_and_relationships(self):
        source = path.read_text(encoding="utf-8")
        self.assertIn('export["files"]["nodes.csv"]["sha256"] + export["files"]["relationships.csv"]["sha256"]', source)

    def test_count_queries_use_explicit_alias(self):
        source = path.read_text(encoding="utf-8")
        self.assertNotIn("RETURN count(n) value", source)
        self.assertNotIn("RETURN count(r) value", source)
        self.assertIn("RETURN count(n) AS value", source)
        self.assertIn("count(n) AS creative_work_nodes", source)
        self.assertIn("count(n.media_type) AS media_populated", source)
        self.assertIn("END) AS media_unknown", source)
        self.assertIn("END) AS media_qwen_v2", source)


if __name__ == "__main__":
    unittest.main()
