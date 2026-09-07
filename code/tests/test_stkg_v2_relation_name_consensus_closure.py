from __future__ import annotations

import importlib
import sqlite3
import unittest


closure = importlib.import_module("scripts.280_close_stkg_v2_relation_and_name_consensus")


def row(name: str, source_type: str) -> sqlite3.Row:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    value = con.execute(
        "select ? canonical_name,? source_entity_type", (name, source_type)
    ).fetchone()
    con.close()
    return value


class V2RelationNameConsensusClosureTests(unittest.TestCase):
    def test_direct_relation_roles_resolve_known_semantics(self):
        cases = (
            (
                "海瑞",
                "Person",
                [{"predicate": "depicts", "endpoint_role": "object"}],
                {"Person", "CreativeWork"},
                "Person",
            ),
            (
                "杨永栋",
                "Concept",
                [{"predicate": "raw:活捉", "endpoint_role": "object"}],
                {"Concept", "Person"},
                "Person",
            ),
            (
                "金马",
                "Person",
                [{"predicate": "stationed_at", "endpoint_role": "subject"}],
                {"Person", "Place"},
                "Person",
            ),
            ("群众力量", "Organization", [], {"Organization", "Spirit"}, "Concept"),
        )
        for name, source_type, contexts, sibling_types, expected in cases:
            with self.subTest(name=name):
                resolution = closure.direct_relation_resolution(
                    row(name, source_type), contexts, sibling_types
                )
                self.assertIsNotNone(resolution)
                self.assertEqual(resolution[0], expected)

    def test_spatial_name_and_repeated_spatial_roles_block_person_inference(self):
        self.assertIsNone(
            closure.direct_relation_resolution(
                row("三元寨", "Person"),
                [{"predicate": "fought_at", "endpoint_role": "subject"}],
                {"Person", "Place"},
            )
        )
        self.assertIsNone(
            closure.direct_relation_resolution(
                row("安宁", "Person"),
                [
                    {"predicate": "worked_at", "endpoint_role": "subject"},
                    {"predicate": "raw:发生地", "endpoint_role": "object"},
                    {"predicate": "raw:active_at", "endpoint_role": "object"},
                ],
                {"Person", "Place"},
            )
        )
        self.assertIsNone(
            closure.direct_relation_resolution(
                row("湘赣", "Person"),
                [{"predicate": "participated_in", "endpoint_role": "subject"}],
                {"Person", "Place"},
            )
        )

    def test_proper_person_name_filter_rejects_categories(self):
        self.assertTrue(closure.is_proper_person_name("杨永栋"))
        self.assertTrue(closure.is_proper_person_name("李健"))
        self.assertFalse(closure.is_proper_person_name("教师"))
        self.assertFalse(closure.is_proper_person_name("游击队员"))


if __name__ == "__main__":
    unittest.main()
