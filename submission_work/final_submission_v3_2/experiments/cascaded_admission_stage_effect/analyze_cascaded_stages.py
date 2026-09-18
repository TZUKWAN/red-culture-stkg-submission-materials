# -*- coding: utf-8 -*-
"""analyze_cascaded_stages.py — 级联准入阶段增益分析（修正统计口径版）。

修正（相对上一版）：
  1. 分类互斥三分：supported(FULLY+PARTIAL) / negative(UNSUP+CONTRA) /
     insufficient；分类合计 = consensus_n（972/973 已调和）。
  2. 核心指标为条件指标：
     - Strong Consensus Coverage = consensus_n / audited_n
     - Support Precision among Strong Consensus = supported / consensus_n
     - Negative Rate among Strong Consensus = negative / consensus_n
     INSUFFICIENT 单列。无条件占比仅进诊断附录。

估计器（Pre-Gate 总体）：
  A. final 层比率估计量：P = Σ[N_h·(s_h/n_h)] / Σ[N_h·(c_h/n_h)]，
     CI = 分层 bootstrap（seed=20260916，B=10,000，replicates 落盘）。
  B. 设计精确权重稳健值：按冻结协议各路由重建真实入选概率 π（BASE 配额 /
     predicate overlay / boundary / salvaged），w=1/π。

Final STRICT 沿用冻结口径：965/972 = 99.28%，negative 4/972 = 0.41%，
coverage 972/2268。门外 0.66% [0.40, 0.97] 原样引用，零重算。
"""
from __future__ import annotations

import csv
import json
import math
import random
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

V31 = Path(__file__).resolve().parents[3] / "final_submission_v3_1"
QA = V31 / "release_final" / "experiments" / "quality_audit"
CONFIG = V31 / "release_final" / "configs"
FTIER = V31 / "experiments" / "07_provenance_semantic_gate" / "FINAL_TIERING.csv"
OUT = Path(__file__).resolve().parent
CN_TZ = timezone(timedelta(hours=8))
SEED_BOOT = 20260916
BOOT = 10_000
SUPPORT = {"FULLY_SUPPORTED", "PARTIALLY_SUPPORTED"}
NEG = {"UNSUPPORTED", "CONTRADICTED"}

POP = {"STRICT": 31_067, "CONTEXTUAL": 31_282, "UNRESOLVED": 49_809}
POP_PRE = sum(POP.values())


def wilson(k: int, n: int) -> dict:
    if n == 0:
        return {"point": None, "ci95": None, "numerator": k, "denominator": n}
    p = k / n
    z = 1.959963984540054
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"point": round(p, 4),
            "ci95": [round(max(0.0, c - half), 4), round(min(1.0, c + half), 4)],
            "numerator": k, "denominator": n}


def newcombe(p1, n1, p2, n2) -> dict:
    z = 1.959963984540054

    def iv(p, n):
        dd = 1 + z * z / n
        cc = (p + z * z / (2 * n)) / dd
        hh = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / dd
        return cc - hh, cc + hh

    pt = p1 - p2
    l1, u1 = iv(p1, n1)
    l2, u2 = iv(p2, n2)
    return {"point": round(pt, 4),
            "ci95_newcombe": [round(pt - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), 4),
                              round(pt + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2), 4)]}


