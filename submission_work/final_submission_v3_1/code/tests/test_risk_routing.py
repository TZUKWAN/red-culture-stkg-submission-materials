# -*- coding: utf-8 -*-
"""test_risk_routing.py — Risk Estimator / 三路路由 / 预算分配 的契约测试。

固化 run_risk_routing.py 的三条硬契约（指令 §六/七/九）：
1. Risk 模型在合成数据上必须能分离 correct/wrong 样本（VAL AUPRC > 0.9）；
2. 三路路由边界：r_hat<=tau_accept 全部 AUTO_ACCEPT、tau_accept<r<=tau_escalate
   全部 ESCALATE、r>tau_escalate 全部 ABSTAIN；无基础预测的样本永不 AUTO_ACCEPT；
3. 预算分配精确：b=10% 恰好升级 10% 样本（round-half-up），b=0 不升级，
   b=100% 全升级，升级集合按 r_hat 降序取前 k 且跨预算嵌套。
另固化：TEST split 泄漏守卫、tau_accept 只在 VAL 学习（train 函数不带 DEV 行）、
CalibratedLR(sigmoid) 显式实现与底层 LR 秩一致（sklearn 1.8.0 CalibratedClassifierCV
在本配置下会产生完全反序分数，见 RISK_MODEL_CARD.json engineering_note）。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiment_pipelines"))

import run_risk_routing as rr  # noqa: E402


# ---------------------------------------------------------------------------
# 合成数据：两类样本，wrong 样本 clf_conf 低 / margin 低 / 规则不一致
# ---------------------------------------------------------------------------

def _synthetic_signal(wrong: int, correct: int, seed: int = 7) -> tuple[dict[str, dict], dict[str, int]]:
    rng = np.random.default_rng(seed)
    rows: dict[str, dict] = {}
    y: dict[str, int] = {}
    for i in range(wrong):
        sid = f"WRONG{i:03d}"
        rows[sid] = rr.feature_vector(_signals(
            clf_conf=float(rng.uniform(0.30, 0.55)),
            clf_margin=float(rng.uniform(0.02, 0.15)),
            rule_pred="Organization",
            rule_conf=float(rng.uniform(0.9, 0.99)),
            validated=False,
            lexical_contradiction=int(rng.random() < 0.5),
            pred_class="Concept",
            source_multiplicity=int(rng.integers(1, 4)),
        ))
        y[sid] = 1
    for i in range(correct):
        sid = f"OK{i:03d}"
        rows[sid] = rr.feature_vector(_signals(
            clf_conf=float(rng.uniform(0.75, 0.99)),
            clf_margin=float(rng.uniform(0.45, 0.90)),
            rule_pred="Person",
            rule_conf=float(rng.uniform(0.9, 0.99)),
            validated=True,
            lexical_contradiction=0,
            pred_class="Person",
            source_multiplicity=1,
        ))
        y[sid] = 0
    return rows, y


def _signals(**kw) -> dict:
    base = {
        "clf_pred": kw.get("pred_class", "Person"),
        "clf_conf": 0.9,
        "clf_margin": 0.8,
        "rule_pred": "Person",
        "rule_conf": 0.95,
        "validated": True,
        "source_multiplicity": 1,
        "lexical_contradiction": 0,
    }
    base.update(kw)
    return base


def test_risk_model_separates_synthetic_wrong_with_auprc_gt_09():
    """契约 1：risk 模型能分离 correct/wrong（留出集 AUPRC > 0.9）。"""
    train_rows, train_y = _synthetic_signal(wrong=120, correct=120, seed=11)
    hold_rows, hold_y = _synthetic_signal(wrong=80, correct=80, seed=23)
    fitted = rr.train_risk_models(train_rows, train_y)
    for name in rr.SIMPLICITY_ORDER:
        p = rr.predict_risk(fitted, name, hold_rows)
        ids = sorted(p)
        from sklearn.metrics import average_precision_score

        auprc = average_precision_score([hold_y[i] for i in ids], [p[i] for i in ids])
        assert auprc > 0.9, f"{name} AUPRC={auprc:.3f} <= 0.9"
        # wrong 样本的平均 r_hat 必须高于 correct 样本
        mean_wrong = float(np.mean([p[i] for i in ids if hold_y[i] == 1]))
        mean_ok = float(np.mean([p[i] for i in ids if hold_y[i] == 0]))
        assert mean_wrong > mean_ok + 0.2, f"{name}: mean_wrong={mean_wrong} mean_ok={mean_ok}"


def test_calibrated_lr_implementation_rank_consistent_with_lr():
    """显式 EnsemblePlattLR 不得复现 sklearn 1.8.0 CalibratedClassifierCV 的反序缺陷。"""
    train_rows, train_y = _synthetic_signal(wrong=100, correct=100, seed=31)
    fitted = rr.train_risk_models(train_rows, train_y)
    p_cal = rr.predict_risk(fitted, "CalibratedLR_sigmoid", train_rows)
    p_lr = rr.predict_risk(fitted, "LogisticRegression", train_rows)
    ids = sorted(p_cal)
    from scipy.stats import spearmanr

    rho = spearmanr([p_cal[i] for i in ids], [p_lr[i] for i in ids]).statistic
    assert rho > 0.5, f"CalibratedLR 反序或失联：spearman={rho:.3f}"


def test_route_three_way_boundaries():
    """契约 2：三路路由边界语义。"""
    tau_acc, tau_esc = 0.3, 0.7
    assert rr.route_three_way(0.0, tau_acc, tau_esc) == "AUTO_ACCEPT"
    assert rr.route_three_way(0.3, tau_acc, tau_esc) == "AUTO_ACCEPT"  # 边界含于 accept
    assert rr.route_three_way(0.30001, tau_acc, tau_esc) == "ESCALATE"
    assert rr.route_three_way(0.5, tau_acc, tau_esc) == "ESCALATE"
    assert rr.route_three_way(0.7, tau_acc, tau_esc) == "ESCALATE"  # 边界含于 escalate
    assert rr.route_three_way(0.70001, tau_acc, tau_esc) == "ABSTAIN"
    assert rr.route_three_way(1.0, tau_acc, tau_esc) == "ABSTAIN"
    # 无基础预测：永不 AUTO_ACCEPT
    assert rr.route_three_way(0.0, tau_acc, tau_esc, has_prediction=False) == "ESCALATE"
    assert rr.route_three_way(0.95, tau_acc, tau_esc, has_prediction=False) == "ABSTAIN"


def test_budget_allocation_exact():
    """契约 3：预算分配精确（b=10% 恰好升级 10% 样本）。"""
    scored = [(f"s{i:02d}", i / 100.0) for i in range(10)]  # r_hat 互不相同
    n = len(scored)
    assert rr.exact_budget_count(n, 0.10) == 1
    assert rr.exact_budget_count(n, 0.0) == 0
    assert rr.exact_budget_count(n, 1.0) == n
    assert rr.exact_budget_count(20, 0.5) == 10

    esc10 = rr.assign_budget_topk(scored, n, 0.10)
    assert len(esc10) == 1  # 恰好 10%
    assert esc10 == {"s09"}  # 取 r_hat 最高者

    esc5 = rr.assign_budget_topk(scored, n, 0.50)
    assert len(esc5) == 5
    assert esc5 == {"s05", "s06", "s07", "s08", "s09"}
    # 嵌套性：小预算集合 ⊆ 大预算集合
    assert esc10 <= esc5
    assert rr.assign_budget_topk(scored, n, 0.0) == set()
    assert rr.assign_budget_topk(scored, n, 1.0) == {sid for sid, _ in scored}

    # 并列打破确定性：r_hat 相同按 sample_id 字典序
    tied = [("b", 0.5), ("a", 0.5), ("c", 0.9), ("d", 0.1)]
    assert rr.assign_budget_topk(tied, 4, 0.5) == {"c", "a"}


def test_assert_no_test_samples_raises():
    """硬约束：TEST split 样本进入任何路径都必须抛断言。"""
    split_map = {"entity_type:a": "dev", "entity_type:b": "val", "entity_type:t": "test"}
    rr.assert_no_test_samples(["a", "b"], split_map, "unit")  # 不抛
    with pytest.raises(AssertionError):
        rr.assert_no_test_samples(["a", "t"], split_map, "unit")


def test_learn_tau_accept_accepts_only_low_risk_region():
    """tau_accept 学习：在可行域内只接受低风险（高正确）区。"""
    rows = (
        [{"r_hat": 0.05 + 0.001 * i, "correct": 1, "violation": 0} for i in range(40)]
        + [{"r_hat": 0.9, "correct": 0, "violation": 0} for _ in range(60)]
    )
    tau, info = rr.learn_tau_accept(rows, coverage_floor=0.3)
    assert tau < 0.5  # 不应越过正确区
    accepted = [r for r in rows if r["r_hat"] <= tau]
    assert len(accepted) >= 0.3 * len(rows) - 1e-9  # 满足 coverage floor
    assert all(r["correct"] == 1 for r in accepted)
    # 无 rows 时安全回退
    tau0, _ = rr.learn_tau_accept([], coverage_floor=0.3)
    assert tau0 == 0.0


def test_pareto_knee_picks_largest_chord_gap():
    """knee 由数据决定：取 risk 相对首末点弦的最大垂直落差处。"""
    pts = [
        {"budget": 0.0, "selective_risk": 0.9},
        {"budget": 0.25, "selective_risk": 0.5},
        {"budget": 0.5, "selective_risk": 0.3},
        {"budget": 0.75, "selective_risk": 0.1},
        {"budget": 1.0, "selective_risk": 0.0},
    ]
    # 弦从 (0,0.9) 到 (1,0)：chord(b)=0.9*(1-b)；gap: b=0.25→0.175, 0.5→0.15, 0.75→0.125
    knee = rr.pareto_knee(pts)
    assert knee["budget"] == 0.25
    assert math.isclose(knee["gap"], 0.175, rel_tol=1e-9)


def test_escalation_payload_blind_no_reference_leak():
    """升级 payload 只允许白名单字段；样本的生产/参考标签不得作为字段出现。"""
    frame = {
        "s1": {
            "name": "江浦",
            "production_type": "CulturalSite",  # 故意选一个不在候选类型表述中的值
            "meta": {
                "canonical_name": "江浦",
                "aliases_json": '["Dummy"]',
                "context_assertions": "ctx",
                "source_excerpt": "src",
            },
        }
    }
    payload = rr.escalation_payload(frame, "s1")
    allowed = {"task_id", "entity_name", "aliases", "context_assertions",
               "source_excerpt", "candidate_types", "type_definitions"}
    assert set(payload) == allowed
    assert payload["task_id"] == "s1"
    assert payload["entity_name"] == "江浦"
    assert payload["aliases"] == ["Dummy"]
    # 生产标签不得以任何字段/值身份进入 payload
    assert "production_type" not in payload
    assert payload["candidate_types"] == list(rr.ENTITY_TYPE_LABELS)
    assert payload["type_definitions"] == dict(rr.ENTITY_TYPE_DEFINITIONS)
    # 无参考/正确性信号字段
    for banned in ("reference", "correct", "risk", "label", "score"):
        assert not any(banned in str(k).lower() for k in payload), f"payload 字段泄漏: {banned}"


def test_finalize_prediction_falls_back_on_invalid_decision():
    """升级决策无效时回退基础预测且不计有效升级。"""
    final, src, ok = rr.finalize_prediction("Person", {"status": "OK", "decision": "NotAType", "decision_valid": False}, "gpt-oss-20b_fresh")
    assert (final, src, ok) == ("Person", "base_prediction_fallback", 0)
    final, src, ok = rr.finalize_prediction("Person", {"status": "OK", "decision": "Place", "decision_valid": True}, "gpt-oss-20b_fresh")
    assert (final, src, ok) == ("Place", "gpt-oss-20b_fresh", 1)
