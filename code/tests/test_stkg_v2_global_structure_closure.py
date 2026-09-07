from __future__ import annotations

import importlib
import sqlite3
import unittest


closure = importlib.import_module("scripts.279_close_stkg_v2_global_structure_constraints")


def row(
    name: str,
    source_type: str,
    semantic_type: str | None,
    status: str = "auto_accepted",
) -> sqlite3.Row:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    value = con.execute(
        "select ? canonical_name,? source_entity_type,? semantic_entity_type,? semantic_status",
        (name, source_type, semantic_type, status),
    ).fetchone()
    con.close()
    return value


class V2GlobalStructureClosureTests(unittest.TestCase):
    def test_independent_cross_type_structures_are_repaired(self):
        cases = (
            ("庐江区委", "Place", "Place", "Organization"),
            ("威远县界牌小学", "Concept", "Concept", "Institution"),
            ("淮阴县县委成立", "Organization", "Organization", "Event"),
            ("罢市救亡史", "Event", "Event", "Document"),
            ("汉口德租界", "Place", "Place", "AdministrativeRegion"),
        )
        for name, source_type, semantic_type, expected in cases:
            with self.subTest(name=name):
                resolution = closure.choose_global_resolution(
                    row(name, source_type, semantic_type)
                )
                self.assertIsNotNone(resolution)
                self.assertEqual(resolution[0], expected)

    def test_source_restoration_and_person_titles_are_excluded(self):
        self.assertIsNone(
            closure.choose_global_resolution(
                row("某日报", "Document", "Organization")
            )
        )
        self.assertIsNone(
            closure.choose_global_resolution(row("刘星副校长", "Person", "Person"))
        )
        self.assertIsNone(
            closure.choose_global_resolution(row("杨队长", "Concept", "Person"))
        )
        self.assertIsNone(
            closure.choose_global_resolution(row("纪大纲", "Person", "Person"))
        )
        self.assertIsNone(
            closure.choose_global_resolution(row("中小学", "Concept", "Concept"))
        )
        self.assertIsNone(
            closure.choose_global_resolution(
                row("文委会工作与平民夜校", "Event", "Organization")
            )
        )
        for composite_position in (
            "军管会委员及各委员会正副主任",
            "张惟清等区委书记",
            "任区委书记",
            "渡江南下任县委书记",
        ):
            with self.subTest(composite_position=composite_position):
                self.assertIsNone(
                    closure.choose_global_resolution(
                        row(composite_position, "Concept", "Concept")
                    )
                )

    def test_matching_current_type_is_idempotent(self):
        self.assertIsNone(
            closure.choose_global_resolution(row("庐江区委", "Place", "Organization"))
        )


if __name__ == "__main__":
    unittest.main()
