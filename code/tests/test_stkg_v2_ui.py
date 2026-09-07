import importlib.util
import unittest
from pathlib import Path


path = Path("stkg_ui_v2/app.py")
spec = importlib.util.spec_from_file_location("stkg_v2_ui", path)
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)


class V2UiTests(unittest.TestCase):
    def test_properties_json_is_parsed_without_failure(self):
        self.assertEqual(ui.parse_properties_json('{"aliases":["毛润之"]}'), {"aliases": ["毛润之"]})
        self.assertEqual(ui.parse_properties_json("bad-json"), {})
        self.assertEqual(ui.parse_properties_json(None), {})

    def test_graph_merge_removes_duplicates_and_dangling_edges(self):
        nodes = [{"id": "A", "label": "甲"}, {"id": "A", "label": "甲"}, {"id": "B", "label": "乙"}]
        edges = [{"id": "R1", "source": "A", "target": "B"}, {"id": "R2", "source": "A", "target": "C"}]
        result = ui.merge_graph(nodes, edges)
        self.assertEqual(len(result["nodes"]), 2)
        self.assertEqual([edge["id"] for edge in result["edges"]], ["R1"])

    def test_frontend_only_opens_entity_nodes(self):
        script = Path("stkg_ui_v2/static/app.js").read_text(encoding="utf-8")
        self.assertIn("data.kind === 'Entity' || data.entityType", script)

    def test_hidden_elements_cannot_be_overridden_by_component_styles(self):
        stylesheet = Path("stkg_ui_v2/static/styles.css").read_text(encoding="utf-8")
        self.assertIn("[hidden] { display: none !important; }", stylesheet)

    def test_creative_media_is_exposed_in_ui_contract(self):
        app_source = Path("stkg_ui_v2/app.py").read_text(encoding="utf-8")
        html = Path("stkg_ui_v2/static/index.html").read_text(encoding="utf-8")
        javascript = Path("stkg_ui_v2/static/app.js").read_text(encoding="utf-8")
        self.assertIn('"mediaTypes": media_types', app_source)
        self.assertIn("focus.media_type=$media", app_source)
        self.assertIn('id="mediaSelect"', html)
        self.assertIn("['媒介类型', displayValue(props.media_type)]", javascript)


if __name__ == "__main__":
    unittest.main()
