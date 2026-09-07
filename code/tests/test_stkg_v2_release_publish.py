import importlib.util
import tempfile
import unittest
from pathlib import Path


path = Path("scripts/294_publish_stkg_v2.py")
spec = importlib.util.spec_from_file_location("publish_stkg_v2", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class V2ReleasePublishTests(unittest.TestCase):
    def test_test_log_requires_count_and_ok(self):
        with tempfile.TemporaryDirectory() as folder:
            good = Path(folder) / "good.log"
            good.write_text("Ran 169 tests in 1.2s\n\nOK\n", encoding="utf-8")
            bad = Path(folder) / "bad.log"
            bad.write_text("Ran 169 tests in 1.2s\n\nFAILED (failures=1)\n", encoding="utf-8")
            self.assertTrue(module.verify_test_log(good)["passed"])
            self.assertFalse(module.verify_test_log(bad)["passed"])

    def test_staging_guard_rejects_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):
                module.safe_remove_staging(Path(folder) / "unrelated")


if __name__ == "__main__":
    unittest.main()
