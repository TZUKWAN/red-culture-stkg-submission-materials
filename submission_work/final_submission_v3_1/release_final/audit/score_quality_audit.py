# -*- coding: utf-8 -*-
"""score_quality_audit.py — PHASE 2.3：独立审计评分与触发决策。

读取 SAMPLE_KEY.json（生产判定，评分时才解盲）+ 两裁判判定文件，计算冻结协议
的主指标（强共识支撑精度 / FP 率 / 升级机会 / 一致性 kappa / 分层与谓词分解 /
salvaged 审计），按 TRIGGERS 输出 PASS / INVESTIGATE_LOCAL / ESCALATE 决策。
产物：release_final/experiments/quality_audit/{AUDIT_RESULTS.json, AUDIT_REPORT.md}
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUD = ROOT / "release_final" / "experiments" / "quality_audit"
CN_TZ = timezone(timedelta(hours=8))

LABELS = ["FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED",
          "CONTRADICTED", "INSUFFICIENT"]
GROUP = {"FULLY_SUPPORTED": "SUP", "PARTIALLY_SUPPORTED": "SUP",
         "UNSUPPORTED": "NEG", "CONTRADICTED": "NEG", "INSUFFICIENT": "INSUF"}
JUDGES = {"A": "JUDGE_gpt_oss_20b_VERDICTS.jsonl",
          "B": "JUDGE_qwen_qwen3_8b_VERDICTS.jsonl"}
SUPPORT = {"FULLY_SUPPORTED", "PARTIALLY_SUPPORTED"}


def load_jsonl(name: str) -> dict:
    out = {}
    p = AUD / name
    if not p.exists():
        return out
    for line in p.open(encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if r.get("parse_ok"):
                out[r["fact_id"]] = r
    return out


def cohens_kappa(pairs: list[tuple[str, str]]) -> float | None:
    n = len(pairs)
    if n == 0:
        return None
    po = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[l] * cb[l] for l in set(ca) | set(cb)) / (n * n)
    return None if pe == 1 else round((po - pe) / (1 - pe), 4)


def main() -> int:
    key = json.loads((AUD / "SAMPLE_KEY.json").read_text(encoding="utf-8"))
    va = load_jsonl(JUDGES["A"])
    vb = load_jsonl(JUDGES["B"])
    both = [fid for fid in key if fid in va and fid in vb]
    now = datetime.now(CN_TZ).isoformat()
    if len(both) < len(key) * 0.5:
        print(f"[score] 裁判覆盖不足：A={len(va)} B={len(vb)} 共同={len(both)}/{len(key)}")
        return 1

    agree5 = weak = dis = 0
    kappa_pairs = []
    per = {}
    strict_tot = strict_sup = strict_fp = strict_fully = 0
    ctx_tot = ctx_up = 0
    unres_tot = unres_fn = 0
    by_stratum: dict[str, dict] = defaultdict(lambda: {"n": 0, "sup": 0, "fp": 0})
    by_pred_sup: dict[str, list] = defaultdict(list)
    salvage_audit = []

    for fid in both:
        k, a, b = key[fid], va[fid], vb[fid]
        da, db = a["decision"], b["decision"]
        kappa_pairs.append((da, db))
        tier = k["production_tier"]
        if da == db:
            agree5 += 1
        elif GROUP[da] == GROUP[db]:
            weak += 1
        else:
            dis += 1
        strong = da == db
        cons = da if strong else None
        rec = {"tier": tier, "stratum": k.get("reasons", [""])[0].split(":")[-1],
               "strong": strong, "a": da, "b": db}
        per[fid] = rec
        if strong:
            st = rec["stratum"]
            if a.get("salvaged"):
                salvage_audit.append({"fact_id": fid, "production": k["production_decision"],
                                      "consensus": cons})
            if tier == "STRICT":
                strict_tot += 1
                by_stratum[st]["n"] += 1
                if cons in SUPPORT:
                    strict_sup += 1
                    by_stratum[st]["sup"] += 1
                if cons == "FULLY_SUPPORTED":
                    strict_fully += 1
                if cons in ("UNSUPPORTED", "CONTRADICTED"):
                    strict_fp += 1
                    by_stratum[st]["fp"] += 1
            elif tier == "CONTEXTUAL":
                ctx_tot += 1
                if cons == "FULLY_SUPPORTED":
                    ctx_up += 1
            elif tier == "UNRESOLVED":
                unres_tot += 1
                if cons in SUPPORT:
                    unres_fn += 1

    # salvaged 审计需强共识；无强共识者标注 unresolved_consensus
    salv_all_ids = [f for f in both if va[f].get("salvaged") or vb[f].get("salvaged")]
    salvage_audit = [{"fact_id": f, "production": key[f]["production_decision"],
                      "a": va[f]["decision"], "b": vb[f]["decision"],
                      "strong": va[f]["decision"] == vb[f]["decision"]}
                     for f in salv_all_ids]
    salvage_bad = sum(
        1 for s in salvage_audit
        if s["strong"] and s["production"] in LABELS
        and GROUP[s["a"]] != GROUP[s["production"]])

    kappa = cohens_kappa(kappa_pairs)
    n = len(both)
    results = {
        "generated_at": now,
        "n_judged_both": n,
        "judge_raw_agreement": round(agree5 / n, 4),
        "weak_consensus_rate": round(weak / n, 4),
        "no_consensus_rate": round(dis / n, 4),
        "cohens_kappa": kappa,
        "strict_support_precision_strong_consensus":
            round(strict_sup / strict_tot, 4) if strict_tot else None,
        "fully_supported_precision":
            round(strict_fully / strict_tot, 4) if strict_tot else None,
        "strict_false_positive_rate":
            round(strict_fp / strict_tot, 4) if strict_tot else None,
        "contextual_upgrade_opportunity":
            round(ctx_up / ctx_tot, 4) if ctx_tot else None,
        "unresolved_false_negative_opportunity":
            round(unres_fn / unres_tot, 4) if unres_tot else None,
        "by_stratum": {k: v for k, v in sorted(by_stratum.items())},
        "salvage_audit": salvage_audit,
        "salvage_strong_consensus_mismatch": salvage_bad,
        "protocol_triggers": {
            "PASS": "strict_support_precision >= 0.90 且 salvage mismatch <= 2",
            "INVESTIGATE_LOCAL": "[0.80, 0.90) 或单层系统偏差",
            "ESCALATE": "< 0.80 或 salvage 系统性错误",
        },
    }
    sp = results["strict_support_precision_strong_consensus"]
    if sp is None:
        decision = "INSUFFICIENT_DATA"
    elif sp >= 0.90 and salvage_bad <= 2:
        decision = "PASS"
    elif sp >= 0.80:
        decision = "INVESTIGATE_LOCAL"
    else:
        decision = "ESCALATE"
    results["decision"] = decision

    (AUD / "AUDIT_RESULTS.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    report = f"""# FINAL QUALITY AUDIT REPORT（独立双裁判盲评）

