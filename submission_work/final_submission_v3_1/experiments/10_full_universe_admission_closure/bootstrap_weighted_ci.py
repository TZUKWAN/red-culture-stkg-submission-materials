# -*- coding: utf-8 -*-
"""bootstrap_weighted_ci.py — 加权总体 STRICT 机会率的设计型置信区间。

样本按层设计（CONTEXTUAL 2,500 / UNRESOLVED 2,500），但两层总体规模悬殊
（268,047 / 43,945），未加权 CI 不可用于加权总体估计。按抽样设计做分层自助：
每层内有放回重采样 → 层内强共识 STRICT 机会率 → 按总体规模加权混合 →
重复 10,000 次取 2.5/97.5 分位。写回 OUTSIDE_GATE_AUDIT_RESULTS.json。
"""
from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

V31 = Path(__file__).resolve().parents[2]
OUT = V31 / "experiments" / "10_full_universe_admission_closure"
CN_TZ = timezone(timedelta(hours=8))

SEED = 20260916          # 与抽样协议同族种子（用途：bootstrap，独立消耗）
B = 10_000
POP = {"CONTEXTUAL": 268_047, "UNRESOLVED": 43_945}
POP_TOTAL = sum(POP.values())   # 311,992


def main() -> int:
    ledger = {}
    with open(OUT / "FULL_UNIVERSE_ADMISSION_LEDGER.csv", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            ledger[r["fact_id"]] = r

    verdicts: dict[str, dict] = {}
    for j, fn in (("A", "JUDGE_gpt_oss_20b_VERDICTS.jsonl"),
                  ("B", "JUDGE_qwen_qwen3_8b_VERDICTS.jsonl")):
        for line in open(OUT / fn, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                if r.get("parse_ok"):
                    verdicts.setdefault(r["fact_id"], {})[j] = r

    layer_yes: dict[str, list[int]] = {"CONTEXTUAL": [], "UNRESOLVED": []}
    for fid, v in verdicts.items():
        if "A" not in v or "B" not in v:
            continue
        r = ledger.get(fid)
        if not r or r["in_evidence_gate_universe"] != "0":
            continue
        tier = r["pre_gate_tier"].upper()
        if tier not in POP:
            continue
        yes = (v["A"]["verdict"]["strict_eligible"] == "YES"
               and v["B"]["verdict"]["strict_eligible"] == "YES")
        layer_yes[tier].append(1 if yes else 0)

    for t in POP:
        n_t = len(layer_yes[t])
        print(f"[bootstrap] layer {t}: n={n_t}, k={sum(layer_yes[t])}, "
              f"rate={sum(layer_yes[t]) / n_t:.4f}")

    rng = random.Random(SEED)
    n_ctx, n_unr = len(layer_yes["CONTEXTUAL"]), len(layer_yes["UNRESOLVED"])
    d_ctx, d_unr = layer_yes["CONTEXTUAL"], layer_yes["UNRESOLVED"]
    pops = []
    for _ in range(B):
        rc = sum(d_ctx[rng.randrange(n_ctx)] for _ in range(n_ctx)) / n_ctx
        ru = sum(d_unr[rng.randrange(n_unr)] for _ in range(n_unr)) / n_unr
        pops.append((rc * POP["CONTEXTUAL"] + ru * POP["UNRESOLVED"]) / POP_TOTAL)
    pops.sort()
    lo, hi = pops[int(0.025 * B)], pops[int(0.975 * B) - 1]

    pt = (sum(d_ctx) / n_ctx * POP["CONTEXTUAL"]
          + sum(d_unr) / n_unr * POP["UNRESOLVED"]) / POP_TOTAL

    result = {
        "method": "stratified bootstrap (per-layer with replacement, "
                  "population-weighted mixture)",
        "bootstrap_seed": SEED,
        "bootstrap_iterations": B,
        "layers": {t: {"population": POP[t], "sample_n": len(layer_yes[t]),
                       "yes": sum(layer_yes[t]),
                       "rate": round(sum(layer_yes[t]) / len(layer_yes[t]), 6)}
                   for t in POP},
        "weighted_point": round(pt, 6),
        "weighted_ci95": [round(lo, 6), round(hi, 6)],
        "population_count_interval": [int(round(lo * POP_TOTAL)),
                                      int(round(hi * POP_TOTAL))],
        "population_total": POP_TOTAL,
        "note": "未加权样本口径 0.63% [0.0044,0.0089] 仅描述样本；"
                "加权总体推断以本设计型 CI 为准。",
        "updated_at": datetime.now(CN_TZ).isoformat(),
    }
    res_path = OUT / "OUTSIDE_GATE_AUDIT_RESULTS.json"
    res = json.loads(res_path.read_text(encoding="utf-8"))
    res["weighted_strict_opportunity_design_ci"] = result
    res_path.write_text(json.dumps(res, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[bootstrap] weighted point={pt:.4f} CI=[{lo:.4f}, {hi:.4f}] "
          f"count=[{result['population_count_interval'][0]:,}, "
          f"{result['population_count_interval'][1]:,}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
