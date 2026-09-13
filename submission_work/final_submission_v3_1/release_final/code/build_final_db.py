# -*- coding: utf-8 -*-
"""build_final_db.py — PHASE 4：最终数据库物化 + 硬结构审计。

流程：
  0. 预检：源库 SHA256 必须与 00_BASELINE_SNAPSHOT 一致；磁盘空间充足；
  1. 只读源库 → 复制为 release_final/data/red_culture_stkg_final.sqlite；
  2. 单事务刷新【事实级 tier 拷贝】：
     - evidence_gate_tier 全量替换（来自 FINAL_TIERING.csv）
     - research_assertions.research_tier（gate 宇宙 112,158 行）
     - research_event_assertion_links.research_tier（fact 级冗余）
     - research_culture_form_support.research_tier（fact 级冗余）
     - research_event_frames.strict_assertion_count（先验证语义再重算）
  3. 无法由 FINAL_TIERING 安全重导的派生层 → release_derivation_ledger 表
     逐项记录（STALE_AS_OF + 原因 + 刷新路径），不假装重建；
  4. 硬结构审计（目标=0）：tier 枚举、pending、CALL_FAILED/UNPARSEABLE 泄漏、
     孤儿断言、重复 fact_id；
  5. 产物：FINAL_DB_MANIFEST.json（含最终库 SHA256 与全部审计结果）。
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "repaired_release" / "red_culture_stkg_final_v3_1.sqlite"
GATE = ROOT / "experiments" / "07_provenance_semantic_gate"
FINAL_CSV = GATE / "FINAL_TIERING.csv"
CKPT_GZ = GATE / "FINAL_TIERING_CHECKPOINT.jsonl.gz"
SNAP = ROOT / "release_final" / "audit" / "00_BASELINE_SNAPSHOT.json"
DST = ROOT / "release_final" / "data" / "red_culture_stkg_final.sqlite"
OUT = ROOT / "release_final" / "manifests" / "FINAL_DB_MANIFEST.json"
CN_TZ = timezone(timedelta(hours=8))

TIER_MAP = {"STRICT": "strict_semantic", "CONTEXTUAL": "contextual",
            "UNRESOLVED": "unresolved"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    t0 = time.time()
    assert DST.parents[0].exists() or DST.parents[0].mkdir(parents=True, exist_ok=True)
    snap = json.loads(SNAP.read_text(encoding="utf-8"))
    base_sha = next(d["sha256"] for d in snap["candidate_databases"]
                    if d["path"].endswith("red_culture_stkg_final_v3_1.sqlite"))
    src_sha = sha256(SRC)
    if src_sha != base_sha:
        print(f"[abort] 源库哈希漂移：baseline={base_sha[:16]} now={src_sha[:16]}")
        return 2

    if DST.exists():
        DST.unlink()
    print(f"[copy] {SRC.stat().st_size:,} bytes ...")
    shutil.copyfile(SRC, DST)

    rows = list(csv.DictReader(open(FINAL_CSV, encoding="utf-8-sig")))
    assert len(rows) == 112_158, f"FINAL_TIERING rows={len(rows)}"
    csv_sha = sha256(FINAL_CSV)
    now = datetime.now(CN_TZ).isoformat()

    con = sqlite3.connect(DST)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=OFF")

    # ---------- 语义验证：frames.strict_assertion_count 是否 = links strict 计数 ----------
    old_vs_new = cur.execute("""
        SELECT SUM(f.strict_assertion_count),
               (SELECT COUNT(*) FROM research_event_assertion_links l
                 WHERE l.research_tier='strict_semantic')
        FROM research_event_frames f""").fetchone()
    semantics_confirmed = old_vs_new[0] == old_vs_new[1]
    print(f"[verify] frames.strict_assertion_count sum={old_vs_new[0]:,} "
          f"links strict={old_vs_new[1]:,} semantics_confirmed={semantics_confirmed}")

    # ---------- 旧值存档（审计） ----------
    old_gate_dist = dict(cur.execute(
        "SELECT final_tier, COUNT(*) FROM evidence_gate_tier GROUP BY final_tier").fetchall())
    old_rt_dist = dict(cur.execute(
        "SELECT research_tier, COUNT(*) FROM research_assertions GROUP BY research_tier").fetchall())

    cur.execute("BEGIN")
    # 1) evidence_gate_tier 全量替换
    cur.execute("DELETE FROM evidence_gate_tier")
    cur.executemany("INSERT INTO evidence_gate_tier (fact_id, gate_method, "
                    "semantic_support, final_tier) VALUES (?,?,?,?)",
                    [(r["fact_id"], r["gate_method"], r["semantic_support"],
                      r["final_tier"]) for r in rows])

    # 2) 事实级 tier 同步（temp 表 join）
    cur.execute("CREATE TEMP TABLE tier_new (fact_id TEXT PRIMARY KEY, tier TEXT)")
    cur.executemany("INSERT OR IGNORE INTO tier_new VALUES (?,?)",
                    [(r["fact_id"], TIER_MAP[r["final_tier"]]) for r in rows])
    n_assert = cur.execute(
        "UPDATE research_assertions SET research_tier = "
        "(SELECT tier FROM tier_new WHERE tier_new.fact_id = research_assertions.fact_id) "
        "WHERE fact_id IN (SELECT fact_id FROM tier_new)").rowcount
    n_links = cur.execute(
        "UPDATE research_event_assertion_links SET research_tier = "
        "(SELECT tier FROM tier_new WHERE tier_new.fact_id = research_event_assertion_links.fact_id) "
        "WHERE fact_id IN (SELECT fact_id FROM tier_new)").rowcount
    # cfs 表有 CHECK 约束 research_tier ∈ (strict_semantic, contextual)：
    # 语义上未决(unresolved)事实不能充当文化形态支持 → 此类支持行删除并如实计数。
    n_cfs = cur.execute(
        "UPDATE research_culture_form_support SET research_tier = "
        "(SELECT tier FROM tier_new WHERE tier_new.fact_id = research_culture_form_support.fact_id) "
        "WHERE fact_id IN (SELECT fact_id FROM tier_new WHERE tier IN "
        "('strict_semantic','contextual'))").rowcount
    n_cfs_del = cur.execute(
        "DELETE FROM research_culture_form_support WHERE fact_id IN "
        "(SELECT fact_id FROM tier_new WHERE tier='unresolved')").rowcount
    print(f"[sync] assertions={n_assert:,} links={n_links:,} cfs={n_cfs:,} "
          f"cfs_deleted_unresolved={n_cfs_del:,}")

    # 3) frames.strict_assertion_count 重算（语义已验证时）
    if semantics_confirmed:
        cur.execute("""
            UPDATE research_event_frames SET strict_assertion_count =
              (SELECT COUNT(*) FROM research_event_assertion_links l
                WHERE l.event_id = research_event_frames.event_id
                  AND l.research_tier='strict_semantic')""")
    new_gate_dist = dict(cur.execute(
        "SELECT final_tier, COUNT(*) FROM evidence_gate_tier GROUP BY final_tier").fetchall())

    # 3b) UI/API 查询索引（保证重建后哈希与发布库一致）
    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_ent_name ON research_entities(canonical_name)",
        "CREATE INDEX IF NOT EXISTS idx_ent_type ON research_entities(entity_type)",
        "CREATE INDEX IF NOT EXISTS idx_assert_subject ON research_assertions(subject_id)",
        "CREATE INDEX IF NOT EXISTS idx_assert_object ON research_assertions(object_id)",
        "CREATE INDEX IF NOT EXISTS idx_assert_tier ON research_assertions(research_tier)",
        "CREATE INDEX IF NOT EXISTS idx_assert_pred ON research_assertions(predicate)",
        "CREATE INDEX IF NOT EXISTS idx_prov_fact ON research_assertion_provenance(fact_id)",
        "CREATE INDEX IF NOT EXISTS idx_links_event ON research_event_assertion_links(event_id)",
    ]:
        cur.execute(sql)

    # 2b) 判定明细表（UI 证据抽屉自包含：来自 checkpoint 的逐条判定细节）
    cur.execute("""CREATE TABLE IF NOT EXISTS gate_verdict_details (
        fact_id TEXT PRIMARY KEY, decision TEXT, confidence REAL,
        evidence_quote TEXT, explanation TEXT, salvaged INTEGER,
        latency_s REAL, model TEXT, judged_at TEXT)""")
    cur.execute("DELETE FROM gate_verdict_details")
    import gzip
    seen: dict[str, tuple] = {}
    with gzip.open(CKPT_GZ, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            fid = rec.get("fact_id")
            if not fid or rec.get("model") != "qwen3.5-4b":
                continue
            if rec.get("decision") in ("FULLY_SUPPORTED", "PARTIALLY_SUPPORTED",
                                       "UNSUPPORTED", "CONTRADICTED", "INSUFFICIENT"):
                seen[fid] = (fid, rec.get("decision"), rec.get("confidence"),
                             (rec.get("evidence_quote") or "")[:400],
                             (rec.get("explanation") or "")[:400],
                             1 if rec.get("salvaged") else 0,
                             rec.get("latency_s"), rec.get("model"),
                             (rec.get("ts") or "")[:19])
    cur.executemany("INSERT OR REPLACE INTO gate_verdict_details VALUES (?,?,?,?,?,?,?,?,?)",
                    list(seen.values()))
    n_details = len(seen)

    # 3) 陈旧派生台账（不可由 FINAL_TIERING 安全重导者，如实记录）
    stale_items = [
        ("research_culture_states", "observation_tier",
         "CultureState 观察层由 v2 管线按旧 strict 支持度推导；重导需完整 CultureState 管线重跑",
         " rerun: v2 研究管线 build（culture_state 阶段）with 新 tiers"),
        ("research_event_spatiotemporal_cells", "observation_tier",
         "时空单元格观察层同上", "同上"),
        ("research_stage_region_culture_metrics", "observation_tier",
         "阶段-区域文化指标观察层同上", "同上"),
        ("research_event_frames", "frame_status/trusted_time_*",
         "帧状态与可信时间计数部分依赖旧 strict 集", "重跑 EventFrame 聚合"),
        ("research_evolution_transitions 及 support/candidates",
         "全表", "演进推断基于旧 observation 层", "重跑 evolution 管线"),
    ]
    cur.execute("""CREATE TABLE IF NOT EXISTS release_derivation_ledger (
        table_name TEXT, columns TEXT, status TEXT, reason TEXT,
        refresh_path TEXT, recorded_at TEXT)""")
    cur.execute("DELETE FROM release_derivation_ledger")
    cur.executemany("INSERT INTO release_derivation_ledger VALUES (?,?,?,?,?,?)",
                    [(t, c, "STALE_AS_OF_FINAL_TIERING", reason, rp, now)
                     for t, c, reason, rp in stale_items])

    # 构建元信息
    cur.execute("INSERT OR REPLACE INTO research_build_metadata (key, value_json) VALUES (?,?)",
                ("final_tiering_materialization", json.dumps({                    "build_version": "red-culture-stkg-final-2026-09",
                    "materialized_at": now,
                    "tier_source": "FINAL_TIERING.csv",
                    "tier_source_sha256": csv_sha,
                    "final_tiers": new_gate_dist,
                    "stale_derivations": len(stale_items),
                }, ensure_ascii=False)))

    # ---------- 硬结构审计 ----------
    audit: dict[str, object] = {}
    audit["gate_rows"] = cur.execute("SELECT COUNT(*) FROM evidence_gate_tier").fetchone()[0]
    audit["gate_pending_none"] = cur.execute(
        "SELECT COUNT(*) FROM evidence_gate_tier WHERE gate_method='none'").fetchone()[0]
    audit["gate_invalid_tier"] = cur.execute(
        "SELECT COUNT(*) FROM evidence_gate_tier WHERE final_tier NOT IN "
        "('STRICT','CONTEXTUAL','UNRESOLVED')").fetchone()[0]
    audit["gate_failed_support"] = cur.execute(
        "SELECT COUNT(*) FROM evidence_gate_tier WHERE semantic_support IN "
        "('CALL_FAILED','UNPARSEABLE','NOT_EVALUATED') AND final_tier='STRICT'").fetchone()[0]
    audit["assertions_orphan_subject"] = cur.execute(
        "SELECT COUNT(*) FROM research_assertions a WHERE a.subject_id IS NOT NULL AND "
        "NOT EXISTS (SELECT 1 FROM research_entities e WHERE e.entity_id=a.subject_id)").fetchone()[0]
    audit["assertions_orphan_object"] = cur.execute(
        "SELECT COUNT(*) FROM research_assertions a WHERE a.object_id IS NOT NULL AND "
        "NOT EXISTS (SELECT 1 FROM research_entities e WHERE e.entity_id=a.object_id)").fetchone()[0]
    audit["assertions_dup_fact_id"] = cur.execute(
        "SELECT COUNT(*) FROM (SELECT fact_id FROM research_assertions "
        "GROUP BY fact_id HAVING COUNT(*)>1)").fetchone()[0]
    audit["links_orphan_fact"] = cur.execute(
        "SELECT COUNT(*) FROM research_event_assertion_links l WHERE NOT EXISTS "
        "(SELECT 1 FROM research_assertions a WHERE a.fact_id=l.fact_id)").fetchone()[0]
    audit["new_research_tier_dist"] = dict(cur.execute(
        "SELECT research_tier, COUNT(*) FROM research_assertions GROUP BY research_tier").fetchall())
    audit["view_strict_now"] = cur.execute(
        "SELECT COUNT(*) FROM v_research_strict_assertions").fetchone()[0]
    con.commit()

    # salvaged 泄漏检查（checkpoint 视角）
    salv_in_strict = 0
    salv_total = 0
    import gzip
    strict_ids = {r["fact_id"] for r in rows if r["final_tier"] == "STRICT"}
    with gzip.open(CKPT_GZ, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("salvaged") and rec.get("model") == "qwen3.5-4b":
                salv_total += 1
                if rec.get("fact_id") in strict_ids:
                    salv_in_strict += 1
    audit["salvaged_total"] = salv_total
    audit["salvaged_in_strict"] = salv_in_strict

    hard_fail = [k for k in ("gate_pending_none", "gate_invalid_tier",
                             "gate_failed_support", "assertions_dup_fact_id")
                 if audit[k]]
    con.close()

    # quick_check + 终哈希
    chk = sqlite3.connect(DST)
    qc = chk.execute("PRAGMA quick_check").fetchone()[0]
    chk.close()
    dst_sha = sha256(DST)

    manifest = {
        "generated_at": now,
        "source_db": str(SRC.relative_to(ROOT.parents[1])),
        "source_db_sha256": src_sha,
        "final_db": str(DST.relative_to(ROOT.parents[1])),
        "final_db_sha256": dst_sha,
        "final_db_bytes": DST.stat().st_size,
        "quick_check": qc,
        "tier_source": {"file": "FINAL_TIERING.csv", "sha256": csv_sha},
        "refreshed": {
            "evidence_gate_tier": {"rows": len(rows), "old_tiers": old_gate_dist,
                                   "new_tiers": new_gate_dist},
            "research_assertions_research_tier": {"rows": n_assert,
                                                  "old_dist": old_rt_dist},
            "event_assertion_links_rows": n_links,
            "culture_form_support_rows": n_cfs,
            "culture_form_support_deleted_unresolved": n_cfs_del,
            "gate_verdict_details_rows": n_details,
            "event_frames_strict_count_recomputed": semantics_confirmed,
        },
        "stale_derivations_documented": len(stale_items),
        "hard_audit": audit,
        "hard_audit_pass": not hard_fail and qc == "ok",
        "elapsed_s": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[manifest] {OUT.name}: sha={dst_sha[:16]} quick_check={qc} "
          f"hard_pass={manifest['hard_audit_pass']} elapsed={manifest['elapsed_s']}s")
    for k, v in audit.items():
        print(f"  {k}: {v}")
    return 0 if manifest["hard_audit_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
