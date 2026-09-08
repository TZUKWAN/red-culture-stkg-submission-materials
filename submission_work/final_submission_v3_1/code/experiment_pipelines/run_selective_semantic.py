# -*- coding: utf-8 -*-
"""run_selective_semantic.py — P0-2/P0-4：链 A（Selective Semantic Prediction）。

评价对象：系统真实执行的语义预测任务（entity_type，382 规范实体）。
方法变体（第三章选择机制组件逐一消融，其余冻结）：

    S0  Full Selective Semantic Controller（完整：规则优先融合 + isotonic 校准 +
        类特异性阈值 theta_c + 证据一致性 + 反向冲突抑制 + 结构准入 + 弃权）
    S1  w/o 类特异性可靠门（全局单阈值替代 theta_c）
    S2  w/o 附加证据一致性（移除 rule-clf agreement 信号与规则融合）
    S3  w/o 词法/规则反向冲突抑制（不做 contraindication 否决）
    S4  w/o 弃权（theta=0，凡有预测必接受）
    S5  w/o 结构准入（不做 TYPE_FAMILY/contraindication 硬门）
    S6  Rule-only            S7  Classifier-only      S8  Blind-LLM-only
    S9  Rule+Classifier      S10 Rule+Blind-LLM

数据：信号取自 V3 冻结基线行（B1 规则 / B2 分类器 proba / B7 margin——确定性生产
组件重放）+ v3_1 新 B3 nemotron 盲 LLM fresh 行；参考 = IMCR strong（无 nemotron 票）。
切分：book-grouped 冻结切分；theta_c/校准只在 DEV 上学习，VAL 观察，TEST 由
--split test 显式运行（须已存在 TEST_FROZEN 守门文件）。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"
for p in (
    str(V3 / "code"),
    str(V3 / "code" / "independent_eval"),
    str(V3 / "code" / "experiment_pipelines"),
    str(Path(__file__).resolve().parent.parent / "independent_eval"),
    str(Path(__file__).resolve().parent),
):
    if p not in sys.path:
        sys.path.insert(0, p)

from selective_stats import (  # noqa: E402
    coverage_at_risk,
    risk_at_coverage,
    rows_to_points,
)

sys.path.insert(0, str(V3 / "data" / "external_inputs"))
import stkg_v2_semantics as sem  # noqa: E402

V3_RUNS = V3 / "experiments" / "09_independent_baselines" / "IMCR_BASELINE_RUNS.csv"
V3_REF_STRONG = V3 / "experiments" / "08_independent_reference" / "IMCR_REFERENCE_STRONG.csv"
V3_REF_ALL = V3 / "experiments" / "08_independent_reference" / "IMCR_REFERENCE_ALL.csv"
SAMPLE = V3 / "experiments" / "08_independent_reference" / "ENTITY_TYPE_SAMPLE.csv"
SIDECAR = V3 / "experiments" / "08_independent_reference" / "ENTITY_TYPE_SAMPLE.sampling_metadata.csv"
B3_RUNS = V3_1 / "experiments" / "02_selective_semantic" / "blind_llm_runs" / "entity_type.jsonl"
SPLIT_MANIFEST = V3_1 / "data" / "frozen_splits" / "SPLIT_MANIFEST.json"
OUT_DIR = V3_1 / "experiments" / "02_selective_semantic"

LAMBDA_RISK = 1.0
LAMBDA_VIOLATION = 2.0
GLOBAL_SEED = 20260908


# ---------------------------------------------------------------------------
# 数据装载
# ---------------------------------------------------------------------------

def load_runs_by_method() -> dict[str, dict[str, dict[str, str]]]:
    rows = list(csv.DictReader(open(V3_RUNS, encoding="utf-8-sig")))
    out: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for r in rows:
        if r["task_type"] == "entity_type" and r["availability_status"] == "available":
            out[r["method_id"]].setdefault(r["sample_id"], r)
    return out


def load_reference(mode: str) -> dict[str, str]:
    path = V3_REF_STRONG if mode == "strong" else V3_REF_ALL
    ref = {}
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        if r["task_type"] == "entity_type" and r["reference_label"]:
            ref[r["sample_id"]] = r["reference_label"]
    return ref


def load_b3_rows() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not B3_RUNS.exists():
        return out
    for line in B3_RUNS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("status") == "OK" and rec.get("parsed_response"):
            sid = str(rec["task_id"])
            if sid not in out:  # 首次 OK 为准
                out[sid] = {
                    "prediction": str(rec["parsed_response"].get("decision") or ""),
                    "confidence": float(rec["parsed_response"].get("confidence") or 0.0),
                }
    return out


def load_entity_meta() -> dict[str, dict[str, str]]:
    names = {r["sample_id"]: r for r in csv.DictReader(open(SAMPLE, encoding="utf-8-sig"))}
    side = {r["sample_id"]: r for r in csv.DictReader(open(SIDECAR, encoding="utf-8-sig"))}
    return {k: {**names.get(k, {}), **side.get(k, {})} for k in names}


def load_split() -> dict[str, str]:
    m = json.loads(SPLIT_MANIFEST.read_text(encoding="utf-8"))
    return {k: v for k, v in m["assignment"].items() if k.startswith("entity_type:")}


# ---------------------------------------------------------------------------
# 信号帧
# ---------------------------------------------------------------------------

def build_signal_frame() -> dict[str, dict[str, Any]]:
    runs = load_runs_by_method()
    meta = load_entity_meta()
    b3 = load_b3_rows()
    from _common import connect_final
    con = connect_final()
    member_types: dict[str, str] = {}
    ent_src: dict[str, list[str]] = defaultdict(list)
    for canon, src_id in con.execute("select canonical_entity_id, source_entity_id from research_entity_members"):
        ent_src[str(canon)].append(str(src_id))
    for canon, srcs in ent_src.items():
        types = [str(t) for (t,) in con.execute(
            "select source_entity_type from sem.v2_entities where entity_id=?", (srcs[0],)
        ).fetchall() if t]
        if types:
            member_types[canon] = types[0]
    frame: dict[str, dict[str, Any]] = {}
    for sid, m in meta.items():
        rule = runs.get("B1_rule_only", {}).get(sid)
        clf = runs.get("B2_frozen_classifier", {}).get(sid)
        margin = runs.get("B7_classifier_margin", {}).get(sid)
        name = str(m.get("canonical_name") or "")
        eid = str(m.get("entity_id") or "")
        primary_source_type = member_types.get(eid, "")
        contra_pred: dict[str, bool] = {}
        frame[sid] = {
            "name": name,
            "production_type": str(m.get("production_entity_type") or ""),
            "validated": str(m.get("type_validation_status") or "") == "validated",
            "rule_pred": (rule or {}).get("prediction", "") or None,
            "rule_conf": float(rule["confidence"]) if rule and rule.get("confidence") else None,
            "clf_pred": (clf or {}).get("prediction", "") or None,
            "clf_conf": float(clf["confidence"]) if clf and clf.get("confidence") else None,
            "clf_margin": float(margin["confidence"]) if margin and margin.get("confidence") else None,
            "llm_pred": b3.get(sid, {}).get("prediction"),
            "llm_conf": b3.get(sid, {}).get("confidence"),
            "contra_cache": contra_pred,
            "meta": m,
            "_primary_source_type": primary_source_type,
        }
    return frame


def contra(frame: dict[str, Any], sid: str, pred: str) -> bool:
    """词法/规则反向冲突抑制：entity_model_contraindication 非空即冲突（按样本缓存）。"""
    cache = frame[sid]["contra_cache"]
    if pred not in cache:
        name = frame[sid]["name"]
        stype = frame[sid]["_primary_source_type"]
        try:
            res = sem.entity_model_contraindication(name, stype, pred)
        except Exception:
            res = ""
        cache[pred] = bool(res)
    return cache[pred]


def structural_ok(frame: dict[str, Any], sid: str, pred: str) -> bool:
    """结构准入：TYPE_FAMILY 成员 + 无 contraindication。"""
    tf = getattr(sem, "TYPE_FAMILY", {})
    if tf and pred not in tf:
        return False
    return not contra(frame, sid, pred)


# ---------------------------------------------------------------------------
# 校准与阈值学习（只允许在 DEV 上执行）
# ---------------------------------------------------------------------------

def isotonic_fit(pairs: list[tuple[float, int]], bins: int = 10) -> list[tuple[float, float]]:
    """简单 PAV 风格分箱保序回归：返回 (bin 上界, 校准值) 表。"""
    pairs = sorted(pairs)
    if not pairs:
        return [(1.0, 0.5)]
    n = len(pairs)
    size = max(1, n // bins)
    table = []
    i = 0
    while i < n:
        chunk = pairs[i : i + size]
        table.append((chunk[-1][0], sum(c for _, c in chunk) / len(chunk)))
        i += size
    # PAV 后向合并违反单调的箱
    for j in range(1, len(table)):
        if table[j][1] < table[j - 1][1]:
            merged_v = (table[j - 1][1] + table[j][1]) / 2
            table[j - 1] = (table[j][0], merged_v)
            table[j] = (table[j][0], merged_v)
    return table


def isotonic_apply(table: list[tuple[float, float]], x: float) -> float:
    for hi, v in table:
        if x <= hi + 1e-12:
            return v
    return table[-1][1] if table else x


def utility(preds: list[dict[str, Any]], lam_risk: float, lam_viol: float) -> float:
    accepted = [p for p in preds if p["accepted"]]
    safe = sum(1 for p in accepted if p["correct"] == 1 and p["gate_violation"] == 0)
    n = len(preds) or 1
    errors = sum(1 for p in accepted if p["correct"] == 0)
    violations = sum(1 for p in accepted if p["gate_violation"] == 1)
    return safe / n - lam_risk * errors / n - lam_viol * violations / n


COVERAGE_FLOOR = 0.30


def learn_threshold(rows: list[dict[str, Any]], coverage_floor: float = COVERAGE_FLOOR) -> float:
    """DEV 上网格搜索 theta：满足 coverage>=floor 的约束下最大化 utility。

    无满足下限的 theta 时回退最小 theta（给出可行域内最大 coverage）。
    """
    best_theta, best_u = None, -math.inf
    floor_theta, floor_cov = None, -1.0
    for theta in [round(0.05 * i, 2) for i in range(1, 21)]:
        trial = [dict(r, accepted=(r["score"] is not None and r["score"] >= theta)) for r in rows]
        cov = sum(t["accepted"] for t in trial) / len(rows) if rows else 0.0
        u = utility(trial, LAMBDA_RISK, LAMBDA_VIOLATION)
        if cov >= coverage_floor and u > best_u:
            best_u, best_theta = u, theta
        if cov > floor_cov:
            floor_cov, floor_theta = cov, theta
    return best_theta if best_theta is not None else (floor_theta or 0.0)


# ---------------------------------------------------------------------------
# 变体构造
# ---------------------------------------------------------------------------

def compose_s_variants(frame: dict[str, Any], calib_table, theta_c: dict[str, float], theta_global: float) -> dict[str, list[dict[str, Any]]]:
    """按变体语义生成逐样本行。所有行统一字段：
    sample_id, prediction, score, accepted, correct, gate_violation, gate_reason。
    correct 由调用方对照参考后回填（此处先置 0）。"""
    variants: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def base_row(sid: str, pred: str | None, score: float | None, accepted: bool, reason: str, violation: int) -> dict[str, Any]:
        return {
            "sample_id": sid,
            "prediction": pred or "",
            "score": score,
            "accepted": int(bool(accepted and pred)),
            "correct": 0,
            "gate_violation": violation,
            "gate_reason": reason,
        }

    for sid, f in frame.items():
        rule_p, clf_p, llm_p = f["rule_pred"], f["clf_pred"], f["llm_pred"]
        rule_conf = f["rule_conf"] or 0.0
        clf_raw = f["clf_conf"]
        clf_cal = isotonic_apply(calib_table[sid], clf_raw) if clf_raw is not None else None
        margin = f["clf_margin"]
        agreement = int(rule_p is not None and clf_p is not None and rule_p == clf_p)
        # --- 信号源（确定性组件） ---
        sources = {
            "rule": (rule_p, rule_conf if rule_p else None),
            "clf": (clf_p, clf_cal),
            "llm": (llm_p, f["llm_conf"]),
        }
        # S6 / S7 / S8：纯信号基线（无门）
        for name, key in (("S6_rule_only", "rule"), ("S7_classifier_only", "clf"), ("S8_blind_llm_only", "llm")):
            p_, c_ = sources[key]
            variants[name].append(base_row(sid, p_, c_, bool(p_), "baseline_no_gate", 0))
        # S9 / S10：规则优先融合（无学习门）
        for name, alt in (("S9_rule_plus_classifier", "clf"), ("S10_rule_plus_blind_llm", "llm")):
            p_, c_ = sources["rule"]
            if not p_:
                p_, c_ = sources[alt]
            variants[name].append(base_row(sid, p_, c_, bool(p_), "rule_first_fusion", 0))

        # 控制器族（S0–S5）：预测源 = 规则优先，否则分类器；分数 = 校准分类器置信，
        # 规则来源且与分类器一致时 +0.1 一致性加成（S2 全部移除）。
        for name in CONTROLLER_VARIANTS:
            v_fusion = name != "S2_wo_evidence_agreement"
            v_agree = name != "S2_wo_evidence_agreement"
            v_per_class = name != "S1_wo_class_gate"
            v_struct = name != "S5_wo_structural_admission"
            v_contra = name != "S3_wo_contradiction_guard"

            if v_fusion and rule_p:
                pred, src_reason = rule_p, "rule"
            else:
                pred, src_reason = clf_p, "classifier"
            if pred is None:
                variants[name].append(base_row(sid, None, None, False, "no_candidate_signal", 0))
                continue
            score_val = clf_cal if clf_cal is not None else (rule_conf or 0.0)
            if v_agree and agreement and src_reason == "rule" and score_val:
                score_val = min(1.0, score_val + 0.1)
            theta = (
                0.0
                if name == "S4_wo_abstention"
                else (theta_global if name == "S1_wo_class_gate" else (theta_c.get(pred) or theta_global))
            )
            accept = bool(score_val is not None and score_val >= theta)
            gate_viol = 0
            reason = f"source={src_reason};theta={theta}"
            if name != "S4_wo_abstention" and not accept:
                reason += ";abstain"
            if v_contra and contra(frame, sid, pred):
                accept = False
                gate_viol = 1
                reason += ";contradiction_guard"
            if v_struct and not structural_ok(frame, sid, pred):
                accept = False
                gate_viol = 1
                reason += ";structural_admission"
            variants[name].append(base_row(sid, pred, score_val, accept, reason, gate_viol))
    return variants


def violation_ok(v: int) -> bool:
    return v == 0


DISABLED: set[str] = set()
CONTROLLER_VARIANTS = [
    "S0_full",
    "S1_wo_class_gate",
    "S2_wo_evidence_agreement",
    "S3_wo_contradiction_guard",
    "S4_wo_abstention",
    "S5_wo_structural_admission",
]


def fill_correct(variants: dict[str, list[dict[str, Any]]], reference: dict[str, str]) -> None:
    for rows in variants.values():
        for r in rows:
            ref = reference.get(r["sample_id"])
            r["correct"] = int(bool(r["accepted"]) and r["prediction"] == ref) if ref else 0


# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------

def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    accepted = [r for r in rows if r["accepted"]]
    correct = sum(r["correct"] for r in accepted)
    cov = len(accepted) / n if n else 0.0
    sel_acc = correct / len(accepted) if accepted else None
    sel_risk = (len(accepted) - correct) / len(accepted) if accepted else None
    gen_risk = (len(accepted) - correct) / n if n else 0.0
    pts = rows_to_points(rows)
    aurc = None
    if len(pts) >= 2:
        xs = [p["coverage"] for p in pts]
        ys = [p["selective_risk"] or 0.0 for p in pts]
        aurc = sum((xs[i + 1] - xs[i]) * (ys[i + 1] + ys[i]) / 2 for i in range(len(xs) - 1))
    return {
        "n": n,
        "coverage": cov,
        "selective_accuracy": sel_acc,
        "selective_risk": sel_risk,
        "generalized_risk": gen_risk,
        "aurc": aurc,
        **{k: v for k, v in risk_at_coverage(pts).items()},
        **{k: v for k, v in coverage_at_risk(pts).items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", choices=["strong", "all"], default="strong")
    ap.add_argument("--split", choices=["dev", "val", "test"], default="dev")
    ap.add_argument("--freeze-test", action="store_true", help="记录配置哈希并解锁 test 评价")
    args = ap.parse_args()

    frame = build_signal_frame()
    reference = load_reference(args.reference)
    split = load_split()

    dev_ids = [sid for sid in frame if split.get(f"entity_type:{sid}") == "dev"]
    dev_rows = []
    # DEV 上学：校准表（全局）+ theta（占位；真 theta 以分类器预测的类为键）
    for sid in dev_ids:
        f = frame[sid]
        if f["clf_conf"] is not None and f["clf_pred"] and reference.get(sid):
            dev_rows.append((f["clf_conf"], int(f["clf_pred"] == reference[sid])))
    calib_global = isotonic_fit(dev_rows)
    calib_table: dict[str, list[tuple[float, float]]] = {sid: calib_global for sid in frame}

    # 先以全局 theta=0.5 生成一次 DEV 控制器行，学习 theta_c
    global DEFAULTS
    DISABLED.clear()
    variants = compose_s_variants(frame, calib_table, {}, 0.5)
    dev_controller = [r for r in variants["S0_full"] if split.get(f"entity_type:{r['sample_id']}") == "dev"]
    theta_c: dict[str, float] = {}
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in dev_controller:
        ref = reference.get(r["sample_id"])
        by_class[r["prediction"] or "?"].append(r)
    theta_global = learn_threshold(dev_controller)
    for cls, rows in by_class.items():
        theta_c[cls] = learn_threshold(rows)
    print(f"[selective_semantic] DEV theta_c learned: {theta_c}; global={theta_global}")

    # 正式变体生成（DEV 配置冻结）
    variants = compose_s_variants(frame, calib_table, theta_c, theta_global)
    fill_correct(variants, reference)

    # 校准表哈希（进入配置指纹）
    config_hash = hashlib.sha256(
        json.dumps({"theta_c": theta_c, "global": theta_global, "calib": calib_global}, sort_keys=True).encode()
    ).hexdigest()[:16]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows_path = OUT_DIR / f"ABLATION_RUNS_{args.reference}_{args.split}.csv"
    all_rows = []
    for name, rows in sorted(variants.items()):
        for r in rows:
            if split.get(f"entity_type:{r['sample_id']}") == args.split:
                all_rows.append({"variant": name, **r})
    fields = ["variant", "sample_id", "prediction", "score", "accepted", "correct", "gate_violation", "gate_reason"]
    with open(rows_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)

    summary = {}
    for name, rows in sorted(variants.items()):
        sub = [r for r in rows if split.get(f"entity_type:{r['sample_id']}") == args.split]
        summary[name] = evaluate(sub)
        acc_n = sum(r["accepted"] for r in sub)
        src_n = Counter(r["gate_reason"].split(";")[0] for r in sub if r["accepted"])
        if name in CONTROLLER_VARIANTS:
            print(f"  [diag] {name}: accepted={acc_n} sources={dict(src_n)}")
    out_json = OUT_DIR / f"ABLATION_SUMMARY_{args.reference}_{args.split}.json"
    out_json.write_text(
        json.dumps({"config_hash": config_hash, "reference": args.reference, "split": args.split, "n_reference_entity": len(reference), "variants": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[selective_semantic] split={args.split} ref={args.reference} config={config_hash}")
    for name, m in summary.items():
        print(f"  {name:<28} cov={m['coverage']:.3f} sel_acc={m['selective_accuracy'] if m['selective_accuracy'] is not None else float('nan'):.3f} risk={m['selective_risk'] if m['selective_risk'] is not None else float('nan')}")
    return 0


import hashlib  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
