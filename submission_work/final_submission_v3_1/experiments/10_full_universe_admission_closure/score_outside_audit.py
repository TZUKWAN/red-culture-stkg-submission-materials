# -*- coding: utf-8 -*-
"""score_outside_audit.py — 门外宇宙双裁判盲评加权评分。

指标（全部带 point estimate + Wilson 95% CI + raw numerator/denominator；
总体推断另给 stratum 权重加权估计）：
  judge_raw_agreement / cohens_kappa / strong_consensus_rate
  contextual_strict_opportunity_rate / unresolved_strict_opportunity_rate
  outside_gate_exact_tier_agreement（门外样本 recommended_state vs 原层）
  per_blocker_strict_opportunity_rate
产出：OUTSIDE_GATE_AUDIT_RESULTS.json / OUTSIDE_GATE_AUDIT_REPORT.md
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

V31 = Path(__file__).resolve().parents[2]
OUT = V31 / "experiments" / "10_full_universe_admission_closure"
CN_TZ = timezone(timedelta(hours=8))

JUDGES = {"A": "JUDGE_gpt_oss_20b_VERDICTS.jsonl",
          "B": "JUDGE_qwen_qwen3_8b_VERDICTS.jsonl"}
SUP = {"FULLY_SUPPORTED", "PARTIALLY_SUPPORTED"}


def wilson(k: int, n: int) -> dict:
    if n == 0:
        return {"point": None, "ci95": None, "numerator": 0, "denominator": 0}
    p = k / n
    z = 1.959963984540054
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {"point": round(p, 4), "ci95": [round(max(0.0, c - half), 4),
                                           round(min(1.0, c + half), 4)],
            "numerator": k, "denominator": n}


def cohens_kappa(pairs):
    n = len(pairs)
    if not n:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[l] * cb[l] for l in set(ca) | set(cb)) / (n * n)
    return None if pe == 1 else round((po - pe) / (1 - pe), 4)


def main() -> int:
    key = {json.loads(l)["fact_id"]: json.loads(l)
           for l in open(OUT / "OUTSIDE_GATE_SAMPLE.jsonl", encoding="utf-8") if l.strip()}
    ledger = {}
    with open(OUT / "FULL_UNIVERSE_ADMISSION_LEDGER.csv", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            ledger[r["fact_id"]] = r
    # 层权重（总体 N / 样本 n）
    stratum_pop: Counter = Counter()
    stratum_smp: Counter = Counter()
    for fid, r in ledger.items():
        if r["in_evidence_gate_universe"] == "0":
            stratum_pop[(r["pre_gate_tier"].upper(),
                         r["primary_blocking_reason"])] += 1
    verdicts = {}
    for j, fn in JUDGES.items():
        p = OUT / fn
        if not p.exists():
            print(f"[score] 缺 {fn}")
            return 1
        for line in p.open(encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                if r.get("parse_ok"):
                    verdicts.setdefault(r["fact_id"], {})[j] = r
    both = [f for f in key if f in verdicts and "A" in verdicts[f]
            and "B" in verdicts[f]]
    for f in both:
        r = ledger.get(f) or {}
        st = (r.get("pre_gate_tier", "").upper(),
              r.get("primary_blocking_reason", ""))
        if st in stratum_pop:
            stratum_smp[st] += 1

    n = len(both)
    agree5 = weak = 0
    pairs = []
    res_fields = {}
    for field in ("evidence_support", "identity_decidable",
                  "relation_semantically_supported", "scope_decidable",
                  "strict_eligible", "recommended_state"):
        agree = 0
        f_pairs = []
        for f in both:
            va = verdicts[f]["A"]["verdict"][field]
            vb = verdicts[f]["B"]["verdict"][field]
            if va == vb:
                agree += 1
            f_pairs.append((va, vb))
        res_fields[field] = wilson(agree, n)
        if field == "recommended_state":
            pairs = f_pairs
    strict_opport_A = sum(1 for f in both
                          if verdicts[f]["A"]["verdict"]["strict_eligible"] == "YES")
    strict_opport_B = sum(1 for f in both
                          if verdicts[f]["B"]["verdict"]["strict_eligible"] == "YES")
    strict_opport_cons = sum(
        1 for f in both
        if verdicts[f]["A"]["verdict"]["strict_eligible"] == "YES"
        and verdicts[f]["B"]["verdict"]["strict_eligible"] == "YES")

    ctx_both = [f for f in both if key[f]["pre_gate_tier"].upper() == "CONTEXTUAL"]
    unr_both = [f for f in both if key[f]["pre_gate_tier"].upper() == "UNRESOLVED"]

    def weighted_strict(subset):
        """总体加权 STRICT 机会率（按 blocker stratum 权重还原）。"""
        num = den = 0.0
        for f in subset:
            r = ledger.get(f) or {}
            st = (r.get("pre_gate_tier", "").upper(),
                  r.get("primary_blocking_reason", ""))
            w = (stratum_pop[st] / stratum_smp[st]) if stratum_smp[st] else 1.0
            yes = (verdicts[f]["A"]["verdict"]["strict_eligible"] == "YES"
                   and verdicts[f]["B"]["verdict"]["strict_eligible"] == "YES")
            den += w
            num += w * (1 if yes else 0)
        return round(num / den, 4) if den else None

    per_blocker = defaultdict(lambda: {"n": 0, "strict_cons": 0})
    for f in both:
        r = ledger.get(f) or {}
        st = r.get("primary_blocking_reason", "")
        per_blocker[st]["n"] += 1
        if (verdicts[f]["A"]["verdict"]["strict_eligible"] == "YES"
                and verdicts[f]["B"]["verdict"]["strict_eligible"] == "YES"):
            per_blocker[st]["strict_cons"] += 1

    exact_agree = sum(
        1 for f in both
        if verdicts[f]["A"]["verdict"]["recommended_state"]
        == verdicts[f]["B"]["verdict"]["recommended_state"]
        == key[f]["pre_gate_tier"].upper())

    results = {
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "n_both_judged": n,
        "judge_raw_agreement": wilson(agree5 := sum(
            1 for f in both
            if verdicts[f]["A"]["verdict"]["evidence_support"]
            == verdicts[f]["B"]["verdict"]["evidence_support"]), n),
        "strong_consensus_evidence_support": wilson(agree5, n),
        "cohens_kappa_evidence_support": cohens_kappa(pairs),
        "recommended_state_agreement": res_fields["recommended_state"],
        "identity_decidable_agreement": res_fields["identity_decidable"],
        "relation_supported_agreement": res_fields["relation_semantically_supported"],
        "scope_decidable_agreement": res_fields["scope_decidable"],
        "strict_eligible_agreement": res_fields["strict_eligible"],
        "strict_opportunity_judgeA": wilson(strict_opport_A, n),
        "strict_opportunity_judgeB": wilson(strict_opport_B, n),
        "strict_opportunity_strong_consensus": wilson(strict_opport_cons, n),
        "strict_opportunity_weighted_population": weighted_strict(both),
        "contextual_strict_opportunity_rate":
            wilson(sum(1 for f in ctx_both
                       if verdicts[f]["A"]["verdict"]["strict_eligible"] == "YES"
                       and verdicts[f]["B"]["verdict"]["strict_eligible"] == "YES"),
                   len(ctx_both)) if ctx_both else None,
        "unresolved_strict_opportunity_rate":
            wilson(sum(1 for f in unr_both
                       if verdicts[f]["A"]["verdict"]["strict_eligible"] == "YES"
                       and verdicts[f]["B"]["verdict"]["strict_eligible"] == "YES"),
                   len(unr_both)) if unr_both else None,
        "outside_gate_exact_tier_agreement": wilson(exact_agree, n),
        "per_blocker_strict_opportunity": {
            k: wilson(v["strict_cons"], v["n"])
            for k, v in sorted(per_blocker.items())},
        "stratum_weights_sample": {f"{t}|{r}": {"pop": stratum_pop[(t, r)],
                                                "sampled": stratum_smp[(t, r)]}
                                   for (t, r) in sorted(stratum_pop)},
    }
    (OUT / "OUTSIDE_GATE_AUDIT_RESULTS.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[score] n={n} raw5={results['judge_raw_agreement']['point']} "
          f"kappa={results['cohens_kappa_evidence_support']} "
          f"strict_cons={results['strict_opportunity_strong_consensus']['point']} "
          f"weighted_pop={results['strict_opportunity_weighted_population']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