def main() -> int:
    key = json.loads((QA / "SAMPLE_KEY.json").read_text(encoding="utf-8"))
    proto = json.loads((CONFIG / "FINAL_QUALITY_AUDIT_PROTOCOL.json").read_text(
        encoding="utf-8"))
    alloc = proto["actual_alloc_by_tier_stratum"]      # "TIER|gate_stratum": k

    ftier = {}
    for r in csv.DictReader(open(FTIER, encoding="utf-8-sig")):
        ftier[r["fact_id"]] = r
    gate_strat = lambda r: (r["bucket"] if r["bucket"] in
                            ("aligned", "mismatch_with_evidence", "no_evidence")
                            else "recovery_" + r["recovery_class"])

    def load(fn):
        out = {}
        for line in open(QA / fn, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                if r.get("parse_ok"):
                    out[r["fact_id"]] = r
        return out

    ja = load("JUDGE_gpt_oss_20b_VERDICTS.jsonl")
    jb = load("JUDGE_qwen_qwen3_8b_VERDICTS.jsonl")

    items = []
    sample_pred = {}
    sa = json.loads((QA / "SAMPLE_AUDIT.json").read_text(encoding="utf-8"))
    for it in sa["items"]:
        sample_pred[it["fact_id"]] = it.get("predicate", "")
    for fid, k in key.items():
        if fid not in ja or fid not in jb:
            continue
        da, db = ja[fid]["decision"], jb[fid]["decision"]
        consensus = da if da == db else None
        cat = (None if consensus is None else
               "supported" if consensus in SUPPORT else
               "negative" if consensus in NEG else "insufficient")
        items.append({"fact_id": fid, "tier": k["production_tier"],
                      "consensus": consensus, "cat": cat,
                      "routes": k.get("reasons", []),
                      "confidence": k.get("production_confidence")})
    audited_n = len(items)
    consensus_n = sum(1 for it in items if it["consensus"] is not None)

    # ---- 路由池规模（真实入选概率的必备量）----
    import sqlite3
    dcon = sqlite3.connect(f"file:{V31 / 'release_final' / 'data' / 'red_culture_stkg_final.sqlite'}?mode=ro",
                           uri=True)
    N_pred = {p: n for p, n in dcon.execute(
        "SELECT predicate, COUNT(*) FROM research_assertions "
        "WHERE research_tier='strict_semantic' GROUP BY predicate")}
    dcon.close()
    N_tier_gs = Counter()
    for r in ftier.values():
        if r["final_tier"] != "STRICT":
            continue
        N_tier_gs[("STRICT", gate_strat(r))] += 1
    n_low = sum(1 for k in key.values()
                if k["production_tier"] in POP
                and isinstance(k.get("production_confidence"), (int, float))
                and k["production_confidence"] <= 0.55)
    n_high = sum(1 for k in key.values()
                 if k["production_tier"] in POP
                 and isinstance(k.get("production_confidence"), (int, float))
                 and k["production_confidence"] >= 0.95)

    # no_evidence 池的层级后备配额（冻结采样器实际使用的路由）
    K_FALLBACK = {"STRICT": 1000, "CONTEXTUAL": 500, "UNRESOLVED": 500}
    N_fallback_pool = Counter()
    for r in ftier.values():
        if gate_strat(r) == "no_evidence":
            N_fallback_pool[r["final_tier"]] += 1

    def pi_item(it) -> float:
        """入选概率 = 1 − Π(1−π_r)，r 遍历该条目的全部【合格】路由
        （BASE 配额池 + predicate overlay + boundary + salvaged），
        与其最终被哪个路由实际选中无关。"""
        fid = it["fact_id"]
        fr = ftier[fid]
        tier, gs = it["tier"], gate_strat(fr)
        routes = []
        k = alloc.get(f"{tier}|{gs}")
        pool = N_tier_gs.get((tier, gs), 0)
        if k and pool:
            routes.append(k / pool)
        elif gs == "no_evidence":
            # 冻结采样器对 no_evidence 池使用层级后备配额
            k2 = K_FALLBACK.get(tier, 0)
            pool2 = N_fallback_pool.get(tier, 0)
            if k2 and pool2:
                routes.append(k2 / pool2)
        if tier == "STRICT":
            n_p = N_pred.get(sample_pred.get(fid, ""), 0)
            if n_p:
                routes.append(min(30, n_p) / n_p)
        conf = it["confidence"]
        if isinstance(conf, (int, float)):
            if conf <= 0.55:
                routes.append(min(100, n_low) / max(n_low, 1))
            elif conf >= 0.95:
                routes.append(min(100, n_high) / max(n_high, 1))
        if any(r == "parser_salvaged" for r in it["routes"]):
            routes.append(1.0)
        if not routes:
            routes = [min(250, POP[tier]) / POP[tier]]
        p_no = 1.0
        for r_ in routes:
            p_no *= (1.0 - r_)
        return 1.0 - p_no

    for it in items:
        it["pi"] = pi_item(it)

    # ---- final 层比率估计量 ----
    per_stratum = {}
    num_s = num_c = num_neg = num_ins = 0.0
    cov_num = 0.0
    for t, N_h in POP.items():
        sub = [it for it in items if it["tier"] == t]
        n_h = len(sub)
        c_h = sum(1 for it in sub if it["consensus"] is not None)
        s_h = sum(1 for it in sub if it["cat"] == "supported")
        neg_h = sum(1 for it in sub if it["cat"] == "negative")
        ins_h = sum(1 for it in sub if it["cat"] == "insufficient")
        per_stratum[t] = {"N_h": N_h, "n_h": n_h, "c_h": c_h, "s_h": s_h,
                          "neg_h": neg_h, "ins_h": ins_h}
        num_s += N_h * (s_h / n_h)
        num_c += N_h * (c_h / n_h)
        num_neg += N_h * (neg_h / n_h)
        num_ins += N_h * (ins_h / n_h)
        cov_num += N_h * (c_h / n_h)
    P_support = num_s / num_c
    P_negative = num_neg / num_c
    P_insufficient = num_ins / num_c
    P_coverage = cov_num / POP_PRE

    # ---- 分层 bootstrap CI（seed 固定，replicates 落盘）----
    rng = random.Random(SEED_BOOT)
    by_tier_items = {t: [it for it in items if it["tier"] == t] for t in POP}
    reps = {"support": [], "negative": [], "coverage": []}
    for _ in range(BOOT):
        num_s = num_c = num_neg = num_ins = cov = 0.0
        for t, lst in by_tier_items.items():
            N_h, m = POP[t], len(lst)
            cs = ss = ng = ins = 0
            for _ in range(m):
                it = lst[rng.randrange(m)]
                if it["consensus"] is None:
                    continue
                cs += 1
                if it["cat"] == "supported":
                    ss += 1
                elif it["cat"] == "negative":
                    ng += 1
                else:
                    ins += 1
            if cs:
                num_s += N_h * (ss / m)
                num_c += N_h * (cs / m)
                num_neg += N_h * (ng / m)
                num_ins += N_h * (ins / m)
                cov += N_h * (cs / m)
        reps["support"].append(num_s / num_c)
        reps["negative"].append(num_neg / num_c)
        reps["coverage"].append(cov / POP_PRE)

    def ci_of(vals):
        s = sorted(vals)
        return [round(s[int(0.025 * BOOT)], 4), round(s[int(0.975 * BOOT) - 1], 4)]

    pre_gate = {
        "population": POP_PRE,
        "audited_n": audited_n,
        "consensus_n_sample": consensus_n,
        "coverage_ratio_estimator": {"point": round(P_coverage, 4),
                                     "ci95_stratified_bootstrap": ci_of(reps["coverage"])},
        "support_precision_among_consensus": {
            "point": round(P_support, 4),
            "ci95_stratified_bootstrap": ci_of(reps["support"])},
        "negative_rate_among_consensus": {
            "point": round(P_negative, 4),
            "ci95_stratified_bootstrap": ci_of(reps["negative"])},
        "insufficient_rate_among_consensus": {"point": round(P_insufficient, 4)},
        "per_stratum": per_stratum,
        "pi_weighted_robust": None,   # 占位，下方填充
    }

    # ---- π 权重稳健值：弃用 ----
    # 冻结采样器的部分路由池（no_evidence 后备池之外的 overlay 交集）无法从
    # 冻结产物唯一复原，π 权重变体不稳定（曾得 coverage>1 的非法定义）。
    # 按目标书 §三 的 final 层比率估计量为准；overlay/boundary 过采样的
    # 层内代表性局限在 REPORT 的局限段如实说明。
    pre_gate["pi_weighted_robust"] = None

    # ---- Final STRICT（冻结口径）----
    kept = [it for it in items if it["tier"] == "STRICT"]
    kept_c = sum(1 for it in kept if it["consensus"] is not None)
    kept_s = sum(1 for it in kept if it["cat"] == "supported")
    kept_neg = sum(1 for it in kept if it["cat"] == "negative")
    kept_ins = sum(1 for it in kept if it["cat"] == "insufficient")
    final_strict = {
        "population": POP["STRICT"],
        "audited_n": len(kept),
        "consensus_n": kept_c,
        "coverage": {"point": round(kept_c / len(kept), 4),
                     "numerator": kept_c, "denominator": len(kept),
                     "note": "仅说明 Judge 一致性覆盖，不得与知识错误率混淆"},
        "support_precision_among_consensus": {
            "point": round(kept_s / kept_c, 4),
            "ci95_wilson_frozen": [0.9852, 0.9965],
            "numerator": kept_s, "denominator": kept_c,
            "source": "冻结审计 AUDIT_RESULTS.json（965/972）"},
        "negative_rate_among_consensus": {
            "point": round(kept_neg / kept_c, 4),
            "ci95_wilson_frozen": [0.0016, 0.0105],
            "numerator": kept_neg, "denominator": kept_c},
        "insufficient_n": kept_ins,
    }

    # ---- kept vs downgraded（条件指标）----
    down = [it for it in items if it["tier"] != "STRICT"]
    down_c = sum(1 for it in down if it["consensus"] is not None)
    down_s = sum(1 for it in down if it["cat"] == "supported")
    down_neg = sum(1 for it in down if it["cat"] == "negative")
    down_ins = sum(1 for it in down if it["cat"] == "insufficient")
    outcome = {
        "kept_final_strict": {
            "consensus_n": kept_c,
            "support_precision_among_consensus": {
                "point": round(kept_s / kept_c, 4),
                "numerator": kept_s, "denominator": kept_c},
            "negative_rate_among_consensus": {
                "point": round(kept_neg / kept_c, 4),
                "numerator": kept_neg, "denominator": kept_c}},
        "downgraded_by_gate": {
            "consensus_n": down_c,
            "support_precision_among_consensus": {
                "point": round(down_s / down_c, 4),
                "numerator": down_s, "denominator": down_c},
            "negative_rate_among_consensus": {
                "point": round(down_neg / down_c, 4),
                "numerator": down_neg, "denominator": down_c}},
        "difference_support_precision_kept_minus_downgraded": newcombe(
            kept_s / kept_c, kept_c, down_s / down_c, down_c),
        "difference_negative_rate_downgraded_minus_kept": newcombe(
            down_neg / down_c, down_c, kept_neg / kept_c, kept_c),
        "statistical_unit_note": (
            "统计单位=断言；比较限强共识样本（条件指标）。McNemar 不适用："
            "kept/downgraded 为观测结局分层而非同一对象两次测量。"),
    }

    # ---- 诊断附录：无条件占比（不得称为 precision/quality）----
    diag = {
        "definition": "unconditional strong-consensus support share = "
                      "强共识支持数 / 全部审计样本；混合覆盖与精度，"
                      "不得作为 accuracy/precision/support quality/evidence support rate。",
        "pre_gate_share": wilson(sum(1 for it in items if it["cat"] == "supported"),
                                 audited_n),
        "final_strict_share": wilson(kept_s, len(kept)),
        "downgraded_share": wilson(down_s, len(down)),
        "legacy_removed_from_manuscript": ["22.20%", "29.79%", "42.55%",
                                           "16.40%", "+26.15pp"],
    }

    results = {
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "zero_new_llm_calls": True,
        "metric_definitions": {
            "strong_consensus_coverage": "consensus_n / audited_n",
            "support_precision_among_strong_consensus":
                "supported_consensus_n / consensus_n（FULLY+PARTIAL，双裁判五档一致）",
            "negative_rate_among_strong_consensus":
                "(UNSUPPORTED+CONTRADICTED) / consensus_n",
            "insufficient_reported_separately": True,
        },
        "n_audited": audited_n,
        "n_consensus_sample": consensus_n,
        "pre_gate_strict_candidate": pre_gate,
        "final_strict": final_strict,
        "admission_outcome_comparison": outcome,
        "outside_gate_frozen_reference": {
            "weighted_strict_opportunity": 0.0066,
            "design_ci95": [0.0040, 0.0097],
            "count_interval": [1257, 3019],
            "source": "10_full_universe_admission_closure/"
                      "OUTSIDE_GATE_AUDIT_RESULTS.json（零重算）"},
        "diagnostic_unconditional_shares": diag,
    }
    (OUT / "CASCADED_ADMISSION_STAGE_RESULTS.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(OUT / "CASCADED_ADMISSION_STAGE_RESULTS.csv", "w",
              encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["指标", "Pre-Gate Strict Candidate", "Final STRICT"])
        w.writerow(["总体规模", POP_PRE, POP["STRICT"]])
        w.writerow(["审计样本量", audited_n, len(kept)])
        cov_ci = ci_of(reps["coverage"])
        sup_ci = ci_of(reps["support"])
        neg_ci = ci_of(reps["negative"])
        w.writerow(["强共识覆盖率",
                    f"{P_coverage:.4f} [{cov_ci[0]}, {cov_ci[1]}]",
                    f"{kept_c}/{len(kept)} = {kept_c / len(kept):.4f}"])
        w.writerow(["强共识条件支持精度",
                    f"{P_support:.4f} [{sup_ci[0]}, {sup_ci[1]}]",
                    "965/972 = 0.9928（冻结）[0.9852, 0.9965]"])
        w.writerow(["强共识条件不支持/冲突率",
                    f"{P_negative:.4f} [{neg_ci[0]}, {neg_ci[1]}]",
                    "4/972 = 0.0041（冻结）[0.0016, 0.0105]"])
        w.writerow(["强共识条件不足率（单列）",
                    f"{P_insufficient:.4f}", f"{kept_ins}/{kept_c}"])
        w.writerow(["设计精确 π 权重稳健值",
                    "弃用（路由池不可从冻结产物唯一复原；见 REPORT 局限段）", "—"])
        w.writerow(["门外加权 STRICT 机会（冻结引用，单列）",
                    "0.66% [0.40, 0.97]；条数 [1,257, 3,019]", "—"])

    (OUT / "pre_gate_stratified_bootstrap_replicates.json").write_text(
        json.dumps({"seed": SEED_BOOT, "iterations": BOOT,
                    "support_precision": reps["support"],
                    "negative_rate": reps["negative"],
                    "coverage": reps["coverage"]}, ensure_ascii=False),
        encoding="utf-8")

    print(f"[cascaded-v2] audited={audited_n} consensus={consensus_n}")
    print(f"  Pre-Gate ratio estimator: coverage={P_coverage:.4f} "
          f"support={P_support:.4f} negative={P_negative:.4f} "
          f"insufficient={P_insufficient:.4f}")
    print(f"  Pre-Gate CIs: support {ci_of(reps['support'])} "
          f"negative {ci_of(reps['negative'])} coverage {ci_of(reps['coverage'])}")
    print(f"  Pre-Gate π-weighted robust: {pre_gate['pi_weighted_robust']}")
    print(f"  Final STRICT: precision 99.28% (965/972), "
          f"negative 0.41% (4/972), coverage {kept_c}/{len(kept)}")
    print(f"  kept vs downgraded (consensus-conditional): "
          f"{kept_s / kept_c:.4f} vs {down_s / down_c:.4f} "
          f"(support), {down_neg / down_c:.4f} vs {kept_neg / kept_c:.4f} (negative)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
