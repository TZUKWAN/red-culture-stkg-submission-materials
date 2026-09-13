# -*- coding: utf-8 -*-
"""generate_final_numbers.py — PHASE 5：论文核心数字唯一权威源。

全部 metric 从 FINAL DB（SQL）/ 已冻结审计产物自动计算，每条带
universe / definition / source / sql_or_script / status / db_sha256。
输出：release_final/manifests/FINAL_NUMBERS.json + .csv
后续：独立 Judge 精度由 score_quality_audit.py 完成后合并进来。
"""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "release_final" / "data" / "red_culture_stkg_final.sqlite"
GATE = ROOT / "experiments" / "07_provenance_semantic_gate"
LEDGER = ROOT / "release_final" / "manifests" / "UNIVERSE_LEDGER.json"
SUMMARY = GATE / "FINAL_TIERING_SUMMARY.json"
INTEG = ROOT / "release_final" / "audit" / "CHECKPOINT_INTEGRITY_REPORT.json"
DIFF = ROOT / "release_final" / "audit" / "REBUILD_DIFF.json"
DBMAN = ROOT / "release_final" / "manifests" / "FINAL_DB_MANIFEST.json"
OUTD = ROOT / "release_final" / "manifests"
CN_TZ = timezone(timedelta(hours=8))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    db_sha = sha256(DB)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cur = con.cursor()
    metrics: list[dict] = []

    def add(metric: str, value, unit: str, universe: str, definition: str,
            source: str, sql_or_script: str, status: str = "MEASURED") -> None:
        metrics.append({"metric": metric, "value": value, "unit": unit,
                        "universe": universe, "definition": definition,
                        "source": source, "sql_or_script": sql_or_script,
                        "status": status, "db_sha256": db_sha})

    def q1(sql: str) -> int:
        return cur.execute(sql).fetchone()[0]

    # ---- 宇宙 ----
    add("total_entities", q1("SELECT COUNT(*) FROM research_entities"), "count",
        "final_db", "规范化实体总数", "FINAL DB", "SELECT COUNT(*) FROM research_entities")
    add("total_assertions", q1("SELECT COUNT(*) FROM research_assertions"), "count",
        "final_db", "全库断言总数（完整 424k 宇宙）", "FINAL DB",
        "SELECT COUNT(*) FROM research_assertions")
    add("gate_universe_old_strict",
        q1("SELECT COUNT(*) FROM evidence_gate_tier"), "count",
        "old_strict_universe",
        "旧 strict 重分层宇宙（本轮证据语义门的定义域，112,158，不是全库）",
        "FINAL DB", "SELECT COUNT(*) FROM evidence_gate_tier")
    add("assertions_outside_gate_universe",
        q1("SELECT COUNT(*) FROM research_assertions WHERE fact_id NOT IN "
           "(SELECT fact_id FROM evidence_gate_tier)"), "count",
        "final_db", "全库中断言不在证据门宇宙的部分（保留历史口径）", "FINAL DB",
        "SELECT COUNT(*) FROM research_assertions WHERE fact_id NOT IN "
        "(SELECT fact_id FROM evidence_gate_tier)")

    # ---- 证据门三层（gate 宇宙）----
    for tier in ("STRICT", "CONTEXTUAL", "UNRESOLVED"):
        add(f"gate_{tier.lower()}",
            q1(f"SELECT COUNT(*) FROM evidence_gate_tier WHERE final_tier='{tier}'"),
            "count", "old_strict_universe",
            f"证据门最终 {tier}（MEASURED，gate 宇宙 112,158 内）", "FINAL DB",
            f"SELECT COUNT(*) FROM evidence_gate_tier WHERE final_tier='{tier}'")

    # ---- 全库三层（424,150 = gate 宇宙 + 历史口径宇宙）----
    for t in ("strict_semantic", "contextual", "unresolved"):
        add(f"full_db_{t}", q1(f"SELECT COUNT(*) FROM research_assertions WHERE research_tier='{t}'"),
            "count", "final_db", f"全库 research_tier={t}（论文全库口径）", "FINAL DB",
            f"SELECT COUNT(*) FROM research_assertions WHERE research_tier='{t}'")

    # ---- STKG 结构对象 ----
    add("event_frames", q1("SELECT COUNT(*) FROM research_event_frames"), "count",
        "final_db", "EventFrame 总数", "FINAL DB",
        "SELECT COUNT(*) FROM research_event_frames")
    add("culture_states", q1("SELECT COUNT(*) FROM research_culture_states"), "count",
        "final_db", "CultureState 总数", "FINAL DB",
        "SELECT COUNT(*) FROM research_culture_states")
    add("place_versions", q1("SELECT COUNT(*) FROM research_place_versions"), "count",
        "final_db", "PlaceVersion 总数", "FINAL DB",
        "SELECT COUNT(*) FROM research_place_versions")
    add("event_relations", q1("SELECT COUNT(*) FROM research_event_relations"), "count",
        "final_db", "事件关系数", "FINAL DB",
        "SELECT COUNT(*) FROM research_event_relations")
    add("place_relations", q1("SELECT COUNT(*) FROM research_place_relations"), "count",
        "final_db", "地点关系数", "FINAL DB",
        "SELECT COUNT(*) FROM research_place_relations")
    add("assertion_temporal_pairs",
        q1("SELECT COUNT(*) FROM assertion_temporal_relations"), "count",
        "final_db", "断言时序关系对", "FINAL DB",
        "SELECT COUNT(*) FROM assertion_temporal_relations")
    add("event_frame_strict_backbone",
        q1("SELECT COALESCE(SUM(strict_assertion_count),0) FROM research_event_frames"),
        "count", "final_db",
        "EventFrame 关联 strict 断言骨架（实测 tiers 刷新后）", "FINAL DB",
        "SELECT SUM(strict_assertion_count) FROM research_event_frames")

    # ---- 三概念分离 A/B/C（来自冻结 summary）----
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    tc = s.get("three_concepts", s.get("abc_separation", {}))
    for key, name in (("A_lineage_completeness", "A_lineage"),
                      ("B_evidence_localization_rate", "B_localization"),
                      ("C_semantic_support_rate_measured", "C_semantic_support")):
        cell = tc.get(key)
        if cell:
            add(name, cell.get("rate"), "rate", "old_strict_universe",
                f"{key}（三概念分离，全库确定数）", "FINAL_TIERING_SUMMARY.json",
                f"FINAL_TIERING_SUMMARY.json.three_concepts.{key}.rate", "DERIVED")

    # ---- 质量与可复现性 ----
    integ = json.loads(INTEG.read_text(encoding="utf-8"))
    add("checkpoint_records", integ["records_total"], "count", "audit",
        "最终判定 checkpoint 记录数（gzip 归档）", "CHECKPOINT_INTEGRITY_REPORT.json",
        "stream parse FINAL_TIERING_CHECKPOINT.jsonl.gz", "MEASURED")
    add("checkpoint_malformed_json", integ["malformed_json"], "count", "audit",
        "checkpoint 畸形 JSON 行数（目标 0）", "CHECKPOINT_INTEGRITY_REPORT.json",
        "stream parse", "MEASURED")
    add("checkpoint_salvaged_records", integ["salvaged_records"], "count", "audit",
        "兜底解析救回的判定数（逐条带 salvaged 审计标志）",
        "CHECKPOINT_INTEGRITY_REPORT.json", "stream parse", "MEASURED")
    diff = json.loads(DIFF.read_text(encoding="utf-8"))
    add("replay_field_diffs", diff["field_diff_total"], "count", "audit",
        "Level-A 离线重放与 FINAL_TIERING.csv 字段差异数（目标 0）", "REBUILD_DIFF.json",
        "release_final/audit/replay_final_tiering.py", "MEASURED")
    dbman = json.loads(DBMAN.read_text(encoding="utf-8"))
    add("final_db_hard_violations",
        sum(1 for k in ("gate_pending_none", "gate_invalid_tier", "gate_failed_support",
                        "assertions_orphan_subject", "assertions_orphan_object",
                        "assertions_dup_fact_id", "links_orphan_fact")
            if dbman["hard_audit"].get(k)),
        "count", "audit", "最终库硬结构违规数（目标 0）", "FINAL_DB_MANIFEST.json",
        "release_final/code/build_final_db.py", "MEASURED")
    add("final_db_sha256", dbman["final_db_sha256"], "hash", "audit",
        "最终数据库 SHA256", "FINAL_DB_MANIFEST.json", "sha256sum", "DERIVED")
    add("production_gate_model", "qwen3.5-4b", "model_id", "audit",
        "最终全量证据门生产模型（reasoning=off，温度 0）",
        "FINAL_TIERING_POLICY.json / checkpoint", "-", "DERIVED")
    con.close()

    OUTD.mkdir(parents=True, exist_ok=True)
    (OUTD / "FINAL_NUMBERS.json").write_text(
        json.dumps({"generated_at": datetime.now(CN_TZ).isoformat(),
                    "final_db_sha256": db_sha, "metrics": metrics},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    with open(OUTD / "FINAL_NUMBERS.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["metric", "value", "unit", "universe", "definition",
                    "source", "sql_or_script", "status", "db_sha256"])
        for m in metrics:
            w.writerow([m["metric"], m["value"], m["unit"], m["universe"],
                        m["definition"], m["source"], m["sql_or_script"],
                        m["status"], m["db_sha256"]])
    print(f"[numbers] wrote {len(metrics)} metrics -> FINAL_NUMBERS.json/.csv")
    for m in metrics:
        print(f"  {m['metric']:36s} = {m['value']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
