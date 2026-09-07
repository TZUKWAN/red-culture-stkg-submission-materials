import importlib
import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path


closure = importlib.import_module("scripts.283_close_stkg_v2_canonical_identity_and_space")


class CanonicalIdentitySpaceTests(unittest.TestCase):
    def test_representative_prefers_primary_member_rich_entity(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.execute("create table x(entity_id,semantic_entity_type,source_entity_type,member_count)")
        con.executemany(
            "insert into x values(?,?,?,?)",
            [
                ("IENT-a", "AdministrativeRegion", "AdministrativeRegion", 3),
                ("ITOPIC-b", "AdministrativeRegion", "Place", 1),
            ],
        )
        rows = con.execute("select * from x").fetchall()
        selected = closure.representative(rows, Counter({"ITOPIC-b": 100}), True)
        self.assertEqual(selected["entity_id"], "IENT-a")
        con.close()

    def test_short_region_label_is_precision_preserving(self):
        self.assertEqual(closure.short_region_label("重庆市"), "重庆")
        self.assertEqual(closure.short_region_label("广西壮族自治区"), "广西")
        self.assertEqual(closure.short_region_label("井冈山"), "井冈山")

    def test_compound_site_names_are_guarded(self):
        self.assertTrue(any(value in "红色遗址/苏维埃政府旧址" for value in closure.COMPOUND_SEPARATORS))


if __name__ == "__main__":
    unittest.main()
