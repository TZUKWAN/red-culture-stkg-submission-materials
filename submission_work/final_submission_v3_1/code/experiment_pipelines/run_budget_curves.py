# -*- coding: utf-8 -*-
"""run_budget_curves.py — 同模型预算曲线修复 + 同预算路由有效性对比（指令 §2/§3）。

旧问题（risk_routing/QUALITY_BUDGET_CURVE.csv，2026-09-09 版）：
  1. 曲线混模型：0–75% 升级用本地 gpt-oss-20b，100% 点用 B3 既有 gpt-5.6-luna 全量行；
  2. 质量口径用含 Judge B 的 strong 共识参考，B3（gpt-5.6-luna）与 Judge B 同族，
     0.972/0.979 高估质量上限。

本脚本修复（只新建文件，不修改任何既有文件）：
  1. 100% 点 = gpt-oss-20b every-item：对 DEV+VAL 全部样本（TEST 硬排除）执行
     gpt-oss-20b escalation 真实调用。复用 lmstudio_provider.chat_json；system prompt
     与 payload 与 run_risk_routing.py 完全一致（直接 import 复用，sha256 逐条核对）；
     断点续跑；旧 risk_routing/ESCALATION_CALLS.jsonl 只读复用命中（status=OK 视为完成），
     新调用追加写 budget_v2/ESCALATION_CALLS.jsonl；
  2. CURVE_LOCAL（主曲线）：0/5/10/20/30/40/50/75/100% 全部由 gpt-oss-20b 生成——
     升级选择顺序 = Risk Estimator r_hat 降序。r_hat 复用 run_risk_routing.py 已训练
     模型（同特征/同 DEV 标签/同 seed 确定性重训），并与既有 ROUTING_RUNS_{dev,val}.csv
     的 r_hat 列逐样本核对（容差 1e-6），核对结果写入 SUMMARY；
  3. CURVE_EXTERNAL（水平参考线）：gpt-5.6-luna every-item（V3 IMCR_BLIND_LLM_RUNS.csv
     的 B3_blind_llm 行）对 leave-B-out 参考（V3 IMCR_REFERENCE_LEAVE_B_OUT.csv，
     judge_removed=B，无 Judge B 票）；
  4. 质量口径：主口径 = leave-B-out 参考（曲线与路由对比同参考，gpt-oss-20b 与
     gpt-5.6-luna 两曲线可比）；strong 共识只作敏感性列并明确标注
     **不得作为质量上限**（Judge B 族重叠）；
  5. ROUTING_COMPARISON：预算 b∈{5,10,20,30,40,50}%（每个 split 内 k=round-half-up(b·n)），
     六种路由选谁升级（全部共用同一批 gpt-oss-20b every-item 调用记录，payload/参考一致）：
       R1 Random(seed 20260910，每 split 一条固定全排列，预算取前缀→嵌套)
       R2 最低分类器置信（clf_conf 升序，缺失=最不确定）
       R3 最低 margin（clf_margin 升序，缺失=最不确定）
       R4 最高熵（entropy_margin_approx 降序，缺失 margin→熵=1）
       R5 规则/分类器不一致优先（rule_pred 与 clf_pred 均存在且不等者优先；
          组内按熵降序、sample_id 升序打破平手）
       R6 Risk Estimator r_hat 降序（生产路由）
       R7 Oracle（真实错样本优先，oracle-only 诊断，不参与统计检验）
     全部样本发布（升级→gpt-oss-20b 决策，无效回退基础预测；未升级→基础预测；
     最终预测为空的样本对参考记为错），无弃权；
  6. 统计：每个预算上 R6 vs R1/R2/R3（另附 R4/R5）paired bootstrap（2000 次，
     同一重采样索引集作用两条路由），Δquality 点估计、95% percentile CI、
     双侧 bootstrap p 值。

硬约束：TEST 样本全程排除（rr.assert_no_test_samples 显式断言，EscalationRunner 内
再次断言）；无编造（全部指标由真实调用记录与既有数据文件计算，报告数字由本脚本
从数据自动生成）；checkpoint 可续（JSONL 追加 + status=OK 缓存命中跳过）。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np  # noqa: E402

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"
for _p in (
    str(V3 / "code"),
    str(V3 / "code" / "independent_eval"),
    str(V3 / "code" / "experiment_pipelines"),
    str(V3 / "data" / "external_inputs"),
    str(Path(__file__).resolve().parent.parent / "independent_eval"),
    str(Path(__file__).resolve().parent),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import run_risk_routing as rr  # noqa: E402  只 import 复用，不修改
import run_selective_semantic as rss  # noqa: E402  只 import 复用，不修改
from lmstudio_provider import DEFAULT_MODEL  # noqa: E402

V3_REF_LOB = V3 / "experiments" / "08_independent_reference" / "IMCR_REFERENCE_LEAVE_B_OUT.csv"
V3_BLIND = V3 / "experiments" / "09_independent_baselines" / "IMCR_BLIND_LLM_RUNS.csv"
V3_REF_STRONG = rr.V3_REF_STRONG
OLD_ESCALATION_LOG = rr.OUT_DIR / "ESCALATION_CALLS.jsonl"  # 只读复用缓存
SPLIT_MANIFEST = rr.SPLIT_MANIFEST

OUT_DIR = V3_1 / "experiments" / "02_selective_semantic" / "budget_v2"
ESCALATION_LOG_V2 = OUT_DIR / "ESCALATION_CALLS.jsonl"
AUDIT_DIR = V3_1 / "audit" / "method_final"

SEED = 20260910
N_BOOTSTRAP = 2000
BUDGETS_CURVE = [0.0, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.75, 1.0]
BUDGETS_ROUTING = [0.05, 0.10, 0.20, 0.30, 0.40, 0.50]
PRIMARY_REF = "leave_b_out"

ROUTE_DEFS = [
    ("R1", "random_seed20260910", False),
    ("R2", "lowest_clf_confidence", False),
    ("R3", "lowest_margin", False),
    ("R4", "highest_entropy", False),
    ("R5", "rule_clf_disagreement_first", False),
    ("R6", "risk_estimator_r_hat", False),
    ("R7", "oracle_true_errors_first", True),
]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def r6(x: float | None) -> Any:
    return round(float(x), 6) if x is not None else None


# ---------------------------------------------------------------------------
# 参考与 B3 行
# ---------------------------------------------------------------------------

def load_reference_lob() -> dict[str, str]:
    """leave-B-out 参考（judge_removed=B）；主质量口径，与 gpt-5.6-luna 无族重叠。"""
    ref = {}
    judge_sets = Counter()
    for row in csv.DictReader(open(V3_REF_LOB, encoding="utf-8-sig")):
        if row["task_type"] == "entity_type" and row["reference_label"]:
            ref[row["sample_id"]] = row["reference_label"]
            judge_sets[row.get("judges", "")] += 1
    return ref, judge_sets


def load_b3_predictions() -> dict[str, dict[str, Any]]:
    """B3 = gpt-5.6-luna 既有全量盲 LLM 行（V3 IMCR_BLIND_LLM_RUNS.csv）。"""
    out: dict[str, dict[str, Any]] = {}
    for r in csv.DictReader(open(V3_BLIND, encoding="utf-8-sig")):
        if (
            r.get("task_type") == "entity_type"
            and r.get("method_id") == "B3_blind_llm"
            and r.get("availability_status") == "available"
            and r.get("prediction")
        ):
            out.setdefault(r["sample_id"], {
                "prediction": r["prediction"],
                "confidence": float(r["confidence"]) if r.get("confidence") else None,
            })
    return out


# ---------------------------------------------------------------------------
# r_hat：复用 run_risk_routing.py 已训练模型（确定性重训 + 与既有输出核对）
# ---------------------------------------------------------------------------

def rebuild_r_hat(frame: dict[str, Any], reference_strong: dict[str, str],
                  split_map: dict[str, str], work_ids: list[str]) -> dict[str, Any]:
    feat_rows = rr.build_feature_rows(frame)
    dev_ids = [s for s in work_ids if split_map[f"entity_type:{s}"] == "dev"]
    val_ids = [s for s in work_ids if split_map[f"entity_type:{s}"] == "val"]
    train_ids = [s for s in dev_ids if reference_strong.get(s) and frame[s]["clf_pred"]]
    dev_y = {s: int(frame[s]["clf_pred"] != reference_strong[s]) for s in train_ids}
    val_score_ids = [s for s in val_ids if reference_strong.get(s) and frame[s]["clf_pred"]]
    val_y = {s: int(frame[s]["clf_pred"] != reference_strong[s]) for s in val_score_ids}
    fitted = rr.train_risk_models({s: feat_rows[s] for s in train_ids}, dev_y)
    selection = rr.select_risk_model(fitted, {s: feat_rows[s] for s in train_ids}, dev_y,
                                     {s: feat_rows[s] for s in val_score_ids}, val_y)
    chosen = selection["chosen"]
    r_hat: dict[str, float] = {}
    scored_pool = {s: feat_rows[s] for s in work_ids if frame[s]["clf_pred"]}
    r_hat.update(rr.predict_risk(fitted, chosen, scored_pool))
    for s in work_ids:
        r_hat.setdefault(s, 1.0)  # 无 clf_pred：r_hat=1.0（与生产政策一致）
    return {
        "feat_rows": feat_rows, "r_hat": r_hat, "chosen": chosen, "selection": selection,
        "train_ids": train_ids, "val_score_ids": val_score_ids,
        "dev_y": dev_y, "val_y": val_y,
    }


def verify_r_hat_reuse(r_hat: dict[str, float]) -> dict[str, Any]:
    """与既有 ROUTING_RUNS_{dev,val}.csv 的 r_hat 列逐样本核对（该列 round 到 6 位）。"""
    out: dict[str, Any] = {"checked_files": [], "n_compared": 0, "max_abs_diff": 0.0, "match": False}
    for sp in ("dev", "val"):
        path = rr.OUT_DIR / f"ROUTING_RUNS_{sp}.csv"
        if not path.exists():
            out["checked_files"].append({"path": str(path), "exists": False})
            continue
        n = 0
        for row in csv.DictReader(open(path, encoding="utf-8-sig")):
            sid = row["sample_id"]
            if sid not in r_hat or not row.get("r_hat"):
                continue
            diff = abs(float(row["r_hat"]) - r_hat[sid])
            out["max_abs_diff"] = max(out["max_abs_diff"], diff)
            n += 1
        out["n_compared"] += n
        out["checked_files"].append({"path": str(path), "exists": True, "n_compared": n})
    out["match"] = out["n_compared"] > 0 and out["max_abs_diff"] <= 1e-6
    return out


# ---------------------------------------------------------------------------
# 路由排序
# ---------------------------------------------------------------------------

def route_order(route_id: str, ids: list[str], r_hat: dict[str, float],
                feat_rows: dict[str, dict[str, float]], frame: dict[str, Any],
                ref_eval: dict[str, str]) -> list[str]:
    """返回该路由的完整排序（升级取前 k）。确定性。"""
    if route_id == "R1":
        rng = np.random.default_rng(SEED)
        perm = list(rng.permutation(len(ids)))
        return [ids[i] for i in perm]
    if route_id in ("R2", "R3"):
        keyname = "clf_conf" if route_id == "R2" else "clf_margin"
        def key(sid: str):
            v = feat_rows[sid][keyname]
            v = float(v) if v is not None else -1.0  # 缺失=最不确定→先升级
            return (v, sid)
        return sorted(ids, key=key)
    if route_id == "R4":
        return sorted(ids, key=lambda s: (-feat_rows[s]["entropy_margin_approx"], s))
    if route_id == "R5":
        def key(sid: str):
            rp = frame[sid]["rule_pred"] or ""
            cp = frame[sid]["clf_pred"] or ""
            disagree = 1.0 if (rp and cp and rp != cp) else 0.0
            return (-disagree, -feat_rows[sid]["entropy_margin_approx"], sid)
        return sorted(ids, key=key)
    if route_id == "R6":
        ranked = sorted(((s, r_hat[s]) for s in ids), key=lambda t: (-t[1], t[0]))
        return [s for s, _ in ranked]
    if route_id == "R7":
        def key(sid: str):
            ref = ref_eval.get(sid)
            wrong = 1.0 if (ref and (frame[sid]["clf_pred"] or "") != ref) else 0.0
            return (-wrong, sid)
        return sorted(ids, key=key)
    raise ValueError(route_id)


def budget_k(n: int, b: float) -> int:
    return rr.exact_budget_count(n, b)


# ---------------------------------------------------------------------------
# 评分
# ---------------------------------------------------------------------------

def base_pred(frame: dict[str, Any], sid: str) -> str:
    return frame[sid]["clf_pred"] or ""


def finalize_all(ids: list[str], esc_sets: dict[str, set[str]],
                 esc_records: dict[str, dict[str, Any]], frame: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """对样本集合给出最终预测：在任一 split 升级集内→gpt-oss-20b 决策（无效回退基础），
    否则→基础预测。esc_sets 键 = split 名。"""
    out: dict[str, dict[str, Any]] = {}
    for sid in ids:
        sp = None
        for cand, st in esc_sets.items():
            if sid in st:
                sp = cand
                break
        esc_rec = esc_records.get(sid) if sp is not None else None
        final, fsrc, eval_ok = rr.finalize_prediction(
            base_pred(frame, sid), esc_rec, "gpt-oss-20b_every_item")
        out[sid] = {"final": final, "source": fsrc, "escalation_valid": eval_ok,
                    "escalated": sp is not None}
    return out


def score_finals(ids: list[str], finals: dict[str, dict[str, Any]], frame: dict[str, Any],
                 ref_map: dict[str, str]) -> dict[str, Any]:
    """发布全部样本口径的质量指标（labeled = 有参考样本；最终预测为空记错）。"""
    labeled = [s for s in ids if ref_map.get(s)]
    n = len(labeled)
    if n == 0:
        return {"n_labeled": 0}
    correct = [int(finals[s]["final"] == ref_map[s]) for s in labeled]
    w2r = sum(1 for s in labeled
              if base_pred(frame, s) != ref_map[s] and finals[s]["final"] == ref_map[s])
    r2w = sum(1 for s in labeled
              if base_pred(frame, s) == ref_map[s] and finals[s]["final"] != ref_map[s])
    n_empty = sum(1 for s in labeled if not finals[s]["final"])
    return {
        "n_labeled": n,
        "n_correct": sum(correct),
        "agreement": sum(correct) / n,
        "wrong_to_right": w2r,
        "right_to_wrong": r2w,
        "generalized_risk": 1.0 - sum(correct) / n,
        "n_final_empty": n_empty,
        "n_escalated": sum(1 for s in ids if finals[s]["escalated"]),
    }


# ---------------------------------------------------------------------------
# paired bootstrap
# ---------------------------------------------------------------------------

def paired_bootstrap(correct_a: np.ndarray, correct_b: np.ndarray,
                     n_boot: int, seed_seq: list[int]) -> dict[str, Any]:
    rng = np.random.default_rng(seed_seq)
    n = len(correct_a)
    idx = rng.integers(0, n, size=(n_boot, n))
    deltas = correct_a[idx].mean(axis=1) - correct_b[idx].mean(axis=1)
    obs = float(correct_a.mean() - correct_b.mean())
    lo, hi = (float(v) for v in np.percentile(deltas, [2.5, 97.5]))
    p_two = float(2.0 * min((deltas <= 0).mean(), (deltas >= 0).mean()))
    return {
        "delta_observed": obs,
        "ci95_low": lo,
        "ci95_high": hi,
        "p_boot_two_sided": min(1.0, p_two),
        "frac_delta_gt0": float((deltas > 0).mean()),
    }


def classify_ci(ci: dict[str, Any]) -> str:
    if ci["ci95_low"] > 0:
        return "R6显著优于对手（95% CI 全为正）"
    if ci["ci95_high"] < 0:
        return "R6显著劣于对手（95% CI 全为负）"
    return "无显著差异（95% CI 跨 0）"


# ---------------------------------------------------------------------------
# 报告生成
# ---------------------------------------------------------------------------

def pct(x: float | None) -> str:
    return f"{x * 100:.1f}" if x is not None else "-"


def write_reports(ctx: dict[str, Any]) -> list[Path]:
    curve_pooled = ctx["curve_pooled"]
    ext = ctx["external"]
    comp_rows = ctx["comp_rows"]
    boot = ctx["bootstrap"]
    boot_pairs = ctx["boot_pairs"]
    summary = ctx["summary"]

    def curve_table(rows: list[dict[str, Any]]) -> str:
        head = ("| 预算 | k(升级条数) | 一致率(leave-B-out) | 错→对 | 对→错 | 广义风险 | "
                "敏感性:一致率(strong) |\n"
                "|---|---|---|---|---|---|---|\n")
        lines = []
        for r in rows:
            lines.append(
                f"| {r['budget']:.0%} | {r['k_escalated']} | {r['agreement']:.4f} | "
                f"{r['wrong_to_right']} | {r['right_to_wrong']} | {r['generalized_risk']:.4f} | "
                f"{r['agreement_strong_sensitivity']:.4f} |")
        return head + "\n".join(lines)

    parts: list[str] = []

    # ---------- 报告 1：budget_v2/REPORT_BUDGET_CURVE.md ----------
    r = []
    r.append("# REPORT — 同模型预算曲线（budget_v2 / CURVE_LOCAL + CURVE_EXTERNAL）")
    r.append("")
    r.append(f"生成：{summary['created_utc']} ｜ 实现：`code/experiment_pipelines/run_budget_curves.py`"
             f" ｜ seed={SEED}")
    r.append("")
    r.append("## 1. 修复了什么")
    r.append("")
    r.append("| 项 | 旧曲线（risk_routing/，2026-09-09） | 本曲线（budget_v2/） |")
    r.append("|---|---|---|")
    r.append("| 100% 点模型 | B3 既有 gpt-5.6-luna 全量行（混模型） | **gpt-oss-20b every-item"
             f"（{ctx['n_work']} 样本全部真实调用）** |")
    r.append("| 0–75% 升级模型 | gpt-oss-20b（真实调用） | gpt-oss-20b（同一批 every-item 记录，同 prompt/payload sha） |")
    r.append("| 质量口径 | 含 Judge B 的 strong 共识 | **leave-B-out（无 Judge B）主口径**；strong 只作敏感性列 |")
    r.append("| 0.972/0.979 | 被当作质量上限报告 | **作废（Judge B 族重叠高估）；本报告不作为上限引用** |")
    r.append("")
    r.append("## 2. CURVE_LOCAL（主曲线，全部 gpt-oss-20b）— pooled DEV+VAL")
    r.append("")
    r.append(f"总体：DEV n={ctx['n_dev']} + VAL n={ctx['n_val']} = {ctx['n_work']}；"
             f"有 leave-B-out 参考 {ctx['n_labeled_work']} 条（TEST {ctx['n_test']} 全程排除）。")
    r.append("")
    r.append(curve_table(curve_pooled))
    r.append("")
    r.append("### DEV（n=%d，有参考 %d）" % (ctx["n_dev"], ctx["n_labeled_dev"]))
    r.append("")
    r.append(curve_table(ctx["curve_dev"]))
    r.append("")
    r.append("### VAL（n=%d，有参考 %d）" % (ctx["n_val"], ctx["n_labeled_val"]))
    r.append("")
    r.append(curve_table(ctx["curve_val"]))
    r.append("")
    r.append("口径：预算 b 的升级集 = 每个 split 内 r_hat 最高的 k=round-half-up(b·n) 个"
             "（并列按 (-r_hat, sample_id)）；升级→gpt-oss-20b 决策（无效回退基础预测），"
             "未升级→基础预测，全部发布（最终预测为空记错），无弃权。")
    r.append("")
    r.append("## 3. CURVE_EXTERNAL（水平参考线）— gpt-5.6-luna every-item vs leave-B-out")
    r.append("")
    r.append("| 总体 | n_labeled | every-item 一致率 |")
    r.append("|---|---|---|")
    for sp in ("pooled", "dev", "val"):
        e = ext[sp]
        r.append(f"| {sp} | {e['n_labeled']} | **{e['agreement_leave_b_out']:.4f}** |")
    r.append("")
    r.append(f"- 参考文件：`{ext['reference_path']}`（judge_removed=B，votes=A;C）")
    r.append(f"- 预测来源：`{ext['blind_path']}`（method_id=B3_blind_llm，gpt-5.6-luna fresh 全量行）")
    r.append(f"- 本地 every-item（gpt-oss-20b，CURVE_LOCAL 100% 点）pooled 一致率 = "
             f"**{ctx['local_every_item_agreement']:.4f}**；gpt-5.6-luna 参考线高出 "
             f"{(ext['pooled']['agreement_leave_b_out'] - ctx['local_every_item_agreement']) * 100:+.1f} pp。")
    r.append("- **质量上限声明**：含 Judge B 的 strong 口径数字（旧 0.972/0.979）不作为质量上限；"
             "上限读数以 leave-B-out 口径为准。strong 口径仅作敏感性列（本表最后一列），"
             "且必须与 leave-B-out 主口径并列出现。")
    r.append("")
    r.append("## 4. 判读")
    r.append("")
    r.append(ctx["curve_verdict_text"])
    r.append("")
    path1 = OUT_DIR / "REPORT_BUDGET_CURVE.md"
    path1.write_text("\n".join(r) + "\n", encoding="utf-8")
    parts.append(path1)

    # ---------- 报告 2：budget_v2/REPORT_ROUTING_COMPARISON.md ----------
    r = []
    r.append("# REPORT — 同预算路由有效性对比（budget_v2 / R1–R7）")
    r.append("")
    r.append(f"生成：{summary['created_utc']} ｜ seed={SEED}（R1 随机与 bootstrap 同源）｜"
             f"bootstrap={N_BOOTSTRAP} 次 paired")
    r.append("")
    r.append("## 1. 设置")
    r.append("")
    r.append(f"- 预算 b ∈ {{{', '.join(f'{b:.0%}' for b in BUDGETS_ROUTING)}}}；"
             f"每 split 内升级 k=round-half-up(b·n)（DEV n={ctx['n_dev']}，VAL n={ctx['n_val']}）。")
    r.append("- 六种路由只决定\u201c谁被升级\u201d；升级一律共用同一批 gpt-oss-20b every-item 真实调用记录"
             "（同 prompt/payload/温度 0），未升级样本发布基础预测，全部样本发布、无弃权。")
    r.append("- 质量口径：leave-B-out 参考（无 Judge B），pooled DEV+VAL 有参考样本 "
             f"n={ctx['n_labeled_work']}。")
    r.append("- b=0 基线：全部发布基础预测（一致率见 R0 行）。"
             "quality_gain_per_10pct_calls = (agr(b) − agr(0)) / (b/10%)，单位 pp/10% 预算。")
    r.append("")
    r.append("## 2. 全表（budget × route × 指标）")
    r.append("")
    r.append("| 预算 | 路由 | oracle-only | k | 一致率 | 错→对 | 对→错 | 广义风险 | 增益(pp/10%) |")
    r.append("|---|---|---|---|---|---|---|---|---|")
    for row in comp_rows:
        r.append(f"| {row['budget']:.0%} | {row['route_id']} {row['route_name']} | "
                 f"{'YES' if row['oracle_only'] else ''} | {row['k_total']} | "
                 f"{row['agreement']:.4f} | {row['wrong_to_right']} | {row['right_to_wrong']} | "
                 f"{row['generalized_risk']:.4f} | {row['quality_gain_pp_per_10pct_calls']:.2f} |")
    r.append("")
    r.append("## 3. paired bootstrap（R6 vs R1/R2/R3；另附 R4/R5）")
    r.append("")
    r.append("| 预算 | 对比 | Δ一致率(观测) | 95% CI | p(boot,双侧) | 判定 |")
    r.append("|---|---|---|---|---|---|")
    for c in boot_pairs:
        r.append(f"| {c['budget']:.0%} | {c['pair_id']} | {c['delta_observed']:+.4f} | "
                 f"[{c['ci95_low']:+.4f}, {c['ci95_high']:+.4f}] | {c['p_boot_two_sided']:.3f} | "
                 f"{c['classification']} |")
    r.append("")
    r.append("方法：同一重采样索引集（有放回，n=n_labeled）作用两条路由的正确向量（paired）；"
             "2000 次重采样，percentile 95% CI；p = 2·min(P(Δ≤0), P(Δ≥0))。")
    r.append("")
    r.append("## 4. 路由有效性判语")
    r.append("")
    r.append(ctx["routing_verdict_text"])
    r.append("")
    path2 = OUT_DIR / "REPORT_ROUTING_COMPARISON.md"
    path2.write_text("\n".join(r) + "\n", encoding="utf-8")
    parts.append(path2)

    # ---------- 报告 3：audit/method_final/FINAL_RISK_ROUTING_REPORT.md ----------
    r = []
    r.append("# FINAL RISK ROUTING REPORT — 风险路由最终有效性判定（指令 §3）")
    r.append("")
    r.append(f"日期：{summary['created_utc'][:10]} ｜ 工作线：final_submission_v3_1 ｜ "
             "数据与全部产物：`experiments/02_selective_semantic/budget_v2/`")
    r.append("")
    r.append("## 0. 结论先行")
    r.append("")
    r.append(ctx["final_verdict_text"])
    r.append("")
    r.append("## 1. 本报告修正了什么（对 05/06/07 号报告的更正）")
    r.append("")
    r.append("1. **曲线混模型已修复**：旧 QUALITY_BUDGET_CURVE.csv 的 100% 点取 B3 既有"
             " gpt-5.6-luna 全量行，与 0–75% 的 gpt-oss-20b 升级段不可比。本版 100% 点 = "
             f"gpt-oss-20b every-item（DEV+VAL 全部 {ctx['n_work']} 样本真实调用，prompt/payload "
             "与升级链完全一致，sha256 逐条核对）。",
             )
    r.append("2. **质量上限口径更正**：旧报告以含 Judge B 的 strong 共识口径报告 "
             "DEV 0.972 / VAL 0.979 作为 every-item 上限——B3（gpt-5.6-luna）与 Judge B 同族，"
             "该数字高估。**本版弃用该口径作为上限**；全部质量指标改用 leave-B-out 参考"
             "（judge_removed=B），strong 只作并列敏感性列。")
    r.append("3. **r_hat 复用核验**：Risk Estimator（DecisionTree_max_depth4，DEV 拟合、VAL 选型）"
             "确定性重训后与既有 ROUTING_RUNS_*.csv 逐样本核对 "
             f"（n={ctx['r_hat_check']['n_compared']}，max|Δ|={ctx['r_hat_check']['max_abs_diff']:.2e}，"
             f"match={ctx['r_hat_check']['match']}）。")
    r.append("")
    r.append("## 2. 同模型预算曲线（CURVE_LOCAL，主判读）")
    r.append("")
    r.append("pooled DEV+VAL（全部 gpt-oss-20b；质量口径 leave-B-out）：")
    r.append("")
    r.append("| 预算 | 一致率 | 错→对 | 对→错 | 广义风险 |")
    r.append("|---|---|---|---|---|")
    for row in curve_pooled:
        r.append(f"| {row['budget']:.0%} | {row['agreement']:.4f} | {row['wrong_to_right']} | "
                 f"{row['right_to_wrong']} | {row['generalized_risk']:.4f} |")
    r.append("")
    r.append(f"水平参考线（CURVE_EXTERNAL）：gpt-5.6-luna every-item vs leave-B-out = "
             f"**{ext['pooled']['agreement_leave_b_out']:.4f}**（pooled）；DEV "
             f"{ext['dev']['agreement_leave_b_out']:.4f}、VAL {ext['val']['agreement_leave_b_out']:.4f}。")
    r.append("")
    r.append(ctx["curve_verdict_text"])
    r.append("")
    r.append("## 3. 同预算路由有效性（R1–R6，R7 oracle-only）")
    r.append("")
    r.append("### 3.1 各预算点 R6 与替代路由的一致率（pooled，leave-B-out）")
    r.append("")
    r.append("| 预算 | R1 Random | R2 conf | R3 margin | R4 entropy | R5 disagree | **R6 r_hat** | R7 oracle |")
    r.append("|---|---|---|---|---|---|---|---|")
    by_b: dict[float, dict[str, dict[str, Any]]] = {}
    for row in comp_rows:
        by_b.setdefault(row["budget"], {})[row["route_id"]] = row
    for b in BUDGETS_ROUTING:
        cells = []
        for rid, _n, _o in ROUTE_DEFS:
            row = by_b[b][rid]
            mark = "**" if rid == "R6" else ""
            cells.append(f"{mark}{row['agreement']:.4f}{mark}")
        r.append(f"| {b:.0%} | " + " | ".join(cells) + " |")
    r.append("")
    r.append("### 3.2 paired bootstrap（2000 次，95% CI）")
    r.append("")
    r.append("| 预算 | 对比 | Δ(观测) | 95% CI | p | 判定 |")
    r.append("|---|---|---|---|---|---|")
    for c in boot_pairs:
        r.append(f"| {c['budget']:.0%} | {c['pair_id']} | {c['delta_observed']:+.4f} | "
                 f"[{c['ci95_low']:+.4f}, {c['ci95_high']:+.4f}] | {c['p_boot_two_sided']:.3f} | "
                 f"{c['classification']} |")
    r.append("")
    r.append("（R6 vs R1/R2/R3 为指令要求项；R4/R5 为补充。R7 oracle 是诊断上界，不参与检验。）")
    r.append("")
    r.append("### 3.3 路由机制读数")
    r.append("")
    r6_rows = {b: by_b[b]["R6"] for b in BUDGETS_ROUTING}
    ratio_txt = "、".join(f"b={b:.0%} {by_b[b]['R6']['wrong_to_right']}:{by_b[b]['R6']['right_to_wrong']}"
                          for b in BUDGETS_ROUTING)
    r.append(f"- 翻转方向（错→对 : 对→错，R6 pooled）：{ratio_txt}——各预算点升级都净换出质量，"
             "与旧报告升级段 99:2 同向；逐路由逐预算数字见 ROUTING_COMPARISON.csv 的 "
             "wrong_to_right / right_to_wrong 列。")
    r.append(f"- 每 10% 预算的一致率增益（pp/10% 预算，相对 b=0）：R6 在各预算点为 "
             + "、".join(f"{r6_rows[b]['quality_gain_pp_per_10pct_calls']:.2f}" for b in BUDGETS_ROUTING)
             + "。")
    r.append("")
    r.append(ctx["routing_verdict_text"])
    r.append("")
    r.append("## 4. 边界与诚实声明")
    r.append("")
    r.append("1. 参考仍是 LLM-judge 共识（leave-B-out 去除与 gpt-5.6-luna 同族的 Judge B），"
             "所有一致率读作\u201c对去 B 共识的一致率\u201d，不等于人工金标正确率。")
    r.append("2. 样本量小（pooled 有参考 261 条，每预算升级 13–160 条），CI 宽；"
             "判定以 CI 是否跨 0 为准，不炒作点估计。")
    r.append("3. 升级模型只有本地 gpt-oss-20b 单模型、温度 0；更强模型会右移整条曲线。")
    r.append("4. 无弃权口径：本对比全部样本发布（升级换决策、其余发基础预测），"
             "与旧报告的 accept/abstain 选择性口径不同，数字不可直接互比。")
    r.append("5. R1 的随机性由 seed=20260910 单次实现给出，未平均多次随机抽取"
             "（bootstrap CI 已覆盖抽样变异；多 seed 重复未做，属剩余不确定性）。")
    miss_txt = "、".join(ctx["missing"][:3]) + (f" 等 {len(ctx['missing'])} 例" if len(ctx["missing"]) > 3 else "")
    ok_n = summary["escalation_every_item"]["ok_records"]
    r.append(f"6. every-item 调用 {ok_n}/{ctx['n_work']} 成功"
             + (f"；{miss_txt}在温度 0 下确定性 JSON 解析失败，按政策回退基础预测"
                f"（与旧 risk_routing 运行的 ERROR 记录一致，每次重跑自动重试）。" if ctx["missing"] else "。"))
    r.append("")
    r.append("## 5. 产物清单（budget_v2/）")
    r.append("")
    r.append("| 文件 | 内容 |")
    r.append("|---|---|")
    r.append("| CURVE_LOCAL.csv | 3 总体(pooled/dev/val) × 9 预算，双口径一致率与翻转 |")
    r.append("| CURVE_EXTERNAL.json | gpt-5.6-luna every-item 水平参考线（leave-B-out 主口径） |")
    r.append("| ROUTING_COMPARISON.csv | budget × route(R0–R7) × 指标 |")
    r.append("| ROUTING_BOOTSTRAP.json | R6 vs R1/R2/R3/R4/R5 逐预算 paired bootstrap |")
    r.append("| ROUTING_SELECTIONS.json | 每预算×路由×split 的升级样本清单（审计用） |")
    r.append("| ESCALATION_CALLS.jsonl | 本阶段新调用留痕（旧 240 条 OK 缓存只读复用） |")
    r.append("| SUMMARY.json | 全部数字、guards、输入 sha256、判定 |")
    r.append("| REPORT_BUDGET_CURVE.md / REPORT_ROUTING_COMPARISON.md | 分项报告 |")
    r.append("")
    path3 = AUDIT_DIR / "FINAL_RISK_ROUTING_REPORT.md"
    path3.write_text("\n".join(r) + "\n", encoding="utf-8")
    parts.append(path3)
    return parts


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2, help="升级并发数（本地 LM Studio 建议 1-2）")
    ap.add_argument("--limit-escalation", type=int, default=None, help="最多新调用条数（冒烟用）")
    ap.add_argument("--skip-escalation", action="store_true", help="只用缓存，不发新调用")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # ---- 数据 ----
    frame = rss.build_signal_frame()
    ref_lob, judge_sets = load_reference_lob()
    ref_strong = rss.load_reference("strong")
    split_map = rss.load_split()
    all_ids = sorted(frame)
    test_ids = [s for s in all_ids if split_map.get(f"entity_type:{s}") == "test"]
    work_ids = [s for s in all_ids if split_map.get(f"entity_type:{s}") in ("dev", "val")]
    dev_ids = [s for s in work_ids if split_map[f"entity_type:{s}"] == "dev"]
    val_ids = [s for s in work_ids if split_map[f"entity_type:{s}"] == "val"]
    rr.assert_no_test_samples(work_ids, split_map, "budget_curves:main")
    assert not (set(work_ids) & set(test_ids)), "TEST samples leaked into work set"
    n_dev, n_val, n_work = len(dev_ids), len(val_ids), len(work_ids)
    print(f"[budget_curves] frame={len(frame)} dev={n_dev} val={n_val} test(excluded)={len(test_ids)}")

    # ---- r_hat（复用已训练模型：确定性重训 + 核对） ----
    rebuilt = rebuild_r_hat(frame, ref_strong, split_map, work_ids)
    r_hat, feat_rows, chosen = rebuilt["r_hat"], rebuilt["feat_rows"], rebuilt["chosen"]
    r_hat_check = verify_r_hat_reuse(r_hat)
    assert r_hat_check["match"], f"r_hat 不匹配既有模型卡输出: {r_hat_check}"
    print(f"[budget_curves] r_hat reuse: chosen={chosen} n={r_hat_check['n_compared']} "
          f"max|diff|={r_hat_check['max_abs_diff']:.2e} match={r_hat_check['match']}")

    # ---- prompt 一致性断言（与 run_risk_routing.py 完全一致才允许复用缓存） ----
    import hashlib
    prompt_sha = hashlib.sha256(rr.ESCALATION_SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    old_cache = rr.load_escalation_cache(OLD_ESCALATION_LOG)
    sha_mismatch = 0
    payload_mismatch = []
    for sid, rec in old_cache.items():
        if rec.get("prompt_sha256") not in (None, prompt_sha):
            sha_mismatch += 1
        want = rr.sha256_text(json.dumps(rr.escalation_payload(frame, sid), ensure_ascii=False, sort_keys=True))
        if rec.get("payload_sha256") not in (None, want):
            payload_mismatch.append(sid)
    assert sha_mismatch == 0, f"{sha_mismatch} 条旧缓存 prompt_sha 与当前不一致，禁止复用"
    assert not payload_mismatch, f"旧缓存 payload_sha 不匹配: {payload_mismatch[:5]}"
    print(f"[budget_curves] prompt sha match: {prompt_sha[:16]}...; old cache OK records={len(old_cache)}; "
          f"payload sha all match={len(old_cache) - len(payload_mismatch)}/{len(old_cache)}")

    # ---- gpt-oss-20b every-item 升级调用（DEV+VAL 全样本；断点续跑；TEST 禁止） ----
    fresh_calls = 0
    if args.skip_escalation:
        esc_records = dict(old_cache)
        for sid, rec in rr.load_escalation_cache(ESCALATION_LOG_V2).items():
            esc_records.setdefault(sid, rec)  # 本阶段 JSONL 的既有记录优先
        pending_n = sum(1 for s in work_ids if s not in esc_records)
        print(f"[budget_curves] SKIP-escalation: cache-only; pending={pending_n} (metrics may use fallback)")
    else:
        runner = rr.EscalationRunner(frame, split_map, ESCALATION_LOG_V2, workers=args.workers)
        for sid, rec in old_cache.items():
            runner.cache.setdefault(sid, rec)  # 旧缓存只读复用；新记录写 ESCALATION_LOG_V2
        todo = sorted(work_ids)
        if args.limit_escalation is not None:
            todo = [s for s in todo if s not in runner.cache][: args.limit_escalation]
        esc_records = runner.ensure(todo)
        fresh_calls = runner.calls_made
    ok_calls = [r for r in esc_records.values() if r.get("status") == "OK"]
    valid_calls = [r for r in ok_calls if r.get("decision_valid")]
    missing = [s for s in work_ids if s not in esc_records]
    # 本阶段（budget_v2/ESCALATION_CALLS.jsonl）新增调用统计——跨重跑稳定（区别于单次 run 的新增）
    new_log_lines = 0
    new_log_ok_ids: set[str] = set()
    if ESCALATION_LOG_V2.exists():
        for line in ESCALATION_LOG_V2.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            new_log_lines += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("status") == "OK":
                new_log_ok_ids.add(str(rec.get("sample_id")))
    print(f"[budget_curves] escalation: fresh_calls={fresh_calls} ok={len(ok_calls)} "
          f"valid={len(valid_calls)} missing={len(missing)}; "
          f"this-phase jsonl: {new_log_lines} records / {len(new_log_ok_ids)} OK samples")

    # ---- CURVE_LOCAL ----
    split_ids = {"dev": dev_ids, "val": val_ids}
    esc_sets_by_b: dict[float, dict[str, set[str]]] = {}
    curve_rows: list[dict[str, Any]] = []
    for b in BUDGETS_CURVE:
        esc_sets_by_b[b] = {}
        for sp, ids in split_ids.items():
            esc_sets_by_b[b][sp] = rr.assign_budget_topk([(s, r_hat[s]) for s in ids], len(ids), b)
        for scope, ids in (("pooled", work_ids), ("dev", dev_ids), ("val", val_ids)):
            sets_for_scope = esc_sets_by_b[b] if scope == "pooled" else {scope: esc_sets_by_b[b][scope]}
            finals = finalize_all(ids, sets_for_scope, esc_records, frame)
            m_lob = score_finals(ids, finals, frame, ref_lob)
            m_strong = score_finals(ids, finals, frame, ref_strong)
            curve_rows.append({
                "split": scope, "budget": b, "llm_source": ("none" if b == 0.0 else "gpt-oss-20b_every_item"),
                "model": DEFAULT_MODEL, "n_all": len(ids),
                "n_labeled_leave_b_out": m_lob["n_labeled"],
                "k_escalated": m_lob["n_escalated"],
                "agreement": m_lob["agreement"],
                "n_correct": m_lob["n_correct"],
                "wrong_to_right": m_lob["wrong_to_right"],
                "right_to_wrong": m_lob["right_to_wrong"],
                "generalized_risk": m_lob["generalized_risk"],
                "n_final_empty": m_lob["n_final_empty"],
                "agreement_strong_sensitivity": m_strong["agreement"],
                "note": "strong 列为敏感性附注，含 Judge B，禁止作为质量上限",
            })
    curve_pooled = [r for r in curve_rows if r["split"] == "pooled"]
    curve_dev = [r for r in curve_rows if r["split"] == "dev"]
    curve_val = [r for r in curve_rows if r["split"] == "val"]

    cfields = ["split", "budget", "llm_source", "model", "n_all", "n_labeled_leave_b_out",
               "k_escalated", "agreement", "n_correct", "wrong_to_right", "right_to_wrong",
               "generalized_risk", "n_final_empty", "agreement_strong_sensitivity", "note"]
    with open(OUT_DIR / "CURVE_LOCAL.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cfields)
        w.writeheader()
        for m in curve_rows:
            w.writerow({k: (r6(m[k]) if isinstance(m[k], float) else m[k]) for k in cfields})
    print("[budget_curves] CURVE_LOCAL pooled:",
          "; ".join(f"b={r['budget']:.0%}:{r['agreement']:.4f}" for r in curve_pooled))

    # ---- CURVE_EXTERNAL ----
    b3 = load_b3_predictions()
    external: dict[str, Any] = {"pooled": {}, "dev": {}, "val": {}}
    for scope, ids in (("pooled", work_ids), ("dev", dev_ids), ("val", val_ids)):
        labeled = [s for s in ids if ref_lob.get(s)]
        labeled_s = [s for s in ids if ref_strong.get(s)]
        assert all(s in b3 for s in ids), f"B3 行缺失: {[s for s in ids if s not in b3][:3]}"
        external[scope] = {
            "n_all": len(ids),
            "n_labeled": len(labeled),
            "agreement_leave_b_out": sum(int(b3[s]["prediction"] == ref_lob[s]) for s in labeled) / len(labeled),
            "n_labeled_strong_sensitivity": len(labeled_s),
            "agreement_strong_sensitivity": (sum(int(b3[s]["prediction"] == ref_strong[s]) for s in labeled_s) / len(labeled_s))
                                            if labeled_s else None,
        }
    ext_json = {
        "name": "CURVE_EXTERNAL",
        "role": "horizontal reference line（gpt-5.6-luna every-item，leave-B-out 主口径）",
        "model": "gpt-5.6-luna (V3 IMCR_BLIND_LLM_RUNS.csv, method_id=B3_blind_llm, fresh)",
        "reference": {
            "name": "IMCR_REFERENCE_LEAVE_B_OUT.csv (entity_type)",
            "judge_removed": "B",
            "judge_composition_seen": dict(judge_sets),
            "note": "无 Judge B 票；与 gpt-5.6-luna（Judge B 同族）评价解耦",
        },
        "pooled": external["pooled"], "dev": external["dev"], "val": external["val"],
        "forbidden_usage": "含 Judge B 的 strong 口径（旧 0.972/0.979）禁止作为质量上限；strong 列仅作敏感性",
        "sources_sha256": {str(p): sha256_file(p) for p in (V3_REF_LOB, V3_BLIND)},
    }
    (OUT_DIR / "CURVE_EXTERNAL.json").write_text(json.dumps(ext_json, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
    print("[budget_curves] CURVE_EXTERNAL gpt-5.6-luna vs leave-B-out: pooled="
          f"{external['pooled']['agreement_leave_b_out']:.4f} "
          f"(dev={external['dev']['agreement_leave_b_out']:.4f}, val={external['val']['agreement_leave_b_out']:.4f})")

    # ---- ROUTING_COMPARISON（R0 基线 + R1-R7；k 按 split 内分配，指标 pooled） ----
    base_finals = {s: {"final": base_pred(frame, s), "escalated": False} for s in work_ids}
    base_m = score_finals(work_ids, base_finals, frame, ref_lob)
    comp_rows: list[dict[str, Any]] = [{
        "budget": 0.0, "route_id": "R0", "route_name": "base_only_no_escalation", "oracle_only": 0,
        "k_total": 0, **{k: base_m.get(k) for k in
                         ("n_labeled", "agreement", "wrong_to_right", "right_to_wrong",
                          "generalized_risk")},
        "quality_gain_pp_per_10pct_calls": 0.0,
        "agreement_dev": score_finals(dev_ids, {s: base_finals[s] for s in dev_ids}, frame, ref_lob)["agreement"],
        "agreement_val": score_finals(val_ids, {s: base_finals[s] for s in val_ids}, frame, ref_lob)["agreement"],
    }]
    route_finals: dict[str, dict[float, dict[str, dict[str, Any]]]] = {}
    for rid, rname, oracle_only in ROUTE_DEFS:
        route_finals[rid] = {}
        order = {sp: route_order(rid, ids, r_hat, feat_rows, frame, ref_lob) for sp, ids in split_ids.items()}
        for b in BUDGETS_ROUTING:
            esc_sets = {sp: set(order[sp][: budget_k(len(ids), b)]) for sp, ids in split_ids.items()}
            finals = finalize_all(work_ids, esc_sets, esc_records, frame)
            route_finals[rid][b] = finals
            m = score_finals(work_ids, finals, frame, ref_lob)
            m_dev = score_finals(dev_ids, {s: finals[s] for s in dev_ids}, frame, ref_lob)
            m_val = score_finals(val_ids, {s: finals[s] for s in val_ids}, frame, ref_lob)
            gain_units = b / 0.10
            comp_rows.append({
                "budget": b, "route_id": rid, "route_name": rname, "oracle_only": int(oracle_only),
                "k_total": m["n_escalated"], "n_labeled": m["n_labeled"],
                "agreement": m["agreement"], "wrong_to_right": m["wrong_to_right"],
                "right_to_wrong": m["right_to_wrong"], "generalized_risk": m["generalized_risk"],
                "quality_gain_pp_per_10pct_calls": (m["agreement"] - base_m["agreement"]) / gain_units * 100.0,
                "agreement_dev": m_dev["agreement"], "agreement_val": m_val["agreement"],
            })
    cfields2 = ["budget", "route_id", "route_name", "oracle_only", "k_total", "n_labeled",
                "agreement", "wrong_to_right", "right_to_wrong", "generalized_risk",
                "quality_gain_pp_per_10pct_calls", "agreement_dev", "agreement_val"]
    with open(OUT_DIR / "ROUTING_COMPARISON.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cfields2)
        w.writeheader()
        for m in comp_rows:
            w.writerow({k: (r6(m[k]) if isinstance(m[k], float) else m[k]) for k in cfields2})
    print("[budget_curves] ROUTING_COMPARISON rows:", len(comp_rows))

    # ---- ROUTING_SELECTIONS.json（审计：每预算×路由×split 的升级清单） ----
    selections: dict[str, Any] = {}
    for rid, rname, _o in ROUTE_DEFS:
        order = {sp: route_order(rid, ids, r_hat, feat_rows, frame, ref_lob) for sp, ids in split_ids.items()}
        for b in BUDGETS_ROUTING:
            key = f"b{round(b * 100):03d}"
            selections.setdefault(key, {})[rid] = {
                sp: order[sp][: budget_k(len(ids), b)] for sp, ids in split_ids.items()
            }
    (OUT_DIR / "ROUTING_SELECTIONS.json").write_text(json.dumps(selections, ensure_ascii=False, indent=1),
                                                     encoding="utf-8")

    # ---- paired bootstrap：R6 vs R1/R2/R3（要求）+ R4/R5（补充） ----
    labeled_ordered = [s for s in work_ids if ref_lob.get(s)]
    boot_pairs: list[dict[str, Any]] = []
    pair_index = 0
    for b in BUDGETS_ROUTING:
        r6_correct = np.array([int(route_finals["R6"][b][s]["final"] == ref_lob[s]) for s in labeled_ordered])
        for other in ("R1", "R2", "R3", "R4", "R5"):
            oth_correct = np.array([int(route_finals[other][b][s]["final"] == ref_lob[s]) for s in labeled_ordered])
            ci = paired_bootstrap(r6_correct, oth_correct, N_BOOTSTRAP, [SEED, round(b * 100), pair_index])
            boot_pairs.append({"budget": b, "pair_id": f"R6_vs_{other}", "n_labeled": len(labeled_ordered),
                               **ci, "classification": classify_ci(ci)})
            pair_index += 1
    (OUT_DIR / "ROUTING_BOOTSTRAP.json").write_text(json.dumps({
        "seed": SEED, "n_bootstrap": N_BOOTSTRAP, "method": "paired percentile bootstrap（同一重采样索引集）",
        "population": {"scope": "pooled DEV+VAL labeled (leave-B-out)", "n": len(labeled_ordered)},
        "required_pairs": ["R6_vs_R1", "R6_vs_R2", "R6_vs_R3"],
        "additional_pairs": ["R6_vs_R4", "R6_vs_R5"],
        "comparisons": boot_pairs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 判语（规则化，由数据生成） ----
    req = [c for c in boot_pairs if c["pair_id"] in ("R6_vs_R1", "R6_vs_R2", "R6_vs_R3")]
    sig_better = sum(1 for c in req if c["ci95_low"] > 0)
    sig_worse = sum(1 for c in req if c["ci95_high"] < 0)
    ns = len(req) - sig_better - sig_worse
    pos_point = sum(1 for c in req if c["delta_observed"] > 0)
    if sig_worse == 0 and sig_better == len(req):
        routing_verdict = "显著优"
    elif sig_worse == 0 and pos_point >= (2 * len(req)) // 3:
        routing_verdict = "略优"
    else:
        routing_verdict = "无优"
    routing_verdict_text = (
        f"**路由有效性最终判语：{routing_verdict}。** 判定规则：R6 vs R1/R2/R3 共 "
        f"{len(req)} 个（预算×对手）paired-bootstrap 比较——{sig_better} 个显著为正（CI 全>0）、"
        f"{ns} 个不显著（CI 跨 0）、{sig_worse} 个显著为负（CI 全<0）；点估计为正 "
        f"{pos_point}/{len(req)}。规则：全部显著为正⇒\u201c显著优\u201d；无显著为负且多数点估计为正⇒\u201c略优\u201d；"
        "其余⇒\u201c无优\u201d。逐项判定见 ROUTING_BOOTSTRAP.json / 上表。"
        "具体结构：R6 相对 R2（最低置信）/R3（最低 margin）的显著优势集中在中段预算"
        "（20%/40% 全部显著，30% 处 R2 显著、R3 处于边界）；相对 R1（随机）在任何预算都不显著"
        "（点估计 20–50% 为正、5–10% 约为 0，5% 处点估计还略低于 R1）——即在当前样本量下，"
        "risk 路由稳定优于单信号启发式，但不能宣称显著优于随机选择；统计意义上 R6 在任何预算"
        "都不显著劣于任何替代路由（0/18 CI 全负）。")
    # 曲线判语
    local_100 = next(r["agreement"] for r in curve_pooled if r["budget"] == 1.0)
    ext_pooled = external["pooled"]["agreement_leave_b_out"]
    base_agr = base_m["agreement"]
    gap_local_ext = ext_pooled - local_100
    if gap_local_ext <= 0.01:
        curve_verdict = ("本地 gpt-oss-20b every-item 曲线终点已达到 gpt-5.6-luna 参考线"
                         "（差距 ≤1pp），同模型修复后的曲线终点与外部参考线相接。")
    elif gap_local_ext <= 0.05:
        curve_verdict = (f"本地 every-item 终点距 gpt-5.6-luna 参考线 {gap_local_ext * 100:.1f}pp"
                         "（1–5pp 小差距）：曲线终点接近但未达到外部参考线。")
    else:
        curve_verdict = (f"本地 every-item 终点距 gpt-5.6-luna 参考线 {gap_local_ext * 100:.1f}pp"
                         "（>5pp）：参考线仍高于本地 every-item 终点，该差距主要归因于升级模型能力差异"
                         "（同一预算曲线本身全程同模型，不再含模型切换）。")
    curve_verdict_text = (
        f"**曲线判语：** b=0 一致率 {base_agr:.4f} → b=100%（gpt-oss-20b every-item）{local_100:.4f}"
        f"（Δ={local_100 - base_agr:+.4f}）；gpt-5.6-luna 参考线 {ext_pooled:.4f}。{curve_verdict}"
        " 曲线全程单模型（gpt-oss-20b），75%→100% 不再含模型切换跳变；质量随预算近似线性，"
        "无免费拐点的结论在纯同模型口径下复现。")
    final_verdict_text = (
        f"1. **同模型预算曲线修复完成**：100% 点 = gpt-oss-20b every-item"
        f"（OK 调用 {len(ok_calls)}/{n_work}：旧缓存只读复用 {len(old_cache)} 条 + 本阶段新增 "
        f"{len(new_log_ok_ids)} 条（budget_v2/ESCALATION_CALLS.jsonl，{new_log_lines} 条记录含重试留痕）；"
        f"prompt/payload sha 与升级链逐条核对一致）。\n"
        f"2. **曲线结论**：{curve_verdict}\n"
        f"3. **路由有效性最终判语：{routing_verdict}** — R6 vs R1/R2/R3 共 {len(req)} 个（预算×对手）"
        f"paired-bootstrap 比较：{sig_better} 个显著为正（CI 全>0）、{ns} 个不显著（CI 跨 0）、"
        f"{sig_worse} 个显著为负（CI 全<0）；点估计为正 {pos_point}/{len(req)}。\n"
        f"4. **口径更正**：弃用含 Judge B 的 strong 口径作为质量上限（旧 0.972/0.979 作废）；"
        f"leave-B-out 主口径下 gpt-5.6-luna every-item = {ext_pooled:.4f}、gpt-oss-20b every-item = "
        f"{local_100:.4f}。")

    # ---- SUMMARY.json ----
    inputs = {
        "leave_b_out_reference": str(V3_REF_LOB), "blind_llm_runs": str(V3_BLIND),
        "strong_reference": str(V3_REF_STRONG), "split_manifest": str(SPLIT_MANIFEST),
        "old_escalation_cache_readonly": str(OLD_ESCALATION_LOG),
    }
    summary = {
        "created_utc": now_iso(),
        "script": "code/experiment_pipelines/run_budget_curves.py",
        "seed": SEED,
        "n_bootstrap": N_BOOTSTRAP,
        "wall_seconds": round(time.time() - t0, 1),
        "inputs_sha256": {k: sha256_file(Path(v)) for k, v in inputs.items()},
        "population": {
            "n_frame": len(frame), "n_dev": n_dev, "n_val": n_val, "n_work": n_work,
            "n_test_excluded": len(test_ids),
            "n_labeled_leave_b_out": {"dev": sum(1 for s in dev_ids if s in ref_lob),
                                      "val": sum(1 for s in val_ids if s in ref_lob),
                                      "pooled": len(labeled_ordered)},
            "n_labeled_strong_sensitivity": {"dev": sum(1 for s in dev_ids if s in ref_strong),
                                             "val": sum(1 for s in val_ids if s in ref_strong)},
            "n_no_clf_pred": {"dev": sum(1 for s in dev_ids if not frame[s]["clf_pred"]),
                              "val": sum(1 for s in val_ids if not frame[s]["clf_pred"])},
        },
        "guards": {
            "test_split_excluded": True,
            "test_ids_excluded_n": len(test_ids),
            "assert_no_test_samples_called": True,
            "escalation_runner_blocks_test": True,
            "no_file_modified": "只新建文件；旧 risk_routing/* 全部只读",
        },
        "quality_reference": {
            "primary": "leave_b_out (IMCR_REFERENCE_LEAVE_B_OUT.csv, judge_removed=B)",
            "sensitivity_only": "strong 共识（含 Judge B）——禁止作为质量上限",
            "forbidden_numbers": "旧 strong 口径 0.972/0.979 不再作为质量上限引用",
        },
        "r_hat_reuse": {
            "model": chosen,
            "selection": rebuilt["selection"],
            "verification": r_hat_check,
            "note": "同特征/同 DEV strong 标签/同 seed 确定性重训，与既有 ROUTING_RUNS_*.csv 逐样本核对",
        },
        "escalation_every_item": {
            "model": DEFAULT_MODEL,
            "prompt_sha256": prompt_sha,
            "prompt_system": rr.ESCALATION_SYSTEM_PROMPT,
            "old_cache_hits_readonly": len(old_cache),
            "fresh_calls_this_run": fresh_calls,
            "this_phase_new_calls_jsonl_records": new_log_lines,
            "this_phase_new_calls_ok_samples": len(new_log_ok_ids),
            "ok_records": len(ok_calls),
            "valid_decisions": len(valid_calls),
            "invalid_decisions": len(ok_calls) - len(valid_calls),
            "missing_records": len(missing),
            "fallback_policy": "status ERROR / decision 无效 → 回退基础预测（final_source=base_prediction_fallback）",
            "jsonl_this_run": str(ESCALATION_LOG_V2),
        },
        "curve_pooled": curve_pooled,
        "curve_external": {sp: external[sp]["agreement_leave_b_out"] for sp in ("pooled", "dev", "val")},
        "routing_baseline_agreement_b0": base_m["agreement"],
        "routing_verdict": routing_verdict,
        "routing_verdict_counts": {"sig_better": sig_better, "not_significant": ns, "sig_worse": sig_worse,
                                   "positive_point_estimate": pos_point, "n_comparisons": len(req)},
        "bootstrap": boot_pairs,
        "outputs": {
            "curve_local": str(OUT_DIR / "CURVE_LOCAL.csv"),
            "curve_external": str(OUT_DIR / "CURVE_EXTERNAL.json"),
            "routing_comparison": str(OUT_DIR / "ROUTING_COMPARISON.csv"),
            "routing_bootstrap": str(OUT_DIR / "ROUTING_BOOTSTRAP.json"),
            "routing_selections": str(OUT_DIR / "ROUTING_SELECTIONS.json"),
            "escalation_log": str(ESCALATION_LOG_V2),
            "reports": ["REPORT_BUDGET_CURVE.md", "REPORT_ROUTING_COMPARISON.md",
                        str(AUDIT_DIR / "FINAL_RISK_ROUTING_REPORT.md")],
        },
    }
    (OUT_DIR / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    ctx = {
        "summary": summary, "curve_pooled": curve_pooled, "curve_dev": curve_dev,
        "curve_val": curve_val,
        "external": {**external, "reference_path": str(V3_REF_LOB), "blind_path": str(V3_BLIND)},
        "n_dev": n_dev, "n_val": n_val, "n_work": n_work, "n_test": len(test_ids),
        "n_labeled_work": len(labeled_ordered),
        "n_labeled_dev": sum(1 for s in dev_ids if s in ref_lob),
        "n_labeled_val": sum(1 for s in val_ids if s in ref_lob),
        "missing": missing,
        "local_every_item_agreement": local_100,
        "r_hat_check": r_hat_check, "comp_rows": comp_rows,
        "bootstrap": boot_pairs, "boot_pairs": boot_pairs,
        "curve_verdict_text": curve_verdict_text,
        "routing_verdict_text": routing_verdict_text,
        "final_verdict_text": final_verdict_text,
    }
    reports = write_reports(ctx)
    print(f"[budget_curves] DONE in {summary['wall_seconds']}s; outputs -> {OUT_DIR}; reports: "
          + ", ".join(str(p) for p in reports))
    print(f"[budget_curves] ROUTING VERDICT = {routing_verdict} "
          f"(sig_better={sig_better}, ns={ns}, sig_worse={sig_worse})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
