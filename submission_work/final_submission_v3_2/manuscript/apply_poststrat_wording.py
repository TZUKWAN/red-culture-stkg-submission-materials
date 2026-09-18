# -*- coding: utf-8 -*-
"""apply_poststrat_wording.py — 估计量称谓修正（final-tier post-stratified）。

1. 69.18% 一律表述为「按最终层构成后分层校正」，并明确真实入样概率
   （inclusion probabilities）无法从冻结产物完整复原，不宣称完整设计加权估计。
2. 图题改为「级联准入前后强共识条件证据质量变化」（差值保留在柱标）。
3. §5 讨论改为中性表述（不使用「保守取向的代价」类防御性措辞）。
"""
from __future__ import annotations

from pathlib import Path

MS = Path(__file__).resolve().parent / "论文正文.md"
REP = Path(__file__).resolve().parents[1] / "experiments" / \
    "cascaded_admission_stage_effect" / "CASCADED_ADMISSION_STAGE_REPORT.md"
RES = Path(__file__).resolve().parents[1] / "experiments" / \
    "cascaded_admission_stage_effect" / "CASCADED_ADMISSION_STAGE_RESULTS.json"
FIGPY = Path(__file__).resolve().parents[1] / "experiments" / \
    "cascaded_admission_stage_effect" / "fig_cascaded_stage.py"

POST = "按最终层构成后分层校正（final-tier post-stratified）"

# ---------- 论文正文 ----------
t = MS.read_text(encoding="utf-8")
t = t.replace(
    "在独立双裁判形成强共识的判定中，直接发布的严格候选其证据支持精度为"
    "69.18%（95%CI 66.51—71.96），经证据语义核验后最终严格层达99.28%；",
    "在独立双裁判形成强共识的判定中，直接发布的严格候选其证据支持精度经"
    "后分层校正为69.18%（95%CI 66.51—71.96），经证据语义核验后最终严格层达99.28%；", 1)
t = t.replace(
    "直接发布的严格候选证据支持精度为69.18%（95%CI 66.51—71.96），明确不支持/冲突率为29.17%",
    "直接发布的严格候选，其按最终层构成后分层校正的证据支持精度为69.18%"
    "（95%CI 66.51—71.96），明确不支持/冲突率为29.17%", 1)
t = t.replace(
    "| 强共识条件支持精度 | 69.18% [66.51, 71.96] | **99.28%**（965/972）[0.9852, 0.9965] |",
    "| 强共识条件支持精度（后分层校正） | 69.18% [66.51, 71.96] | **99.28%**（965/972）[0.9852, 0.9965] |", 1)
t = t.replace(
    "注：Pre-Gate 行为 final 层比率估计量（按 31,067/31,282/49,809 层构成加权），CI 为分层 bootstrap（B=10,000，seed=20260916）；",
    "注：Pre-Gate 行为按最终层构成后分层校正的估计（final-tier post-stratified ratio estimator；"
    "冻结采样器存在 overlay/fallback 等多重入选路由，真实入样概率无法完整复原，"
    "故不宣称完整设计加权估计），CI 为分层 bootstrap（B=10,000，seed=20260916）；", 1)
t = t.replace(
    "直接发布的严格候选证据支持精度为69.18%（95%CI 66.51—71.96），明确不支持/冲突率达29.17%",
    "直接发布的严格候选，其后分层校正的证据支持精度为69.18%（95%CI 66.51—71.96），"
    "明确不支持/冲突率达29.17%", 1)
t = t.replace(
    "在强共识判定中，直接发布的严格候选证据支持精度为"
    "69.18%（95%CI 66.51—71.96），经证据语义核验后最终严格层提升至99.28%",
    "在强共识判定中，直接发布的严格候选经后分层校正的证据支持精度为69.18%"
    "（95%CI 66.51—71.96），经证据语义核验后最终严格层提升至99.28%", 1)
# §5 防御性措辞 → 中性表述
t = t.replace(
    "同时，被降级候选中仍有部分获双裁判支持、门外加权严格机会为0.66%，这些少量机会损失是方法保守取向的代价，论文如实报告而不掩饰。",
    "前置规范化与结构约束不能替代断言级证据核验；二者在级联过程中分别控制结构语义条件与证据支持条件。", 1)
MS.write_text(t, encoding="utf-8")
print("[wording] 论文正文.md updated")

# ---------- REPORT ----------
r = REP.read_text(encoding="utf-8")
r = r.replace(
    "## 三、估计方法声明\n\n- Pre-Gate 采用 final 层比率估计量",
    "## 三、估计方法声明\n\n- Pre-Gate 采用 **按最终层构成后分层校正的比率估计量"
    "（final-tier post-stratified ratio estimator）**。说明：冻结采样器存在 "
    "overlay/fallback 等多重入选路由，真实入样概率（inclusion probabilities）"
    "无法从冻结产物完整复原，故该估计为后分层校正，**不宣称完整设计加权估计**。", 1)
r = r.replace(
    "4. 局限：层内 predicate/boundary 路由过采样使层内代表性存在不可精确量化的偏差；\n"
    "   Judge 强共识覆盖率（Pre-Gate 32.09%、Final STRICT 42.86%）属于评价不确定性，\n"
    "   不与知识错误率混同。",
    "4. 局限：层内 predicate/boundary 路由过采样使层内代表性存在不可精确量化的偏差；\n"
    "   Judge 强共识覆盖率（Pre-Gate 32.09%、Final STRICT 42.86%）属于评价不确定性，\n"
    "   不与知识错误率混同。\n"
    "5. 表述规范：69.18% 一律称「按最终层构成后分层校正」，不称「设计加权」；\n"
    "   前置规范化与结构约束不能替代断言级证据核验，二者分别控制结构语义条件与\n"
    "   证据支持条件。", 1)
REP.write_text(r, encoding="utf-8")
print("[wording] REPORT updated")

# ---------- RESULTS.json：估计量称谓标注 ----------
res_p = RES
res = json.loads(res_p.read_text(encoding="utf-8"))
pg = res["pre_gate_strict_candidate"]
pg["estimator"] = ("final-tier post-stratified ratio estimator; true inclusion "
                   "probabilities not fully recoverable from frozen artifacts; "
                   "NOT claimed as a full design-weighted estimate")
res_p.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
print("[wording] RESULTS.json estimator note added")

# ---------- 图脚本：主标题 ----------
f = FIGPY.read_text(encoding="utf-8")
f = f.replace('ax.set_title("级联准入前后严格知识证据质量变化", fontsize=12)',
              'ax.set_title("级联准入前后强共识条件证据质量变化", fontsize=12)')
FIGPY.write_text(f, encoding="utf-8")
print("[wording] fig title updated")
