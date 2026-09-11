# -*- coding: utf-8 -*-
"""test_ablation_single_component_only.py — P0-C 消融单变量纯度测试。

契约（见 audit/method_final/01_METHOD_IMPLEMENTATION_AUDIT.md §3/§4）：
S1–S5 相对 S0_production_faithful 各只允许改变一个声明组件；候选源与分数
（prediction/score 输入）在 S0 与全部消融变体间逐样本恒等。fixture 为小型
信号帧，用真实 stkg_v2_semantics 函数构造能分别命中各组件的样本：

    A  全部组件通过（基线接受）
    B  agreement 失配（rule_pred 缺失 = 生产无独立词法/schema 信号）
    C  仅类门阈值失败（conf 0.30）
    D  仅词法严格矛盾守卫触发（"农会"严格提示 Organization ≠ 预测 Institution，
       同族 CollectiveAgent，故 contraindication 不触发）
    E  仅 contraindication 结构门触发（"浦口"+AdministrativeRegion：
       administrative_region_requires_explicit_admin_structure，词法提示为空）
    F  仅 TYPE_FAMILY 失配（预测 AlienType 不在受控类型族）
    G  无分类器信号（生产：非 pending 实体无分类器输出 → 弃权）
    I  类门与全局阈值可区分（conf 0.60：theta_c[Person]=0.90 vs global=0.50）
    J  规则≠分类器（延安：规则 Place / 分类器 Person，暴露候选源差异）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiment_pipelines"))

from run_selective_semantic import (  # noqa: E402
    CHANGED_COMPONENTS,
    FAITHFUL_VARIANTS,
    compose_s_variants,
)

ABLATION_VARIANTS = [
    "S1_wo_class_gate",
    "S2_wo_evidence_agreement",
    "S3_wo_contradiction_guard",
    "S4_wo_abstention",
    "S5_wo_structural_admission",
]

# fixture 阈值（DEV 学习结果的替身；禁止在测试里重新学习）
THETA_C = {"Person": 0.90, "Institution": 0.90, "AdministrativeRegion": 0.90, "AlienType": 0.50}
THETA_GLOBAL = 0.50
THETA_C_LEGACY: dict[str, float] = {}
THETA_GLOBAL_LEGACY = 0.30


def _row(name, stype, rule_pred, rule_conf, clf_pred, clf_conf, margin=0.10):
    return {
        "name": name,
        "production_type": "",
        "validated": False,
        "rule_pred": rule_pred,
        "rule_conf": rule_conf,
        "clf_pred": clf_pred,
        "clf_conf": clf_conf,
        "clf_margin": margin,
        "llm_pred": "Person",
        "llm_conf": 0.50,
        "contra_cache": {},
        "lexical_cache": {},
        "meta": {},
        "_primary_source_type": stype,
    }


def _fixture_frame() -> dict[str, dict]:
    return {
        "A": _row("毛泽东", "Person", "Person", 0.98, "Person", 0.97),
        "B": _row("李先念", "Person", None, None, "Person", 0.99),
        "C": _row("刘少奇", "Person", "Person", 0.98, "Person", 0.30),
        "D": _row("农会", "Institution", "Institution", 0.98, "Institution", 0.99),
        "E": _row("浦口", "Place", "AdministrativeRegion", 0.98, "AdministrativeRegion", 0.99),
        "F": _row("陌生物件", "Unknown", "AlienType", 0.98, "AlienType", 0.99),
        "G": _row("无名者", "Person", "Person", 0.98, None, None),
        "I": _row("周恩来", "Person", "Person", 0.98, "Person", 0.60),
        "J": _row("延安", "Place", "Place", 0.98, "Person", 0.99),
    }


def _compose(frame: dict[str, dict]) -> dict[str, list[dict]]:
    calib = {sid: [(1.0, 0.5)] for sid in frame}  # isotonic 仅 legacy 家族消费
    return compose_s_variants(frame, calib, THETA_C, THETA_GLOBAL, THETA_C_LEGACY, THETA_GLOBAL_LEGACY)


def _by_id(variants: dict[str, list[dict]], name: str) -> dict[str, dict]:
    return {r["sample_id"]: r for r in variants[name]}


# ---------------------------------------------------------------------------
# changed_components 字段契约
# ---------------------------------------------------------------------------

def test_changed_components_s0_is_none_and_ablations_single_component():
    assert CHANGED_COMPONENTS["S0_production_faithful"] == "none"
    expected = {
        "S1_wo_class_gate": "class_gate",
        "S2_wo_evidence_agreement": "evidence_agreement",
        "S3_wo_contradiction_guard": "contradiction_guard",
        "S4_wo_abstention": "abstention",
        "S5_wo_structural_admission": "structural_admission",
    }
    for variant, comp in expected.items():
        assert CHANGED_COMPONENTS[variant] == comp
        assert "," not in comp, f"{variant} 必须只改一个声明组件"
    for variant, comp in CHANGED_COMPONENTS.items():
        assert isinstance(comp, str) and comp, variant


# ---------------------------------------------------------------------------
# 单变量纯度核心：prediction/score 输入逐条一致
# ---------------------------------------------------------------------------

def test_ablation_prediction_and_score_identical_to_s0():
    variants = _compose(_fixture_frame())
    s0 = _by_id(variants, "S0_production_faithful")
    for variant in ABLATION_VARIANTS:
        rows = _by_id(variants, variant)
        assert set(rows) == set(s0), variant
        for sid in s0:
            assert rows[sid]["prediction"] == s0[sid]["prediction"], (variant, sid)
            assert rows[sid]["score"] == s0[sid]["score"], (variant, sid)


def test_s1_prediction_column_identical_to_s0():
    variants = _compose(_fixture_frame())
    s0 = _by_id(variants, "S0_production_faithful")
    s1 = _by_id(variants, "S1_wo_class_gate")
    assert [s1[sid]["prediction"] for sid in sorted(s0)] == [s0[sid]["prediction"] for sid in sorted(s0)]


def test_no_candidate_signal_rows_identical_across_faithful_family():
    variants = _compose(_fixture_frame())
    for sid in ("G",):  # 无分类器信号：生产行为照搬（全部弃权、无预测）
        for variant in FAITHFUL_VARIANTS:
            r = _by_id(variants, variant)[sid]
            assert r["prediction"] == "" and r["score"] is None and r["accepted"] == 0
            assert r["gate_reason"] == "no_candidate_signal"


# ---------------------------------------------------------------------------
# 逐变体：只有声明组件的条件发生变化
# ---------------------------------------------------------------------------

def test_s1_differs_only_through_threshold():
    variants = _compose(_fixture_frame())
    s0 = _by_id(variants, "S0_production_faithful")
    s1 = _by_id(variants, "S1_wo_class_gate")
    diff = {sid for sid in s0 if s1[sid]["accepted"] != s0[sid]["accepted"]}
    # 只有 I（0.50 <= conf 0.60 < theta_c[Person] 0.90）经全局阈值翻转
    assert diff == {"I"}
    assert "class_gate_abstain" in s0["I"]["gate_reason"]
    assert s1["I"]["accepted"] == 1


def test_s2_only_removes_evidence_agreement():
    variants = _compose(_fixture_frame())
    s0 = _by_id(variants, "S0_production_faithful")
    s2 = _by_id(variants, "S2_wo_evidence_agreement")
    diff = {sid for sid in s0 if s2[sid]["accepted"] != s0[sid]["accepted"]}
    # B：rule 缺失（生产：无独立信号 → 不合格）；J：rule != 分类器预测
    assert diff == {"B", "J"}
    for sid in ("B", "J"):
        assert "evidence_agreement_fail" in s0[sid]["gate_reason"]
        assert s2[sid]["accepted"] == 1
    # agreement 本成立的样本逐字段一致
    for sid in s0.keys() - {"B", "J"}:
        assert s2[sid] == s0[sid], sid


def test_s3_only_removes_contradiction_guard():
    variants = _compose(_fixture_frame())
    s0 = _by_id(variants, "S0_production_faithful")
    s3 = _by_id(variants, "S3_wo_contradiction_guard")
    diff = {sid for sid in s0 if s3[sid]["accepted"] != s0[sid]["accepted"]}
    assert diff == {"D"}
    assert "contradiction_guard" in s0["D"]["gate_reason"] and s0["D"]["gate_violation"] == 1
    assert s3["D"]["accepted"] == 1 and s3["D"]["gate_violation"] == 0
    for sid in s0.keys() - {"D"}:
        assert s3[sid] == s0[sid], sid


def test_s4_removes_only_threshold_abstention_and_keeps_guards():
    variants = _compose(_fixture_frame())
    s0 = _by_id(variants, "S0_production_faithful")
    s4 = _by_id(variants, "S4_wo_abstention")
    diff = {sid for sid in s0 if s4[sid]["accepted"] != s0[sid]["accepted"]}
    # 仅被阈值挡住的 C、I 翻转
    assert diff == {"C", "I"}
    assert s4["C"]["accepted"] == 1 and "theta=0" in s4["C"]["gate_reason"]
    # agreement / 矛盾守卫 / 结构门全部保留：被它们挡住的样本仍弃权
    for sid in ("B", "D", "E", "F"):
        assert s4[sid]["accepted"] == 0, sid
    assert "evidence_agreement_fail" in s4["B"]["gate_reason"]
    assert "contradiction_guard" in s4["D"]["gate_reason"]
    assert "structural_admission" in s4["E"]["gate_reason"]
    assert "structural_admission" in s4["F"]["gate_reason"]


def test_s5_only_removes_structural_admission():
    variants = _compose(_fixture_frame())
    s0 = _by_id(variants, "S0_production_faithful")
    s5 = _by_id(variants, "S5_wo_structural_admission")
    diff = {sid for sid in s0 if s5[sid]["accepted"] != s0[sid]["accepted"]}
    # E：contraindication 触发；F：TYPE_FAMILY 失配
    assert diff == {"E", "F"}
    for sid in ("E", "F"):
        assert "structural_admission" in s0[sid]["gate_reason"] and s0[sid]["gate_violation"] == 1
        assert s5[sid]["accepted"] == 1 and s5[sid]["gate_violation"] == 0
    for sid in s0.keys() - {"E", "F"}:
        assert s5[sid] == s0[sid], sid


# ---------------------------------------------------------------------------
# legacy 对照与基线融合不变
# ---------------------------------------------------------------------------

def test_legacy_differs_in_candidate_source_and_is_flagged():
    variants = _compose(_fixture_frame())
    s0 = _by_id(variants, "S0_production_faithful")
    legacy = _by_id(variants, "S0_rule_first_legacy")
    # J：规则 Place / 分类器 Person——faithful 不让规则替换预测，legacy 规则优先
    assert s0["J"]["prediction"] == "Person"
    assert legacy["J"]["prediction"] == "Place"
    assert legacy["J"]["accepted"] == 1
    changed = CHANGED_COMPONENTS["S0_rule_first_legacy"].split(",")
    assert "candidate_source" in changed and "score_calibration" in changed


def test_s9_rule_first_fusion_baseline_unchanged():
    variants = _compose(_fixture_frame())
    s9 = _by_id(variants, "S9_rule_plus_classifier")
    frame = _fixture_frame()
    for sid, f in frame.items():
        expected = f["rule_pred"] or f["clf_pred"] or ""
        assert s9[sid]["prediction"] == expected, sid
