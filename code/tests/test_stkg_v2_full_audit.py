import importlib.util
import unittest
from pathlib import Path


path = Path("scripts/293_audit_stkg_v2_full.py")
spec = importlib.util.spec_from_file_location("audit_stkg_v2_full", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class V2FullAuditTests(unittest.TestCase):
    def test_canonical_time_label_accepts_precision_preserving_family(self):
        for label in ("1941年", "1943年8月", "1934年10月-1936年10月", "1996年-1999年"):
            with self.subTest(label=label):
                self.assertTrue(module.canonical_time_label(label))

    def test_canonical_time_label_rejects_mixed_or_false_precision(self):
        for label in (None, "一九四一年", "1943年2月15日", "1943-02", "1943年13月"):
            with self.subTest(label=label):
                self.assertFalse(module.canonical_time_label(label))

    def test_relation_contract_is_hierarchy_aware(self):
        self.assertTrue(module.relation_compatible("occurred_at", "Event", "AdministrativeRegion"))
        self.assertTrue(module.relation_compatible("participated_in", "Institution", "Event"))
        self.assertFalse(module.relation_compatible("occurred_at", "Organization", "Place"))


if __name__ == "__main__":
    unittest.main()