- 生成：{now}
- 样本：{len(key)} 条（协议冻结 n）；两裁判共同有效判定：{n}
- 裁判：Judge A = gpt-oss-20b，Judge B = qwen/qwen3-8b（均为本地、独立于生产模型 qwen3.5-4b）

## 主指标
| 指标 | 数值 |
|---|---|
| 裁判五档完全一致率 | {results['judge_raw_agreement']} |
| Cohen's kappa | {kappa} |
| 弱共识率（粗分组一致） | {results['weak_consensus_rate']} |
| STRICT 支撑精度（强共识口径） | **{sp}** |
| FULLY 精度 | {results['fully_supported_precision']} |
| STRICT 误报率（强共识判 UNSUP/CONTRA） | {results['strict_false_positive_rate']} |
| CONTEXTUAL 升级机会 | {results['contextual_upgrade_opportunity']} |
| UNRESOLVED 漏判机会 | {results['unresolved_false_negative_opportunity']} |
| salvaged 强共识不一致数 | {salvage_bad}/{len(salvage_audit)} |

## 协议决策：**{decision}**

（详见 AUDIT_RESULTS.json；分层分解见 by_stratum。）
"""
    (AUD / "AUDIT_REPORT.md").write_text(report, encoding="utf-8")
    print(f"[score] n={n} agree={results['judge_raw_agreement']} kappa={kappa} "
          f"strict_precision={sp} decision={decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
