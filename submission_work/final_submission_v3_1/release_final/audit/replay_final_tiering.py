# -*- coding: utf-8 -*-
"""replay_final_tiering.py — PHASE 1：Level-A 离线精确回放与逐行对账。

三件事（不 import 生产链代码，按冻结 policy 独立实现，构成交叉验证）：
  1. checkpoint 完整性：gzip 流式解压、逐行 JSON parse、模型/判定/salvage 统计、
     重建"每 fact_id 最后一次有效 verdict"；
  2. 从 checkpoint + EVIDENCE_GATE_VERDICTS(dev) + FINAL_TIERING_POLICY.json 独立
     重建 FINAL_TIERING_REBUILT.csv；
  3. 与 FINAL_TIERING.csv 逐行比较（id 集 / gate_method / semantic_support /
     final_tier / evidence_localizable），输出 REBUILD_DIFF.json。

产物：release_final/audit/{CHECKPOINT_INTEGRITY_REPORT.json,
FINAL_TIERING_REBUILT.csv, REBUILD_DIFF.json}
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "experiments" / "07_provenance_semantic_gate"
OUTD = ROOT / "release_final" / "audit"
CN_TZ = timezone(timedelta(hours=8))

LABELS = {"FULLY_SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED",
          "CONTRADICTED", "INSUFFICIENT"}
TIER_OF = {"FULLY_SUPPORTED": "STRICT", "UNSUPPORTED": "UNRESOLVED",
           "CONTRADICTED": "UNRESOLVED", "INSUFFICIENT": "CONTEXTUAL"}

CKPT_GZ = GATE / "FINAL_TIERING_CHECKPOINT.jsonl.gz"
DEV = GATE / "EVIDENCE_GATE_VERDICTS.jsonl"
POLICY = GATE / "FINAL_TIERING_POLICY.json"
ALIGN = GATE / "STRICT_ALIGNMENT.csv"
RECOV = GATE / "EVIDENCE_RECOVERY.csv"
FEATS = GATE / "FINAL_TIERING_FEATURES.csv"
FINAL_CSV = GATE / "FINAL_TIERING.csv"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_jsonl(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def parse_bool(v: str) -> bool:
    return v.strip() in ("1", "True", "true")


def main() -> int:
    OutInt = OUTD / "CHECKPOINT_INTEGRITY_REPORT.json"
    OutReb = OUTD / "FINAL_TIERING_REBUILT.csv"
    OutDiff = OUTD / "REBUILD_DIFF.json"
    OUTD.mkdir(parents=True, exist_ok=True)

    # ---------- 1. checkpoint 完整性 ----------
    total = 0
    malformed = 0
    models = Counter()
    decisions = Counter()
    salvaged = 0
    per_fact_hist: Counter = Counter()
    last_valid: dict[str, dict] = {}     # qwen 最后一次有效五档 verdict
    last_any: dict[str, dict] = {}
    with gzip.open(CKPT_GZ, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            fid = rec.get("fact_id")
            if not fid:
                continue
            models[rec.get("model", "?")] += 1
            decisions[rec.get("decision", "?")] += 1
            if rec.get("salvaged"):
                salvaged += 1
            per_fact_hist[fid] += 1
            last_any[fid] = rec
            if rec.get("model") == "qwen3.5-4b" and rec.get("decision") in LABELS:
                last_valid[fid] = rec     # 后写覆盖先写

    multi = {f: c for f, c in per_fact_hist.items() if c > 1}
    integrity = {
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "checkpoint_gz": str(CKPT_GZ.relative_to(ROOT.parents[1])),
        "sha256": sha256(CKPT_GZ),
        "records_total": total,
        "malformed_json": malformed,
        "unique_fact_ids": len(last_any),
        "model_distribution": dict(models),
        "decision_distribution": dict(decisions),
        "salvaged_records": salvaged,
        "facts_with_retry_history": len(multi),
        "retry_history_max": max(multi.values(), default=0),
        "valid_qwen_unique": len(last_valid),
        "unexplained_missing": "checked_later_against_universe",
    }
    OutInt.write_text(json.dumps(integrity, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"[integrity] records={total:,} malformed={malformed} "
          f"unique={len(last_any):,} valid_qwen={len(last_valid):,} "
          f"salvaged={salvaged} retry_facts={len(multi)}")

    # ---------- 2. 独立重建 ----------
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    pred_table = policy.get("predicate_policy_table", {})
    safe_rules = policy.get("safe_rules", [])

    def dev_tier(decision: str, predicate: str) -> str:
        if decision == "PARTIALLY_SUPPORTED":
            cell = pred_table.get(predicate)
            if cell and cell.get("partial_map_to") == "strict":
                return "STRICT"
            return "CONTEXTUAL"
        return TIER_OF.get(decision, "CONTEXTUAL")

    align: dict[str, dict] = {}
    for row in csv.DictReader(open(ALIGN, encoding="utf-8-sig")):
        align[row["fact_id"]] = row
    recov: dict[str, str] = {}
    for row in csv.DictReader(open(RECOV, encoding="utf-8-sig")):
        recov[row["fact_id"]] = row.get("recovery_class", "")

    def stratum_of(fid: str) -> str:
        b = align[fid].get("bucket", "")
        if b in ("aligned", "mismatch_with_evidence"):
            return b
        cls = recov.get(fid, "")
        return f"recovery_{cls}" if cls else b

    dev: dict[str, dict] = {}
    for rec in load_jsonl(DEV):
        if rec.get("fact_id"):
            dev[rec["fact_id"]] = rec

    feats: dict[str, dict] = {}
    if safe_rules:   # 本回合 safe_rules 为空；保留通用能力
        for row in csv.DictReader(open(FEATS, encoding="utf-8-sig")):
            feats[row["fact_id"]] = row

    def rule_hit(fid: str) -> bool:
        frow = feats.get(fid, {})
        for rr in safe_rules:
            ok = True
            for key, val in rr.get("requires", {}).items():
                if key == "min_name_len_min":
                    ok &= int(frow.get("min_name_len", 0) or 0) >= val
                elif key == "max_gap":
                    g = int(frow.get("both_gap", -1) or -1)
                    ok &= 0 <= g <= val
                elif key == "stratum_family_in":
                    ok &= frow.get("stratum_family") in val
                else:
                    ok &= parse_bool(frow.get(key, "")) == bool(val)
                if not ok:
                    break
            if ok:
                return True
        return False

    rebuilt: dict[str, dict] = {}
    for fid, a in align.items():
        st = stratum_of(fid)
        localizable = "False" if st == "recovery_D" else "True"
        pred = (a.get("predicate") or "").strip()
        if st == "recovery_D":
            gm, sup, tier = "rule", "NO_EVIDENCE", "UNRESOLVED"
        elif safe_rules and rule_hit(fid):
            gm, sup, tier = "rule", "SAFE_RULE_FULL", "STRICT"
        elif fid in dev and dev[fid].get("decision") in LABELS:
            d = dev[fid]["decision"]
            gm, sup, tier = "llm", d, dev_tier(d, pred)
        elif fid in last_valid:
            d = last_valid[fid]["decision"]
            gm, sup, tier = "llm", d, dev_tier(d, pred)
        else:
            gm, sup, tier = "none", "NOT_EVALUATED", "CONTEXTUAL"
        rebuilt[fid] = {"bucket": a.get("bucket", ""),
                        "recovery_class": recov.get(fid, ""),
                        "evidence_localizable": localizable,
                        "gate_method": gm, "semantic_support": sup,
                        "final_tier": tier}

    with open(OutReb, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fact_id", "bucket", "recovery_class",
                    "evidence_localizable", "gate_method",
                    "semantic_support", "final_tier"])
        for fid in align:
            r = rebuilt[fid]
            w.writerow([fid, r["bucket"], r["recovery_class"],
                        r["evidence_localizable"], r["gate_method"],
                        r["semantic_support"], r["final_tier"]])

    # ---------- 3. 逐行对账 ----------
    official: dict[str, dict] = {}
    for row in csv.DictReader(open(FINAL_CSV, encoding="utf-8-sig")):
        official[row["fact_id"]] = row

    ids_off = set(official)
    ids_reb = set(rebuilt)
    diffs = Counter()
    diff_rows = []
    for fid in ids_off & ids_reb:
        o, r = official[fid], rebuilt[fid]
        for col, rv in (("gate_method", r["gate_method"]),
                        ("semantic_support", r["semantic_support"]),
                        ("final_tier", r["final_tier"]),
                        ("evidence_localizable", r["evidence_localizable"])):
            if o.get(col, "") != rv:
                diffs[col] += 1
                if len(diff_rows) < 50:
                    diff_rows.append({"fact_id": fid, "col": col,
                                      "official": o.get(col, ""), "rebuilt": rv})
    diff_report = {
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "official_rows": len(ids_off),
        "rebuilt_rows": len(ids_reb),
        "id_set_missing_in_rebuilt": sorted(ids_off - ids_reb)[:50],
        "id_set_extra_in_rebuilt": sorted(ids_reb - ids_off)[:50],
        "field_diff_counts": dict(diffs),
        "field_diff_total": sum(diffs.values()),
        "identical": (ids_off == ids_reb and sum(diffs.values()) == 0),
        "diff_samples": diff_rows,
        "tier_counts_official": dict(Counter(
            r.get("final_tier", "") for r in official.values())),
        "tier_counts_rebuilt": dict(Counter(
            r["final_tier"] for r in rebuilt.values())),
    }
    OutDiff.write_text(json.dumps(diff_report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    print(f"[diff] official={len(ids_off):,} rebuilt={len(ids_reb):,} "
          f"field_diffs={sum(diffs.values())} identical={diff_report['identical']}")
    print(f"[diff] tiers official={diff_report['tier_counts_official']}")
    return 0 if diff_report["identical"] else 1


if __name__ == "__main__":
    sys.exit(main())
