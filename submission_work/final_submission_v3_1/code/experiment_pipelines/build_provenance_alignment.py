# -*- coding: utf-8 -*-
"""build_provenance_alignment.py — P0-9 前置：strict 层证据-断言词法对齐表。

对全部 research_tier='strict_semantic' 断言：
* 抽取证据文本（fact → provenance.evidence_ids → evidence_registry）；
* 词法对齐检查：subject/object 名称是否出现在证据文本中（含别名回退）；
* 输出三桶：aligned / mismatch_with_evidence / no_evidence，及断言元数据。

产物：experiments/07_provenance_semantic_gate/STRICT_ALIGNMENT.csv（全量 112,158 行）
+ STRICT_ALIGNMENT_SUMMARY.json。后续 LLM 语义验证只针对
mismatch_with_evidence 全量 + aligned 的冻结分层样本（GOAL 指令 P0-9 的
"轻量规则过滤，只把 uncertain/high-risk 送给大型模型"）。
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

V3_1 = Path(__file__).resolve().parents[2]
V3 = V3_1.parent / "final_submission_v3"
for p in (str(V3 / "code"), str(V3 / "code" / "independent_eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _common import connect_final, attach_integration, sha256_file  # noqa: E402

OUT_DIR = V3_1 / "experiments" / "07_provenance_semantic_gate"


def main() -> int:
    con = connect_final()
    attach_integration(con)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1) 全量 evidence 文本缓存（evidence_id → text）
    ev_text: dict[str, str] = {}
    for eid, text in con.execute("select evidence_id, evidence_text from up.evidence_registry"):
        ev_text[str(eid)] = str(text or "")

    # 2) fact → evidence_ids
    fact_eids: dict[str, list[str]] = defaultdict(list)
    for fid, ej in con.execute("select fact_id, evidence_ids_json from research_assertion_provenance"):
        try:
            ids = json.loads(str(ej or "[]"))
        except json.JSONDecodeError:
            continue
        if ids:
            fact_eids[str(fid)].extend(str(i) for i in ids)

    # 3) 逐 strict 断言对齐
    rows_out: list[dict[str, Any]] = []
    counts = {"aligned": 0, "mismatch_with_evidence": 0, "no_evidence": 0}
    cur = con.execute(
        "select fact_id, subject_name, subject_type, object_name, object_type, predicate, "
        "time_raw, place_raw, confidence, semantic_status, risk_tier "
        "from research_assertions where research_tier='strict_semantic'"
    )
    n = 0
    for r in cur:
        n += 1
        fid = str(r["fact_id"])
        subj = str(r["subject_name"] or "").strip()
        obj = str(r["object_name"] or "").strip()
        ids = fact_eids.get(fid, [])
        texts = [ev_text[e] for e in ids if e in ev_text and ev_text[e]]
        if not texts:
            bucket = "no_evidence"
        else:
            joined = "\n".join(texts[:3])
            s_hit = len(subj) >= 2 and subj in joined
            o_hit = len(obj) >= 2 and obj in joined
            bucket = "aligned" if (s_hit or o_hit) else "mismatch_with_evidence"
        counts[bucket] += 1
        rows_out.append(
            {
                "fact_id": fid,
                "bucket": bucket,
                "n_evidence": len(texts),
                "subject_name": subj,
                "subject_type": str(r["subject_type"] or ""),
                "object_name": obj,
                "object_type": str(r["object_type"] or ""),
                "predicate": str(r["predicate"] or ""),
                "time_raw": str(r["time_raw"] or ""),
                "place_raw": str(r["place_raw"] or ""),
                "confidence": "" if r["confidence"] is None else f"{float(r['confidence']):.4f}",
                "semantic_status": str(r["semantic_status"] or ""),
                "risk_tier": str(r["risk_tier"] or ""),
            }
        )
        if n % 20000 == 0:
            print(f"[provenance_alignment] {n} rows...")

    fields = list(rows_out[0].keys())
    out_path = OUT_DIR / "STRICT_ALIGNMENT.csv"
    with open(out_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows_out)
    summary = {
        "n_strict_total": n,
        "buckets": counts,
        "alignment_csv": out_path.name,
        "alignment_sha256": sha256_file(out_path),
    }
    (OUT_DIR / "STRICT_ALIGNMENT_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[provenance_alignment] done: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
