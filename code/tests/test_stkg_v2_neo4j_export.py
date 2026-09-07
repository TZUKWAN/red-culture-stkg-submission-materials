import importlib
import unittest


exporter = importlib.import_module("scripts.287_export_stkg_v2_neo4j")


class V2Neo4jExportTests(unittest.TestCase):
    def test_assertion_caption_is_human_readable(self):
        self.assertEqual(exporter.readable_assertion_name("秋收起义", "发生于", "occurred_at", "湖南"),
                         "秋收起义｜发生于｜湖南")
        self.assertEqual(exporter.readable_assertion_name("作品", "", "raw:提及", "人物"),
                         "作品｜提及｜人物")

    def test_node_rows_use_name_as_caption(self):
        row = exporter.make_node_row(
            "Entity", "E1", "作品", ["Entity", "CreativeWork"],
            media_type="电影", media_method="qwen_v2_semantic_classification",
            media_status="completed", media_confidence=0.95,
        )
        self.assertEqual(row[2], "作品")
        self.assertEqual(row[3], "作品")
        self.assertEqual(row[exporter.NODE_HEADER.index("media_type:string")], "电影")
        self.assertEqual(row[exporter.NODE_HEADER.index("media_status:string")], "completed")
        self.assertEqual(row[-1], "Entity;CreativeWork")

    def test_technical_nodes_get_readable_fallback(self):
        row = exporter.make_node_row("Assertion", "F1", "", ["Assertion", "TechnicalNode"])
        self.assertEqual(row[2], "Assertion：F1")

    def test_relationship_ids_are_stable_and_type_sensitive(self):
        first = exporter.relationship_id("SUBJECT_OF", "F1")
        self.assertEqual(first, exporter.relationship_id("SUBJECT_OF", "F1"))
        self.assertNotEqual(first, exporter.relationship_id("OBJECT", "F1"))

    def test_value_facet_projection_has_explicit_relationship_type(self):
        source = __import__("pathlib").Path("scripts/287_export_stkg_v2_neo4j.py").read_text(encoding="utf-8")
        self.assertIn('"STATE_VALUE_FACET"', source)
        self.assertIn('"state_spirit_fact_id"', source)
        self.assertIn('"spirit_value_fact_id"', source)


if __name__ == "__main__":
    unittest.main()
