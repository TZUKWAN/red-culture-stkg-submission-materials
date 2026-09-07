import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


path = Path("scripts/289_enrich_stkg_v2_creative_media.py")
spec = importlib.util.spec_from_file_location("stkg_v2_creative_media", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class StkgV2CreativeMediaTests(unittest.TestCase):
    def test_validate_model_result_enforces_vocabulary_and_threshold(self):
        accepted = module.validate_model_result({
            "media_type": "歌曲", "confidence": 0.96,
            "reason_code": "title_cue", "explanation": "名称包含进行曲。",
        })
        self.assertEqual(accepted[0], "歌曲")
        conservative = module.validate_model_result({
            "media_type": "小说", "confidence": 0.80,
            "reason_code": "weak_context", "explanation": "上下文较弱。",
        })
        self.assertEqual(conservative[0], "未知")
        with self.assertRaises(ValueError):
            module.validate_model_result({
                "media_type": "短视频", "confidence": 0.99,
                "reason_code": "bad", "explanation": "不在词表。",
            })

    def test_prompt_is_one_entity_and_contains_controlled_vocabulary(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "task.sqlite"
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            con.executescript(module.SCHEMA)
            con.execute(
                "insert into creative_media_tasks values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "E1", "测试作品", None, "qwen_v2_semantic_classification", "pending",
                    None, 0, module.MODEL, module.PROMPT_VERSION, None, None, "[]", "[]",
                    json.dumps({"relation_context": []}), None, None, "2026-01-01T00:00:00+08:00",
                ),
            )
            task = con.execute("select * from creative_media_tasks").fetchone()
            prompt = json.loads(module.build_prompt(task))
            con.close()
        self.assertEqual(prompt["entity_id"], "E1")
        self.assertIn("电影", prompt["allowed_media_types"])
        self.assertIn("散文", prompt["allowed_media_types"])
        self.assertIn("未知", prompt["allowed_media_types"])

    def test_database_validation_rejects_nonfinal_task(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(module.SCHEMA)
        con.execute(
            "insert into creative_media_tasks values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "E1", "测试作品", None, "qwen_v2_semantic_classification", "pending",
                None, 0, module.MODEL, module.PROMPT_VERSION, None, None, "[]", "[]", "{}",
                None, None, "2026-01-01T00:00:00+08:00",
            ),
        )
        _, failures = module.validate_database(con, 1)
        con.close()
        self.assertTrue(any("nonfinal_count" in item for item in failures))


if __name__ == "__main__":
    unittest.main()
