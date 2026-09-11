# -*- coding: utf-8 -*-
"""test_final_tiering.py — build_final_tiering 的单元测试（无 LLM、无 DB、无外部 IO）。

运行：python -m unittest code.tests.test_final_tiering -v
（工作目录 = final_submission_v3_1）

覆盖：
1. wilson_ci 统计正确性；
2. rule_matches 特征约束匹配（max_gap / min_name_len_min / stratum_family_in / 布尔位）；
3. dev_tier 的 §5.3 冻结映射（PARTIAL predicate 表、五个 decision 档）；
4. compute_row_features 的双名命中/间距/谓词线索（中文合成文本）；
5. build_predicate_policy 的 ≥70% FULL 阈值与最小样本门槛；
6. assign_all 端到端分派（D 规约 / 安全规则 / DEV LLM / 队列 LLM / 保守持留）；
7. TIERING_COLUMNS 固定列序契约。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

V3_1 = Path(__file__).resolve().parents[2]
for p in (str(V3_1 / "code" / "experiment_pipelines"),):
    if p not in sys.path:
        sys.path.insert(0, p)

import build_final_tiering as bt  # noqa: E402


class TestWilsonCI(unittest.TestCase):
    def test_basic_range_and_point(self):
        lo, hi = bt.wilson_ci(95, 100)
        self.assertTrue(0.885 < lo < 0.91)      # ~0.895
        self.assertTrue(0.96 < hi < 0.99)
        lo0, hi0 = bt.wilson_ci(0, 0)
        self.assertEqual((lo0, hi0), (0.0, 0.0))

    def test_wilson_lb_threshold_semantics(self):
        # 95/100 的 Wilson 下界应 < 0.90 → 不满足 ≥90% 下界的安全标准
        lo, _ = bt.wilson_ci(95, 100)
        self.assertLess(lo, 0.90)
        # 200/200 → 下界逼近 1、上界=1
        lo2, hi2 = bt.wilson_ci(200, 200)
        self.assertEqual(hi2, 1.0)
        self.assertGreater(lo2, 0.97)


class TestRuleMatches(unittest.TestCase):
    FEAT = {"both_hit": True, "both_hit_close": True, "pred_cue": True,
            "pred_cue_between": True, "both_gap": 55, "min_name_len": 3,
            "stratum_family": "aligned"}

    def test_bool_flags_and_gap(self):
        req = {"both_hit": True, "max_gap": 80}
        self.assertTrue(bt.rule_matches(self.FEAT, req))
        self.assertFalse(bt.rule_matches(self.FEAT, {"both_hit": False}))
        self.assertFalse(bt.rule_matches({**self.FEAT, "both_gap": 90},
                                         {"max_gap": 80}))
        self.assertFalse(bt.rule_matches({**self.FEAT, "both_gap": -1},
                                         {"max_gap": 80}))

    def test_min_name_len_and_family(self):
        self.assertTrue(bt.rule_matches(self.FEAT, {"min_name_len_min": 3}))
        self.assertFalse(bt.rule_matches({**self.FEAT, "min_name_len": 2},
                                         {"min_name_len_min": 3}))
        self.assertTrue(bt.rule_matches(self.FEAT,
                                        {"stratum_family_in": ["aligned", "recovery_B"]}))
        self.assertFalse(bt.rule_matches(self.FEAT,
                                         {"stratum_family_in": ["recovery_B"]}))


class TestDevTier(unittest.TestCase):
    POLICY = {"predicate_policy_table": {
        "participated_in": {"partial_map_to": "strict"},
        "led": {"partial_map_to": "contextual"},
    }}

    def test_full_mapping(self):
        self.assertEqual(bt.dev_tier("FULLY_SUPPORTED", "led", self.POLICY), "STRICT")

    def test_partial_uses_predicate_table(self):
        self.assertEqual(bt.dev_tier("PARTIALLY_SUPPORTED", "participated_in",
                                     self.POLICY), "STRICT")
        self.assertEqual(bt.dev_tier("PARTIALLY_SUPPORTED", "led", self.POLICY),
                         "CONTEXTUAL")
        # 未入表 predicate 默认 contextual
        self.assertEqual(bt.dev_tier("PARTIALLY_SUPPORTED", "influenced", self.POLICY),
                         "CONTEXTUAL")

    def test_negative_and_hold(self):
        self.assertEqual(bt.dev_tier("UNSUPPORTED", "led", self.POLICY), "UNRESOLVED")
        self.assertEqual(bt.dev_tier("CONTRADICTED", "led", self.POLICY), "UNRESOLVED")
        self.assertEqual(bt.dev_tier("INSUFFICIENT", "led", self.POLICY), "CONTEXTUAL")
        self.assertEqual(bt.dev_tier("NO_EVIDENCE", "led", self.POLICY), "UNRESOLVED")
        self.assertEqual(bt.dev_tier("NOT_EVALUATED", "led", self.POLICY), "CONTEXTUAL")


class TestComputeRowFeatures(unittest.TestCase):
    def test_both_hit_gap_and_cue_between(self):
        row = {"subject_name": "张三", "object_name": "八路军", "predicate": "participated_in"}
        text = "张三于一九三八年参加八路军，随军转战冀中。"
        f = bt.compute_row_features(row, text, 1)
        self.assertEqual(f["both_hit"], 1)
        self.assertEqual(f["pred_cue"], 1)
        self.assertEqual(f["pred_cue_between"], 1)   # “参加”位于两名字之间
        self.assertGreaterEqual(f["both_gap"], 0)
        self.assertEqual(f["min_name_len"], 2)

    def test_no_object_hit(self):
        row = {"subject_name": "李四", "object_name": "太行军区", "predicate": "active_at"}
        f = bt.compute_row_features(row, "李四在村里活动。", 1)
        self.assertEqual(f["both_hit"], 0)
        self.assertEqual(f["both_hit_close"], 0)
        self.assertEqual(f["both_gap"], -1)
        self.assertEqual(f["pred_cue"], 1)           # “活动”出现但未夹在双名之间

    def test_empty_evidence(self):
        row = {"subject_name": "王五", "object_name": "延安", "predicate": "active_at"}
        f = bt.compute_row_features(row, "", 0)
        self.assertEqual(f["evidence_empty"], 1)
        self.assertEqual(f["both_hit"], 0)


class TestPredicatePolicy(unittest.TestCase):
    def test_share_threshold_and_min_n(self):
        dev = {}
        for i in range(8):     # participated_in: 8 FULL, 2 PARTIAL → 80% ≥70%，n=10
            dev[f"a{i}"] = {"decision": "FULLY_SUPPORTED", "predicate": "participated_in"}
        for i in range(2):
            dev[f"b{i}"] = {"decision": "PARTIALLY_SUPPORTED", "predicate": "participated_in"}
        for i in range(5):     # led: 全 FULL 但 n=5 < 10 → contextual
            dev[f"c{i}"] = {"decision": "FULLY_SUPPORTED", "predicate": "led"}
        table = bt.build_predicate_policy(dev)
        self.assertEqual(table["participated_in"]["partial_map_to"], "strict")
        self.assertEqual(table["led"]["partial_map_to"], "contextual")
        self.assertAlmostEqual(table["participated_in"]["full_share"], 0.8, places=3)


def _mini_world():
    """合成小宇宙：2 D / 1 规则命中 / 1 DEV LLM / 1 队列 LLM / 1 持留。"""
    align = {
        "F1": {"fact_id": "F1", "bucket": "no_evidence", "risk_tier": "A",
               "subject_name": "甲", "object_name": "乙", "predicate": "active_at"},
        "F2": {"fact_id": "F2", "bucket": "no_evidence", "risk_tier": "A",
               "subject_name": "丙", "object_name": "丁", "predicate": "led"},
        "F3": {"fact_id": "F3", "bucket": "aligned", "risk_tier": "A",
               "subject_name": "戊", "object_name": "己", "predicate": "led"},
        "F4": {"fact_id": "F4", "bucket": "mismatch_with_evidence", "risk_tier": "B",
               "subject_name": "庚", "object_name": "辛", "predicate": "led"},
        "F5": {"fact_id": "F5", "bucket": "aligned", "risk_tier": "A",
               "subject_name": "壬", "object_name": "癸", "predicate": "led"},
        "F6": {"fact_id": "F6", "bucket": "aligned", "risk_tier": "A",
               "subject_name": "子", "object_name": "丑", "predicate": "led"},
    }
    recov = {
        "F1": {"recovery_class": "D"},
        "F2": {"recovery_class": "B"},
    }
    feats = {
        "F3": {"both_hit": True, "both_hit_close": True, "pred_cue": True,
               "pred_cue_between": True, "both_gap": 30, "min_name_len": 3,
               "stratum_family": "aligned"},
        "F4": {"both_hit": False, "both_hit_close": False, "pred_cue": False,
               "pred_cue_between": False, "both_gap": -1, "min_name_len": 2,
               "stratum_family": "mismatch_with_evidence"},
        "F5": {"both_hit": False, "both_hit_close": False, "pred_cue": False,
               "pred_cue_between": False, "both_gap": -1, "min_name_len": 2,
               "stratum_family": "aligned"},
        "F6": {"both_hit": False, "both_hit_close": False, "pred_cue": False,
               "pred_cue_between": False, "both_gap": -1, "min_name_len": 2,
               "stratum_family": "aligned"},
    }
    policy = {"safe_rules": [{"name": "RX", "requires": {
        "both_hit": True, "both_hit_close": True, "pred_cue_between": True}}],
        "predicate_policy_table": {"led": {"partial_map_to": "contextual"}}}
    dev = {"F4": {"decision": "UNSUPPORTED", "stratum": "mismatch_with_evidence",
                  "predicate": "led"}}
    queue = {"F5": {"decision": "FULLY_SUPPORTED", "stratum": "aligned",
                    "predicate": "led"},
             "F2": {"decision": "PARTIALLY_SUPPORTED", "stratum": "recovery_B",
                    "predicate": "led"}}
    return align, recov, feats, policy, dev, queue


class TestAssignAll(unittest.TestCase):
    def setUp(self):
        self.align, self.recov, self.feats, self.policy, self.dev, self.queue = \
            _mini_world()
        self.assigned = bt.assign_all(self.align, self.recov, self.feats,
                                      self.policy, self.dev, self.queue)

    def test_recovery_d_rule(self):
        r = self.assigned["F1"]
        self.assertEqual(r["gate_method"], "rule")
        self.assertEqual(r["semantic_support"], "NO_EVIDENCE")
        self.assertEqual(r["final_tier"], "UNRESOLVED")
        self.assertEqual(r["evidence_localizable"], "False")

    def test_safe_rule_strict(self):
        r = self.assigned["F3"]
        self.assertEqual(r["gate_method"], "rule")
        self.assertEqual(r["semantic_support"], "SAFE_RULE_FULL")
        self.assertEqual(r["final_tier"], "STRICT")
        self.assertEqual(r["evidence_localizable"], "True")

    def test_dev_and_queue_llm(self):
        r4 = self.assigned["F4"]
        self.assertEqual((r4["gate_method"], r4["final_tier"]), ("llm", "UNRESOLVED"))
        r5 = self.assigned["F5"]
        self.assertEqual((r5["gate_method"], r5["semantic_support"],
                          r5["final_tier"]), ("llm", "FULLY_SUPPORTED", "STRICT"))

    def test_queue_partial_uses_predicate_table(self):
        # F2: 队列 PARTIAL + predicate "led" 在表中为 contextual → CONTEXTUAL
        r2 = self.assigned["F2"]
        self.assertEqual((r2["gate_method"], r2["semantic_support"],
                          r2["final_tier"]),
                         ("llm", "PARTIALLY_SUPPORTED", "CONTEXTUAL"))

    def test_pending_hold(self):
        r = self.assigned["F6"]
        self.assertEqual(r["gate_method"], "none")
        self.assertEqual(r["semantic_support"], "NOT_EVALUATED")
        self.assertEqual(r["final_tier"], "CONTEXTUAL")

    def test_old_tier_carried(self):
        self.assertEqual(self.assigned["F4"]["old_tier"], "B")

    def test_measured_excludes_hold(self):
        measured = [r for r in self.assigned.values()
                    if r["gate_method"] in ("rule", "llm")]
        self.assertEqual(len(measured), 5)
        holds = [r for r in self.assigned.values() if r["gate_method"] == "none"]
        self.assertEqual(len(holds), 1)


class TestContract(unittest.TestCase):
    def test_tiering_columns_exact(self):
        self.assertEqual(bt.TIERING_COLUMNS,
                         ["fact_id", "old_tier", "bucket", "recovery_class",
                          "evidence_localizable", "gate_method",
                          "semantic_support", "final_tier"])

    def test_tier_values_closed_vocabulary(self):
        for t in bt.TIER_OF_DECISION.values():
            self.assertIn(t, {"STRICT", "CONTEXTUAL", "UNRESOLVED"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
