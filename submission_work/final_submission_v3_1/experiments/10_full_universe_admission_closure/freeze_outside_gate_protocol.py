# -*- coding: utf-8 -*-
"""freeze_outside_gate_protocol.py — 门外宇宙独立审计协议（预注册冻结）。

seed=20260916；CONTEXTUAL 2,500 + UNRESOLVED 2,500；
分层键：primary_blocking_reason → predicate → source_book；
任何 population>=500 的主要 blocking stratum 至少 50 条；
剩余配额按总体规模比例分配（最大比例法）。
"""
from __future__ import annotations

import csv
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

V31 = Path(__file__).resolve().parents[2]
OUT = V31 / "experiments" / "10_full_universe_admission_closure"
LEDGER = OUT / "FULL_UNIVERSE_ADMISSION_LEDGER.csv"
CN_TZ = timezone(timedelta(hours=8))

SEED = 20260916
BUDGET = {"CONTEXTUAL": 2500, "UNRESOLVED": 2500}
MIN_STRATUM_N = 50
MIN_POP = 500

JUDGES = ["gpt-oss-20b", "qwen/qwen3-8b"]


def main() -> int:
    (OUT / "OUTSIDE_GATE_SAMPLE.jsonl").parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    # 读台账（门外部分）
    pool: dict[str, dict] = {}
    with open(LEDGER, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["in_evidence_gate_universe"] == "0":
                pool[r["fact_id"]] = r
    by_tier: dict[str, list[str]] = defaultdict(list)
    for fid, r in pool.items():
        by_tier[r["pre_gate_tier"].upper()].append(fid)

    sample: dict[str, dict] = {}

    def take(fid: str, stratum: str) -> None:
        if fid in sample:
            sample[fid]["strata"].append(stratum)
        else:
            r = pool[fid]
            sample[fid] = {"fact_id": fid, "strata": [stratum],
                           "pre_gate_tier": r["pre_gate_tier"],
                           "predicate": r["predicate"],
                           "primary_blocking_reason": r["primary_blocking_reason"],
                           "source_book": r["source_book"]}

    alloc_report = {}
    for tier, budget in BUDGET.items():
        fids = by_tier[tier]
        # 主要 blocking stratum（population>=500 至少 50 条）
        by_reason: dict[str, list[str]] = defaultdict(list)
        for f in fids:
            by_reason[pool[f]["primary_blocking_reason"]].append(f)
        remaining = budget
        for reason, lst in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
            if len(lst) >= MIN_POP:
                k = min(MIN_STRATUM_N, len(lst))
                for f in rng.sample(lst, k):
                    take(f, f"min50:{reason}")
                remaining -= k
                alloc_report[f"{tier}|min50:{reason}"] = k
        # 剩余按 predicate × book 比例分配
        rest = [f for f in fids if f not in sample]
        rng.shuffle(rest)
        k = min(remaining, len(rest))
        for f in rest[:k]:
            take(f, f"proportional:{tier}")
        alloc_report[f"{tier}|proportional"] = k

    items = list(sample.values())
    rng.shuffle(items)

    protocol = {
        "frozen_at": datetime.now(CN_TZ).isoformat(),
        "seed": SEED,
        "population": {"outside_gate_total": len(pool),
                       "contextual": BUDGET["CONTEXTUAL"] and len(by_tier["CONTEXTUAL"]),
                       "unresolved": len(by_tier["UNRESOLVED"])},
        "sample_sizes": BUDGET,
        "actual_n": len(items),
        "stratification": "primary_blocking_reason(min50 if pop>=500) → predicate → source_book; 余量按比例",
        "allocation": alloc_report,
        "judges": JUDGES,
        "blindness": "裁判仅见断言/实体/类型/证据原文/时间/空间；禁止见 tier/blocking reason/decision path/生产判定/置信度",
        "judge_output_schema": {
            "evidence_support": ["FULLY_SUPPORTED", "PARTIALLY_SUPPORTED",
                                 "INSUFFICIENT", "UNSUPPORTED", "CONTRADICTED",
                                 "NO_EVIDENCE"],
            "identity_decidable": ["YES", "NO", "UNCERTAIN"],
            "relation_semantically_supported": ["YES", "NO", "UNCERTAIN"],
            "scope_decidable": ["YES", "NO", "UNCERTAIN"],
            "strict_eligible": ["YES", "NO", "UNCERTAIN"],
            "recommended_state": ["STRICT", "CONTEXTUAL", "UNRESOLVED"],
            "reason": "<一句话中文>",
        },
        "metrics": ["judge_raw_agreement", "cohens_kappa", "strong_consensus_rate",
                    "contextual_strict_opportunity_rate",
                    "unresolved_strict_opportunity_rate",
                    "outside_gate_exact_tier_agreement",
                    "per_blocker_strict_opportunity_rate"],
        "estimation": "每个比例给 point estimate + Wilson 95% CI + raw numerator/denominator；"
                      "总体推断用 stratum 权重 w=N_stratum/n_stratum 加权",
        "freezing_note": "本文件在 Any Judge 运行前生成；判后不得修改。",
    }
    (OUT / "OUTSIDE_GATE_AUDIT_PROTOCOL.json").write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(OUT / "OUTSIDE_GATE_SAMPLE.jsonl", "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")

    print(f"[protocol] frozen: n={len(items)} "
          f"(tiers={Counter(i['pre_gate_tier'] for i in items)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
