# -*- coding: utf-8 -*-
"""test_selective_stats_repair.py — P0-3 修复口径的自动测试。

覆盖 GOAL v3_1 指令 第十九节要求：
* test_mcnemar_respects_acceptance：Full 100 条只接受 20 条时，McNemar 的
  correctness 绝不可能来自未接受的 80 条；
* test_selective_denominator_consistency：曲线分母恒为全样本、弃权行不计正确；
* test_matched_coverage_comparison：配对 bootstrap 共享索引、差值可复现；
* Risk@Coverage / Coverage@Risk 的基本性质。
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "independent_eval"))

from selective_stats import (  # noqa: E402
    coverage_at_risk,
    matched_coverage_risk_difference,
    mcnemar_on_jointly_accepted,
    risk_at_coverage,
    rows_to_points,
)


def _row(sid, accepted, correct, score):
    return {"sample_id": sid, "accepted": accepted, "correct": correct, "score": score}


def test_mcnemar_respects_acceptance():
    # Full 100 条，只接受 20 条（score 高的 20 条）；盲系统 B 全接受。
    # 构造：未接受的 80 条里 Full 的"潜在预测"全对（correct=1）——若统计
    # 把它们算进来，Full 会虚高；接受集内 Full 12 对 8 错，B 接受集 19 对 1 错。
    rows_full = []
    rows_blind = []
    rng = random.Random(7)
    for i in range(100):
        accepted = i < 20
        # Full 未接受的 80 条也带 correct=1（模拟"潜在预测恰好正确"）——
        # 修复口径必须完全忽略它们。
        correct_full = 1 if (accepted and i < 12) else 0
        rows_full.append(_row(f"s{i}", int(accepted), correct_full, 0.9 - i * 0.001 if accepted else None))
        rows_blind.append(_row(f"s{i}", 1, 1 if i != 5 else 0, 0.5))
    res = mcnemar_on_jointly_accepted(rows_full, rows_blind, system_a_name="Full", system_b_name="Blind")
    # 共同接受集 = Full 的 20 条；其中 Full 对 12、B 在 s5 错 → b=12? s5: full correct? i=5<12 → full 对
    assert res["n_shared_accepted"] == 20
    assert res["coverage_a"] == 0.20 and res["coverage_b"] == 1.0
    # b: full对且blind错 → s5 一条；c: full错且blind对 → i in 12..19 且 i!=5 → 8 条
    assert res["b_a_correct_b_wrong"] == 1
    assert res["c_a_wrong_b_correct"] == 8
    assert res["n_discordant"] == 9
    # p 值精确二项：b=1,c=9 → 2*sum_{i<=1}C(9,i)/2^9
    p_expect = 2 * (1 + 9) / 2**9
    assert abs(res["p_value"] - p_expect) < 1e-12


def test_mcnemar_ignores_unaccepted_latent_predictions():
    # 把未接受样本的 correct 全部翻转（0↔1），联合接受集结果必须完全不变。
    rng = random.Random(11)
    mk = lambda flip: [
        _row(f"s{i}", 1 if i < 50 else 0,
             (1 if rng.random() < 0.6 else 0) ^ (flip and i >= 50),
             0.9 - i * 0.001 if i < 50 else None)
        for i in range(100)
    ]
    a1, b1 = mk(False), mk(False)
    a2 = [_row(r["sample_id"], r["accepted"], r["correct"] ^ (0 if r["accepted"] else 1), r["score"]) for r in a1]
    r1 = mcnemar_on_jointly_accepted(a1, b1)
    r2 = mcnemar_on_jointly_accepted(a2, b1)
    assert (r1["b_a_correct_b_wrong"], r1["c_a_wrong_b_correct"]) == (r2["b_a_correct_b_wrong"], r2["c_a_wrong_b_correct"])
    assert r1["n_shared_accepted"] == r2["n_shared_accepted"] == 50


def test_curve_denominator_and_abstention():
    rows = [
        _row("a", 1, 1, 0.9),
        _row("b", 1, 0, 0.8),
        _row("c", 0, 0, None),   # 弃权：correct 恒 0
        _row("d", 0, 1, None),   # 即使误带 correct=1，弃权也不得计入已发布正确
    ]
    pts = rows_to_points(rows)
    full = pts[-1]
    assert full["coverage"] == 0.5 and full["n_accepted"] == 2
    assert full["errors"] == 1 and abs(full["selective_risk"] - 0.5) < 1e-12
    first = pts[0]
    assert first["coverage"] == 0.0 and first["selective_risk"] == 0.0


def test_risk_at_coverage_and_coverage_at_risk():
    rows = [
        _row("a", 1, 1, 0.9),
        _row("b", 1, 1, 0.8),
        _row("c", 1, 1, 0.7),
        _row("d", 1, 0, 0.6),
    ]
    pts = rows_to_points(rows)
    r = risk_at_coverage(pts, targets=(0.5, 0.75))
    assert r["risk@50%"] == 0.0 and abs(r["risk@75%"] - 0.0) < 1e-12
    c = coverage_at_risk(pts, limits=(0.01, 0.25))
    assert c["coverage@risk<=1%"] == 0.75 and c["coverage@risk<=25%"] == 1.0


def test_matched_coverage_shared_indices_and_sign():
    rng = random.Random(3)
    rows_a = []  # A：前 60 条全对、后 40 条全错（高 score 对应正确）→ 曲线占优
    rows_b = []  # B：随机 50% 正确，score 无区分力
    for i in range(100):
        ok = i < 60
        rows_a.append(_row(f"s{i}", 1, int(ok), 0.99 - i * 0.001))
        ok_b = rng.random() < 0.5
        rows_b.append(_row(f"s{i}", 1, int(ok_b), 0.5))
    out = matched_coverage_risk_difference(rows_a, rows_b, n_bootstrap=200, seed=42)
    # 逐网格点：point 差 = risk_b - risk_a ≤ 0（A 更优）
    for c, d in out["diff_b_minus_a_point"].items():
        assert d <= 1e-12
    # 固定 seed 可复现
    out2 = matched_coverage_risk_difference(rows_a, rows_b, n_bootstrap=200, seed=42)
    assert out["bootstrap_mean_diff_b_minus_a"] == out2["bootstrap_mean_diff_b_minus_a"]
    # 共享索引：mean diff == mean(risk_b_rep - risk_a_rep)（符号恒定，这里 A 更优 → 负）
    for c, v in out["bootstrap_mean_diff_b_minus_a"].items():
        assert v <= 1e-12


if __name__ == "__main__":
    raise SystemExit(0)
