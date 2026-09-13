# -*- coding: utf-8 -*-
"""make_universe_ledger.py — PHASE 1.3：全库 universe 对账台账。

从生产库（只读）SQL 统计全部 universe 定义，并与 FINAL_TIERING.csv /
evidence_gate_tier 表交叉核对，产出 release_final/manifests/UNIVERSE_LEDGER.csv
+ .json。每个条目带 universe_name / definition / sql / count / db_sha256。
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "repaired_release" / "red_culture_stkg_final_v3_1.sqlite"
GATE = ROOT / "experiments" / "07_provenance_semantic_gate"
FINAL_CSV = GATE / "FINAL_TIERING.csv"
OUTD = ROOT / "release_final" / "manifests"
CN_TZ = timezone(timedelta(hours=8))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    OUTD.mkdir(parents=True, exist_ok=True)
    db_sha = sha256(DB)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()

    ledger: list[dict] = []

    def add(name: str, definition: str, sql: str) -> int:
        n = cur.execute(sql).fetchone()[0]
        ledger.append({"universe_name": name, "definition": definition,
                       "sql": sql, "count": n, "source_db_sha256": db_sha})
        print(f"  {n:>12,}  {name}")
        return n

    print("[ledger] querying production DB (read-only)...")
    n_entities = add("all_entities", "全部规范化实体（research_entities）",
                     "SELECT COUNT(*) FROM research_entities")
    n_assertions = add("all_assertions", "全库断言宇宙（research_assertions）",
                       "SELECT COUNT(*) FROM research_assertions")
    n_prov = add("all_provenance", "断言溯源行（research_assertion_provenance）",
                 "SELECT COUNT(*) FROM research_assertion_provenance")
    n_gate = add("gate_universe_old_strict",
                 "旧 strict 重分层宇宙（evidence_gate_tier = FINAL_TIERING 覆盖）",
                 "SELECT COUNT(*) FROM evidence_gate_tier")
    n_frames = add("event_frames", "EventFrame 主表",
                   "SELECT COUNT(*) FROM research_event_frames")
    n_states = add("culture_states", "CultureState 主表",
                   "SELECT COUNT(*) FROM research_culture_states")
    n_pv = add("place_versions", "PlaceVersion 主表",
               "SELECT COUNT(*) FROM research_place_versions")
    n_erel = add("event_relations", "事件关系（research_event_relations）",
                 "SELECT COUNT(*) FROM research_event_relations")
    n_prel = add("place_relations", "地点关系（research_place_relations）",
                 "SELECT COUNT(*) FROM research_place_relations")
    n_trel = add("assertion_temporal_pairs", "断言时序关系对",
                 "SELECT COUNT(*) FROM assertion_temporal_relations")

    # 非 strict 宇宙（全库断言 - 旧 strict 重分层宇宙）
    n_outside = add("assertions_outside_gate_universe",
                    "全库断言中不在旧 strict 重分层宇宙的部分（旧 contextual/unresolved 候选宇宙）",
                    f"SELECT COUNT(*) FROM research_assertions WHERE fact_id NOT IN "
                    f"(SELECT fact_id FROM evidence_gate_tier)")

    # research_assertions 自带的 tier/publish 列（自适应探测）
    cols = [r[1] for r in cur.execute("PRAGMA table_info(research_assertions)").fetchall()]
    tier_cols = [c for c in cols if "tier" in c.lower() or "publish" in c.lower()
                 or "state" in c.lower()]
    by_tier_col: dict[str, dict] = {}
    for c in tier_cols:
        rows = cur.execute(
            f"SELECT {c}, COUNT(*) FROM research_assertions GROUP BY {c}").fetchall()
        by_tier_col[c] = {str(k): v for k, v in rows}
        ledger.append({"universe_name": f"assertions_by_{c}",
                       "definition": f"research_assertions.{c} 分组计数",
                       "sql": f"SELECT {c}, COUNT(*) FROM research_assertions GROUP BY {c}",
                       "count": dict(by_tier_col[c]), "source_db_sha256": db_sha})
        print(f"  [col] {c}: {by_tier_col[c]}")

    # evidence_gate_tier 表 vs FINAL_TIERING.csv 逐条核对
    gate_db = {fid: (gm, sup, tier) for fid, gm, sup, tier in
               cur.execute("SELECT fact_id, gate_method, semantic_support, final_tier "
                           "FROM evidence_gate_tier").fetchall()}
    csv_rows = {r["fact_id"]: (r["gate_method"], r["semantic_support"], r["final_tier"])
                for r in csv.DictReader(open(FINAL_CSV, encoding="utf-8-sig"))}
    mismatch = sum(1 for fid in set(gate_db) & set(csv_rows)
                   if gate_db[fid] != csv_rows[fid])
    cross = {
        "db_gate_tier_rows": len(gate_db),
        "csv_rows": len(csv_rows),
        "id_set_diff": len(set(gate_db) ^ set(csv_rows)),
        "field_mismatches": mismatch,
        "identical": (set(gate_db) == set(csv_rows) and mismatch == 0),
    }
    print(f"[cross] evidence_gate_tier vs FINAL_TIERING.csv: {cross}")

    tiers = {"final_strict": "STRICT", "final_contextual": "CONTEXTUAL",
             "final_unresolved": "UNRESOLVED"}
    for name, tier in tiers.items():
        add(name, f"最终三层 {tier}（evidence_gate_tier.final_tier）",
            f"SELECT COUNT(*) FROM evidence_gate_tier WHERE final_tier='{tier}'")
    add("gate_measured_rule", "gate_method=rule 确定性判定",
        "SELECT COUNT(*) FROM evidence_gate_tier WHERE gate_method='rule'")
    add("gate_measured_llm", "gate_method=llm 语义判定",
        "SELECT COUNT(*) FROM evidence_gate_tier WHERE gate_method='llm'")
    add("gate_none_hold", "gate_method=none 持留（目标=0）",
        "SELECT COUNT(*) FROM evidence_gate_tier WHERE gate_method='none'")

    # 视图计数（发布层视图口径）
    for v in ("v_research_strict_assertions", "v_research_contextual_assertions",
              "v_research_unresolved_assertions"):
        add(f"view_{v}", f"发布视图 {v} 行数", f"SELECT COUNT(*) FROM {v}")

    con.close()

    payload = {
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "source_db": str(DB.relative_to(ROOT.parents[1])),
        "source_db_sha256": db_sha,
        "source_db_bytes": DB.stat().st_size,
        "cross_check_gate_tier_vs_csv": cross,
        "entries": ledger,
    }
    OUTD.mkdir(parents=True, exist_ok=True)
    (OUTD / "UNIVERSE_LEDGER.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(OUTD / "UNIVERSE_LEDGER.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["universe_name", "definition", "count", "source_db_sha256", "sql"])
        for e in ledger:
            w.writerow([e["universe_name"], e["definition"], json.dumps(e["count"], ensure_ascii=False)
                        if isinstance(e["count"], dict) else e["count"],
                        e["source_db_sha256"], e["sql"]])
    print(f"[ledger] wrote UNIVERSE_LEDGER.csv/.json ({len(ledger)} entries), "
          f"cross_identical={cross['identical']}")
    return 0 if cross["identical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
