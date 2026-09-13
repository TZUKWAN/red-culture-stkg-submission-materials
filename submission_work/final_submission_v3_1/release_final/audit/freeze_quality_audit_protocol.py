# -*- coding: utf-8 -*-
"""freeze_quality_audit_protocol.py — PHASE 2.1：预注册质量审计协议（冻结）。

在查看任何独立 Judge 输出之前生成并冻结本协议。内容含抽样策略、分层配额、
裁判配置、共识规则、主指标、降级/重判触发线、随机种子。冻结后禁止修改。
"""
from __future__ import annotations

import csv
import gzip
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "experiments" / "07_provenance_semantic_gate"
OUTD = ROOT / "release_final" / "configs"
AUD = ROOT / "release_final" / "experiments" / "quality_audit"
CN_TZ = timezone(timedelta(hours=8))

SEED = 20260914
LABELS = ["FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED",
          "CONTRADICTED", "INSUFFICIENT"]
TIER_BUDGET = {"STRICT": 2000, "CONTEXTUAL": 1000, "UNRESOLVED": 1000}
STRATUM_MIN = {"aligned": 0.40, "mismatch_with_evidence": 0.10,
               "recovery_A": 0.075, "recovery_B": 0.25, "recovery_C": 0.175}
PRED_OVERLAY = 30          # 每个 partial→strict predicate 在 STRICT 内保证样本
BOUNDARY_LOW_N = 100       # 生产置信度 ≤0.55
BOUNDARY_HIGH_N = 100      # 生产置信度 ≥0.95
SALVAGE_ALL = True         # 17 条 salvaged 全审

JUDGES = ["gpt-oss-20b", "qwen3-8b"]
CONSENSUS = {
    "strong": "两裁判五档判定完全一致",
    "weak": "两裁判在支持/不支持粗分组（{FULLY,PARTIAL} vs {UNSUPPORTED,CONTRADICTED} vs {INSUFFICIENT}）一致但五档不同",
    "none": "粗分组都不一致",
}
TRIGGERS = {
    "PASS": "STRICT strong-consensus support precision >= 0.90 且 salvaged 错误 <= 2/17",
    "INVESTIGATE_LOCAL": "precision 在 [0.80,0.90) 或单一 stratum/predicate 系统性偏差 -> 仅对该层局部重判",
    "ESCALATE": "precision < 0.80 或 salvage 系统性错误 -> 全量 re-adjudication 评估（硬阻断，须记录）",
}


