# -*- coding: utf-8 -*-
"""analyze_cascaded_stages.py — 级联准入阶段增益分析（零新增 LLM 调用）。

只复用既有冻结审计数据：
  release_final/experiments/quality_audit/{SAMPLE_KEY.json,
  JUDGE_gpt_oss_20b_VERDICTS.jsonl, JUDGE_qwen_qwen3_8b_VERDICTS.jsonl}
  （4,427 条样本全部为 pre-gate strict candidate——均属 112,158 门宇宙；
   production_tier = Evidence Gate 后最终层）

阶段对比：
  A. Pre-Gate Strict Candidate（总体 112,158）：若直接发布候选的质量。
     样本按 final 层分层抽取，总体率用 final 层构成加权还原 + 分层 bootstrap CI。
  B. Final STRICT（总体 31,067）：该层样本率直接代表（抽样框=该层）。

配对比较（同一批 fact_id 的准入结局分组）：
  kept-STRICT vs downgraded(→CONTEXTUAL/UNRESOLVED) 的支持率差异；
  Newcombe 差值 CI + Fisher 精确检验（本设计非匹配对，McNemar 不适用，如实说明）。

门外 STRICT 机会：直接引用冻结审计（0.66%，设计型 95%CI [0.40%, 0.97%]），
不重算口径。
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
CLOSURE = V31 / "experiments" / "10_full_universe_admission_closure"
OUT = Path(__file__).resolve().parent               # experiments/cascaded_admission_stage_effect/
CN_TZ = timezone(timedelta(hours=8))
SEED = 20260916
BOOT = 10_000
SUPPORT = {"FULLY_SUPPORTED", "PARTIALLY_SUPPORTED"}
NEG = {"UNSUPPORTED", "CONTRADICTED"}

POP_PRE_GATE = 112_158
POP_STRICT = 31_067
POP_CTX = 31_282
POP_UNRES = 49_809


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


def newcombe(pa, na, pb, nb):
    """Newcombe hybrid-score 差值 CI（p1-p2）。"""
    z = 1.959963984540054

    def wilson_iv(p, n):
        d = 1 + z * z / n
        c = (p + z * z / (2 * n)) / d
        half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
        return c - half, c + half

    p1, p2 = pa / na, pb / nb
    l1, u1 = wilson_iv(p1, na)
    l2, u2 = wilson_iv(p2, nb)
    d_pt = p1 - p2
    lo = d_pt - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d_pt + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return {"point": round(d_pt, 4),
            "ci95_newcombe": [round(lo, 4), round(hi, 4)]}


def fisher_exact_2x2(a, b, c, d):
    """Fisher 精确检验（双侧，超几何枚举）。a/b=组1 支持/不支持；c/d=组2。"""
    from math import comb
    n = a + b + c + d
    r1, r2 = a + b, c + d
    c1 = a + c
    lo = max(0, r1 - (n - c1))
    hi = min(r1, c1)

    def p_of(x):
        return comb(c1, x) * comb(n - c1, r1 - x) / comb(n, r1)

    p0 = p_of(a)
    tail = sum(p_of(x) for x in range(lo, hi + 1) if p_of(x) <= p0 + 1e-12)
    return round(min(1.0, tail), 6)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    key = json.loads((QA / "SAMPLE_KEY.json").read_text(encoding="utf-8"))

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
    for fid, k in key.items():
        if fid not in ja or fid not in jb:
            continue
        da, db = ja[fid]["decision"], jb[fid]["decision"]
        consensus = da if da == db else None
        items.append({"fact_id": fid, "final_tier": k["production_tier"],
                      "a": da, "b": db, "consensus": consensus})
    n_join = len(items)

    def stage_stats(subset, label, pop, weight_note):
        n = len(subset)
        sup = sum(1 for it in subset if it["consensus"] in SUPPORT)
        uns = sum(1 for it in subset if it["consensus"] in NEG)
        contra = sum(1 for it in subset if it["consensus"] == "CONTRADICTED")
        insuf = sum(1 for it in subset if it["consensus"] == "INSUFFICIENT")
        return {"stage": label, "population": pop,
                "audit_valid_n": n,
                "evidence_supported": wilson(sup, n),
                "unsupported": wilson(uns, n),
                "contradicted": wilson(contra, n),
                "insufficient": wilson(insuf, n),
                "weight_note": weight_note}

    # A. Pre-Gate Strict Candidate：样本=全部联合判定条目（分层抽样），
    #    总体率需按 final 层构成加权还原
    pre_sample = stage_stats(items, "Pre-Gate Strict Candidate", POP_PRE_GATE,
                             "sample rate is stratified; population rate needs "
                             "final-tier weighting (see weighted fields)")
    # B. Final STRICT：抽样框即该层
    strict_items = [it for it in items if it["final_tier"] == "STRICT"]
    strict_stats = stage_stats(strict_items, "Final STRICT", POP_STRICT,
                               "sample drawn within this stratum; rate is direct")

    # Pre-Gate 加权总体率（权重 = 31,067/2,268 等按 final 层）
    stratum_pop = {"STRICT": POP_STRICT, "CONTEXTUAL": POP_CTX,
                   "UNRESOLVED": POP_UNRES}
    stratum_n = Counter(it["final_tier"] for it in items)
    sup_by = {t: sum(1 for it in items if it["final_tier"] == t
                     and it["consensus"] in SUPPORT) for t in stratum_pop}
    weighted_pre = (sum(sup_by[t] / stratum_n[t] * stratum_pop[t]
                        for t in stratum_pop) / POP_PRE_GATE)
    # 分层 bootstrap CI
    rng = random.Random(SEED)
    by_tier = {t: [it for it in items if it["final_tier"] == t]
               for t in stratum_pop}
    boots = []
    for _ in range(BOOT):
        num = 0.0
        for t, lst in by_tier.items():
            s = [lst[rng.randrange(len(lst))]["consensus"] for _ in lst]
            num += (sum(1 for x in s if x in SUPPORT) / len(s)) * stratum_pop[t]
        boots.append(num / POP_PRE_GATE)
    boots.sort()
    pre_weighted = {
        "point": round(weighted_pre, 4),
        "ci95_stratified_bootstrap": [round(boots[int(0.025 * BOOT)], 4),
                                      round(boots[int(0.975 * BOOT) - 1], 4)],
        "bootstrap_iterations": BOOT, "bootstrap_seed": SEED,
        "weights": {t: {"population": stratum_pop[t], "sample_n": stratum_n[t]}
                    for t in stratum_pop},
    }

    # 准入结局分组比较（同一批 fact_id 的结局差异）
    kept = [it for it in items if it["final_tier"] == "STRICT"]
    down = [it for it in items if it["final_tier"] != "STRICT"]

    def sup_rate(subset):
        return (sum(1 for it in subset if it["consensus"] in SUPPORT), len(subset))

    k_sup, k_n = sup_rate(kept)
    d_sup, d_n = sup_rate(down)
    diff = newcombe(k_sup, k_n, d_sup, d_n)
    fisher_p = fisher_exact_2x2(k_sup, k_n - k_sup, d_sup, d_n - d_sup)

    # 分层 bootstrap 差值 CI（按结局层重采样）
    boots_d = []
    for _ in range(BOOT):
        sk = sum(1 for _ in range(k_n)
                 if kept[rng.randrange(k_n)]["consensus"] in SUPPORT) / k_n
        sd = sum(1 for _ in range(d_n)
                 if down[rng.randrange(d_n)]["consensus"] in SUPPORT) / d_n
        boots_d.append(sk - sd)
    boots_d.sort()
    diff["ci95_stratified_bootstrap"] = [round(boots_d[int(0.025 * BOOT)], 4),
                                         round(boots_d[int(0.975 * BOOT) - 1], 4)]
    diff["fisher_exact_two_sided_p"] = fisher_p
    diff["mcnemar_note"] = ("McNemar 不适用：结局分组（kept/downgraded）为观测分层"
                            "而非同一受试对象的两次测量；采用组间差值 + Newcombe CI "
                            "+ 分层 bootstrap + Fisher 精确检验。")

    results = {
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "zero_new_llm_calls": True,
        "data_sources": [
            "release_final/experiments/quality_audit/SAMPLE_KEY.json",
            "release_final/experiments/quality_audit/JUDGE_gpt_oss_20b_VERDICTS.jsonl",
            "release_final/experiments/quality_audit/JUDGE_qwen_qwen3_8b_VERDICTS.jsonl",
        ],
        "joined_valid_n": n_join,
        "stages": [pre_sample, strict_stats],
        "pre_gate_weighted_population_rate": pre_weighted,
        "pre_gate_stage_note": (
            "Pre-Gate 样本按 final 层分层抽取，样本率≠总体率；"
            "总体率以 final 层构成加权还原（112,158 = 31,067 kept + 31,282 →CTX "
            "+ 49,809 →UNRES）。"),
        "admission_outcome_comparison": {
            "kept_final_strict": {"supported": wilson(k_sup, k_n)},
            "downgraded_by_gate": {"supported": wilson(d_sup, d_n)},
            "difference_in_proportions_kept_minus_downgraded": diff,
        },
        "outside_gate_frozen_reference": {
            "weighted_strict_opportunity": 0.0066,
            "design_ci95": [0.0040, 0.0097],
            "count_interval": [1257, 3019],
            "source": "10_full_universe_admission_closure/OUTSIDE_GATE_AUDIT_RESULTS.json"
                      "(weighted_strict_opportunity_design_ci)；本轮零重算",
        },
        "statistical_unit_note": (
            "统计单位 = 断言（fact_id）；强共识口径 = 双裁判五档一致；"
            "全部率为强共识口径，另附单裁判口径见 per_judge。"),
    }

    # 单裁判口径（透明附件）
    per_judge = {}
    for jname, jd in (("judgeA", ja), ("judgeB", jb)):
        pj_pre_sup = sum(1 for it in items if jd[it["fact_id"]]["decision"] in SUPPORT)
        pj_strict_sup = sum(1 for it in strict_items
                            if jd[it["fact_id"]]["decision"] in SUPPORT)
        per_judge[jname] = {
            "pre_gate_supported": wilson(pj_pre_sup, len(items)),
            "final_strict_supported": wilson(pj_strict_sup, len(strict_items))}
    results["per_judge_secondary"] = per_judge

    # ---- CSV（核心表）----
    csv_path = OUT / "CASCADED_ADMISSION_STAGE_RESULTS.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["阶段", "候选规模(总体)", "独立评价有效样本量(强共识)",
                    "证据支持数", "证据支持率", "95%CI",
                    "不支持数", "不支持率", "冲突数", "不足数", "阶段作用"])
        ps = pre_sample["evidence_supported"]
        w.writerow(["Pre-Gate Strict Candidate", POP_PRE_GATE,
                    pre_sample["audit_valid_n"], ps["numerator"], ps["point"],
                    f"[{ps['ci95'][0]}, {ps['ci95'][1]}]（样本口径）；"
                    f"总体加权 {pre_weighted['point']} "
                    f"[{pre_weighted['ci95_stratified_bootstrap'][0]}, "
                    f"{pre_weighted['ci95_stratified_bootstrap'][1]}]",
                    pre_sample["unsupported"]["numerator"],
                    pre_sample["unsupported"]["point"],
                    pre_sample["contradicted"]["numerator"],
                    pre_sample["insufficient"]["numerator"],
                    "结构准入后的严格候选（未做证据核验）"])
        ss = strict_stats["evidence_supported"]
        w.writerow(["Final STRICT", POP_STRICT, strict_stats["audit_valid_n"],
                    ss["numerator"], ss["point"],
                    f"[{ss['ci95'][0]}, {ss['ci95'][1]}]",
                    strict_stats["unsupported"]["numerator"],
                    strict_stats["unsupported"]["point"],
                    strict_stats["contradicted"]["numerator"],
                    strict_stats["insufficient"]["numerator"],
                    "证据语义核验后的严格知识层"])
        w.writerow(["Outside-Gate weighted STRICT opportunity（引用冻结审计）",
                    311_992, 4_957, "—", 0.0066, "[0.0040, 0.0097]",
                    "—", "—", "—", "—",
                    "前置准入遗漏的潜在 STRICT 机会（0.66%，条数 [1,257, 3,019]）"])

    json_path = OUT / "CASCADED_ADMISSION_STAGE_RESULTS.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    print(f"[cascaded] joined={n_join}")
    print(f"  Pre-Gate sample supported = {pre_sample['evidence_supported']}")
    print(f"  Pre-Gate weighted pop     = {pre_weighted}")
    print(f"  Final STRICT supported    = {strict_stats['evidence_supported']}")
    print(f"  kept supported   = {wilson(k_sup, k_n)}")
    print(f"  downgraded supp  = {wilson(d_sup, d_n)}")
    print(f"  diff             = {diff}")
    print(f"[cascaded] wrote {json_path.name} / {csv_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
