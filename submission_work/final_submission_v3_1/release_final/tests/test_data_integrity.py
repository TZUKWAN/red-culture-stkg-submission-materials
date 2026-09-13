# -*- coding: utf-8 -*-
"""test_data_integrity.py — PHASE 11：最终库数据完整性测试（无依赖，直接运行）。

运行：python test_data_integrity.py
全部断言通过 → 打印 ALL TESTS PASSED，退出码 0；任一失败 → 退出码 1。
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]           # release_final/
DB = ROOT / "data" / "red_culture_stkg_final.sqlite"
GATE = ROOT.parent / "experiments" / "07_provenance_semantic_gate"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        FAILS.append(name)


def q(cur, sql: str):
    return cur.execute(sql).fetchone()[0]


def main() -> int:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()
    print("[data tests] final db integrity")

    # ---- 行数守恒 ----
    check("universe_total_424150", q(cur, "SELECT COUNT(*) FROM research_assertions") == 424_150)
    check("entities_152979", q(cur, "SELECT COUNT(*) FROM research_entities") == 152_979)
    check("gate_rows_112158", q(cur, "SELECT COUNT(*) FROM evidence_gate_tier") == 112_158)
    check("verdict_details_105081",
          q(cur, "SELECT COUNT(*) FROM gate_verdict_details") == 105_081)

    # ---- tier 枚举与持留 ----
    bad_tier = q(cur, "SELECT COUNT(*) FROM evidence_gate_tier WHERE final_tier NOT IN "
                      "('STRICT','CONTEXTUAL','UNRESOLVED')")
    check("tier_enum_valid", bad_tier == 0)
    check("pending_hold_zero", q(cur, "SELECT COUNT(*) FROM evidence_gate_tier "
                                     "WHERE gate_method='none'") == 0)
    check("failed_not_strict", q(cur, "SELECT COUNT(*) FROM evidence_gate_tier WHERE "
                                      "semantic_support IN ('CALL_FAILED','UNPARSEABLE','NOT_EVALUATED') "
                                      "AND final_tier='STRICT'") == 0)

    # ---- 三层计数与发布数字一致 ----
    tiers = dict(cur.execute("SELECT final_tier, COUNT(*) FROM evidence_gate_tier "
                             "GROUP BY final_tier").fetchall())
    check("strict_31067", tiers.get("STRICT") == 31_067)
    check("contextual_31282", tiers.get("CONTEXTUAL") == 31_282)
    check("unresolved_49809", tiers.get("UNRESOLVED") == 49_809)
    check("full_db_strict_31067",
          q(cur, "SELECT COUNT(*) FROM research_assertions WHERE research_tier='strict_semantic'") == 31_067)

    # ---- 引用完整性 ----
    check("no_orphan_subject", q(cur, "SELECT COUNT(*) FROM research_assertions a WHERE "
                                      "a.subject_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "
                                      "research_entities e WHERE e.entity_id=a.subject_id)") == 0)
    check("no_orphan_object", q(cur, "SELECT COUNT(*) FROM research_assertions a WHERE "
                                     "a.object_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "
                                     "research_entities e WHERE e.entity_id=a.object_id)") == 0)
    check("no_dup_fact_id", q(cur, "SELECT COUNT(*) FROM (SELECT fact_id FROM "
                                   "research_assertions GROUP BY fact_id HAVING COUNT(*)>1)") == 0)
    check("verdict_details_linked",
          q(cur, "SELECT COUNT(*) FROM gate_verdict_details v WHERE NOT EXISTS "
                 "(SELECT 1 FROM evidence_gate_tier g WHERE g.fact_id=v.fact_id)") == 0)

    # ---- 派生台账存在（诚实声明） ----
    check("derivation_ledger_present",
          q(cur, "SELECT COUNT(*) FROM release_derivation_ledger") >= 5)

    # ---- CSV ↔ DB 一致（抽样 2,000 行）----
    csv_rows = list(csv.DictReader(open(GATE / "FINAL_TIERING.csv", encoding="utf-8-sig")))
    sample = csv_rows[::56]
    mismatch = 0
    for r in sample:
        row = cur.execute("SELECT gate_method, semantic_support, final_tier FROM "
                          "evidence_gate_tier WHERE fact_id=?", (r["fact_id"],)).fetchone()
        if not row or tuple(row) != (r["gate_method"], r["semantic_support"], r["final_tier"]):
            mismatch += 1
    check("csv_db_sample_consistent", mismatch == 0, f"n={len(sample)}")

    # ---- FINAL_NUMBERS 哈希闭环 ----
    nums = json.loads((ROOT / "manifests" / "FINAL_NUMBERS.json")
                      .read_text(encoding="utf-8"))
    h = hashlib.sha256()
    with open(DB, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    check("numbers_hash_closed", nums["final_db_sha256"] == h.hexdigest())

    con.close()
    print(f"[data tests] {'ALL TESTS PASSED' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