def main() -> int:
    AUD.mkdir(parents=True, exist_ok=True)
    OUTD.mkdir(parents=True, exist_ok=True)

    # 从 FINAL_TIERING.csv + checkpoint gz 建立候选池
    tier_of: dict[str, str] = {}
    for r in csv.DictReader(open(GATE / "FINAL_TIERING.csv", encoding="utf-8-sig")):
        tier_of[r["fact_id"]] = r["final_tier"]

    pool: dict[str, dict] = {}
    with gzip.open(GATE / "FINAL_TIERING_CHECKPOINT.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            fid = rec.get("fact_id")
            if not fid or rec.get("model") != "qwen3.5-4b":
                continue
            if rec.get("decision") in LABELS and fid not in pool:
                pass
            # 后写覆盖：保留最后一次记录（与生产 loader 同口径）
            pool[fid] = rec

    rng = random.Random(SEED)
    by_tier_stratum: dict[tuple, list[str]] = defaultdict(list)
    for fid, rec in pool.items():
        t = tier_of.get(fid)
        st = rec.get("stratum", "")
        if t in TIER_BUDGET and st in STRATUM_MIN:
            by_tier_stratum[(t, st)].append(fid)
    for k in by_tier_stratum:
        rng.shuffle(by_tier_stratum[k])

    sample: dict[str, dict] = {}

    def take(fid: str, reason: str) -> None:
        if fid in sample:
            sample[fid]["reasons"].append(reason)
        else:
            rec = pool[fid]
            sample[fid] = {
                "fact_id": fid, "reasons": [reason],
                "assertion": rec.get("assertion", ""),
                "evidence_text": rec.get("evidence_text", ""),
                "stratum": rec.get("stratum", ""),
                "predicate": rec.get("predicate", ""),
            }

    # 主配额：每层按 STRATUM_MIN 比例分配
    alloc: Counter = Counter()
    for tier, budget in TIER_BUDGET.items():
        for st, share in STRATUM_MIN.items():
            k = min(int(budget * share), len(by_tier_stratum[(tier, st)]))
            for fid in by_tier_stratum[(tier, st)][:k]:
                take(fid, f"quota:{tier}:{st}")
                alloc[(tier, st)] += 1

    # predicate overlay：partial→strict predicates 在 STRICT 内保证样本
    policy = json.loads((GATE / "FINAL_TIERING_POLICY.json").read_text(encoding="utf-8"))
    preds = set(policy.get("partial_strict_preds", []))
    by_pred: dict[str, list[str]] = defaultdict(list)
    for fid, rec in pool.items():
        if tier_of.get(fid) == "STRICT" and rec.get("predicate") in preds:
            by_pred[rec["predicate"]].append(fid)
    for p in by_pred:
        rng.shuffle(by_pred[p])
    for p, fids in by_pred.items():
        for fid in fids[:PRED_OVERLAY]:
            take(fid, f"predicate_overlay:{p}")

    # 边界置信度 + salvaged
    low = [f for f, r in pool.items() if isinstance(r.get("confidence"), (int, float))
           and r["confidence"] <= 0.55 and tier_of.get(f) in TIER_BUDGET]
    high = [f for f, r in pool.items() if isinstance(r.get("confidence"), (int, float))
            and r["confidence"] >= 0.95 and tier_of.get(f) in TIER_BUDGET]
    rng.shuffle(low)
    rng.shuffle(high)
    for fid in low[:BOUNDARY_LOW_N]:
        take(fid, "boundary_low_conf")
    for fid in high[:BOUNDARY_HIGH_N]:
        take(fid, "boundary_high_conf")
    salv = [f for f, r in pool.items() if r.get("salvaged")]
    for fid in salv:
        take(fid, "parser_salvaged")

    items = list(sample.values())
    rng.shuffle(items)

    # 冻结协议 + 盲样本 + 评分钥（生产判定只进 KEY，不进盲样本）
    protocol = {
        "task": "FINAL QUALITY AUDIT — 预注册协议（冻结后不得修改）",
        "frozen_at": datetime.now(CN_TZ).isoformat(),
        "seed": SEED,
        "universe": "FINAL_TIERING 112,158（recovery_D 无证据不可评，排除并记录）",
        "sample_sizes": {"STRICT": TIER_BUDGET["STRICT"],
                         "CONTEXTUAL": TIER_BUDGET["CONTEXTUAL"],
                         "UNRESOLVED": TIER_BUDGET["UNRESOLVED"],
                         "overlay_predicate_per_pred": PRED_OVERLAY,
                         "boundary_low": BOUNDARY_LOW_N, "boundary_high": BOUNDARY_HIGH_N,
                         "salvaged": len(salv)},
        "actual_sample_n": len(items),
        "actual_alloc_by_tier_stratum": {f"{t}|{s}": n for (t, s), n in sorted(alloc.items())},
        "judges": JUDGES,
        "judge_blindness": "裁判仅见 assertion + evidence_text + 五档定义；禁止见到生产 tier/decision/confidence",
        "labels": LABELS,
        "consensus_rules": CONSENSUS,
        "primary_metrics": [
            "strict_support_precision（强共识口径：STRICT 样本中裁判强共识判支持 FULLY/PARTIAL 的比例）",
            "fully_supported_precision",
            "false_positive_rate（STRICT 被强共识判 UNSUPPORTED/CONTRADICTED）",
            "contextual_upgrade_opportunity（CONTEXTUAL 被强共识判 FULLY）",
            "unresolved_false_negative_opportunity（UNRESOLVED 被强共识判 FULLY/PARTIAL）",
            "judge_raw_agreement", "fleiss_kappa",
        ],
        "triggers": TRIGGERS,
        "freezing_note": "本文件与 SAMPLE_AUDIT.json 在任何 Judge 运行前生成；Judge 输出只能写入 JUDGE_*_VERDICTS.jsonl。",
    }
    (OUTD / "FINAL_QUALITY_AUDIT_PROTOCOL.json").write_text(
        json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")

    blind = [{"fact_id": it["fact_id"], "assertion": it["assertion"],
              "evidence_text": it["evidence_text"], "stratum": it["stratum"],
              "predicate": it["predicate"]} for it in items]
    (AUD / "SAMPLE_AUDIT.json").write_text(
        json.dumps({"seed": SEED, "n": len(blind), "items": blind},
                   ensure_ascii=False), encoding="utf-8")
    key = {it["fact_id"]: {"production_tier": tier_of.get(it["fact_id"]),
                           "production_decision": pool[it["fact_id"]].get("decision"),
                           "production_confidence": pool[it["fact_id"]].get("confidence"),
                           "salvaged": bool(pool[it["fact_id"]].get("salvaged")),
                           "reasons": it["reasons"]}
           for it in items}
    (AUD / "SAMPLE_KEY.json").write_text(
        json.dumps(key, ensure_ascii=False), encoding="utf-8")

    print(f"[protocol] frozen: sample n={len(items)} "
          f"(tiers={Counter(tier_of.get(it['fact_id']) for it in items)})")
    print(f"[protocol] judges={JUDGES} triggers={list(TRIGGERS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
