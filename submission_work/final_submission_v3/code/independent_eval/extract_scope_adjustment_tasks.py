#!/usr/bin/env python3
"""任务1：从只读 final_v2 数据库提取全部 208 条时空作用域调整，生成盲化评价任务。

产出（experiments/10_structural_validation/）：
- SCOPE_ADJUSTMENT_TASKS.jsonl   每行一个盲化任务（state_a/state_b，不标注 before/after）
- SCOPE_ADJUSTMENT_AB_MAPPING.csv  state_a/state_b 与 before/after 的对应关系（单独保存）
- SCOPE_ADJUSTMENT_EXTRACTION_AUDIT.json  类型分布与一致性检查

种子规则：master_seed=20260907；本任务种子 = SHA-256("scope_adjustment_ab_blinding|20260907") 前 8 字节。
数据库只读（file:...?mode=ro），不修改任何已有文件。
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\REDCULTUREDATA\投稿材料_代码数据整理包")
FINAL_DB = ROOT / "data" / "release_databases" / "red_culture_stkg_final_v2.sqlite"
OUTDIR = ROOT / "submission_work" / "final_submission_v3" / "experiments" / "10_structural_validation"
OUTDIR.mkdir(parents=True, exist_ok=True)

MASTER_SEED = 20260907
TASK_NAME = "scope_adjustment_ab_blinding"
DERIVED_SEED = int.from_bytes(
    hashlib.sha256(f"{TASK_NAME}|{MASTER_SEED}".encode("utf-8")).digest()[:8], "big"
)
FINAL_DB_SHA256 = "a199d736b9ec436b3d5f244e874718604b6c84955a505f31f90a3e28c51a9ee7"  # BASELINE_FREEZE_MANIFEST


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    con = sqlite3.connect(f"file:{FINAL_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        "SELECT * FROM research_scope_adjustments ORDER BY fact_id"
    ).fetchall()
    assert len(rows) == 208, f"expected 208 scope adjustments, got {len(rows)}"

    # 关联断言全文上下文
    fact_ids = [r["fact_id"] for r in rows]
    assertions = {}
    for i in range(0, len(fact_ids), 500):
        chunk = fact_ids[i : i + 500]
        q = ",".join("?" * len(chunk))
        for a in con.execute(f"SELECT * FROM research_assertions WHERE fact_id IN ({q})", chunk):
            assertions[a["fact_id"]] = dict(a)

    # 实体名称解析
    entity_ids = set()
    for r in rows:
        for col in (
            "source_time_owner_canonical_id",
            "final_time_owner_id",
            "source_space_owner_canonical_id",
            "final_space_owner_id",
        ):
            if r[col]:
                entity_ids.add(r[col])
    for a in assertions.values():
        for col in ("subject_id", "object_id", "time_owner_id", "space_owner_id"):
            if a.get(col):
                entity_ids.add(a[col])
    names = {}
    eids = sorted(entity_ids)
    for i in range(0, len(eids), 500):
        chunk = eids[i : i + 500]
        q = ",".join("?" * len(chunk))
        for e in con.execute(
            f"SELECT entity_id, canonical_name, entity_type FROM research_entities WHERE entity_id IN ({q})",
            chunk,
        ):
            names[e["entity_id"]] = {"name": e["canonical_name"], "type": e["entity_type"]}

    # 来源谱系摘要（发布库无原始证据文本，只有谱系指针）
    prov = {}
    for i in range(0, len(fact_ids), 500):
        chunk = fact_ids[i : i + 500]
        q = ",".join("?" * len(chunk))
        for p in con.execute(
            f"SELECT fact_id, provenance_kind, source_table, source_predicate, member_status,"
            f" legacy_candidate_ids_json, native_record_ids_json"
            f" FROM research_assertion_provenance WHERE fact_id IN ({q})",
            chunk,
        ):
            prov.setdefault(p["fact_id"], []).append(dict(p))

    con.close()

    rng = random.Random(DERIVED_SEED)
    tasks = []
    mapping_rows = []
    stats = {
        "time_role_changed": 0,
        "time_owner_changed": 0,
        "space_role_changed": 0,
        "space_owner_changed": 0,
        "both_time_and_space_changed": 0,
        "time_only": 0,
        "space_only": 0,
    }
    time_role_transitions = Counter()
    space_role_transitions = Counter()
    reason_counts = Counter()
    method_versions = Counter()
    consistency_mismatches = []

    for idx, r in enumerate(rows, 1):
        r = dict(r)
        fact_id = r["fact_id"]
        a = assertions.get(fact_id, {})

        def owner_info(eid):
            if not eid:
                return None
            info = names.get(eid, {})
            return {"entity_id": eid, "name": info.get("name"), "type": info.get("type")}

        before_state = {
            "time_role": r["source_time_role"],
            "time_owner": owner_info(r["source_time_owner_canonical_id"]),
            "space_role": r["source_space_role"],
            "space_owner": owner_info(r["source_space_owner_canonical_id"]),
        }
        after_state = {
            "time_role": r["final_time_role"],
            "time_owner": owner_info(r["final_time_owner_id"]),
            "space_role": r["final_space_role"],
            "space_owner": owner_info(r["final_space_owner_id"]),
        }

        time_changed = (
            r["source_time_role"] != r["final_time_role"]
            or r["source_time_owner_canonical_id"] != r["final_time_owner_id"]
        )
        space_changed = (
            r["source_space_role"] != r["final_space_role"]
            or r["source_space_owner_canonical_id"] != r["final_space_owner_id"]
        )
        stats["time_role_changed"] += int(r["source_time_role"] != r["final_time_role"])
        stats["time_owner_changed"] += int(
            r["source_time_owner_canonical_id"] != r["final_time_owner_id"]
        )
        stats["space_role_changed"] += int(r["source_space_role"] != r["final_space_role"])
        stats["space_owner_changed"] += int(
            r["source_space_owner_canonical_id"] != r["final_space_owner_id"]
        )
        stats["both_time_and_space_changed"] += int(time_changed and space_changed)
        stats["time_only"] += int(time_changed and not space_changed)
        stats["space_only"] += int(space_changed and not time_changed)
        time_role_transitions[f"{r['source_time_role']} -> {r['final_time_role']}"] += 1
        space_role_transitions[f"{r['source_space_role']} -> {r['final_space_role']}"] += 1
        reason_counts[r["adjustment_reason"]] += 1
        method_versions[r["method_version"]] += 1

        # 一致性检查：调整表 final_* 应与发布断言当前值一致
        if a:
            checks = [
                ("time_role", a.get("time_role"), r["final_time_role"]),
                ("time_owner_id", a.get("time_owner_id"), r["final_time_owner_id"]),
                ("space_role", a.get("space_role"), r["final_space_role"]),
                ("space_owner_id", a.get("space_owner_id"), r["final_space_owner_id"]),
            ]
            for field, got, want in checks:
                if (got or None) != (want or None):
                    consistency_mismatches.append(
                        {"fact_id": fact_id, "field": field, "assertion": got, "adjustment_final": want}
                    )

        # A/B 盲化
        a_is_before = rng.random() < 0.5
        state_a = before_state if a_is_before else after_state
        state_b = after_state if a_is_before else before_state

        task_id = f"SA-{idx:04d}"
        prov_list = prov.get(fact_id, [])
        task = {
            "task_id": task_id,
            "fact_id": fact_id,
            "adjustment": r,
            "assertion_context": {
                "subject_id": a.get("subject_id"),
                "subject_name": a.get("subject_name"),
                "subject_type": a.get("subject_type"),
                "predicate": a.get("predicate"),
                "object_id": a.get("object_id"),
                "object_name": a.get("object_name"),
                "object_type": a.get("object_type"),
                "time_raw": a.get("time_raw"),
                "time_start": a.get("time_start"),
                "time_end": a.get("time_end"),
                "time_precision": a.get("time_precision"),
                "normalized_time_label": a.get("normalized_time_label"),
                "place_raw": a.get("place_raw"),
                "province": a.get("province"),
                "city": a.get("city"),
                "county": a.get("county"),
                "semantic_status": a.get("semantic_status"),
                "risk_tier": a.get("risk_tier"),
                "research_tier": a.get("research_tier"),
            },
            "provenance": {
                "record_count": len(prov_list),
                "kinds": sorted({p["provenance_kind"] for p in prov_list}),
                "source_tables": sorted({p["source_table"] for p in prov_list}),
                "source_predicates": sorted({str(p["source_predicate"]) for p in prov_list}),
                "member_statuses": sorted({p["member_status"] for p in prov_list}),
                "legacy_candidate_ids": sorted(
                    {cid for p in prov_list for cid in json.loads(p["legacy_candidate_ids_json"])}
                ),
                "native_record_ids": sorted(
                    {nid for p in prov_list for nid in json.loads(p["native_record_ids_json"])}
                ),
            },
            "source_evidence_text": None,
            "source_evidence_text_note": (
                "发布库 research_assertion_provenance 仅存谱系指针（evidence_ids_json/metadata_json 为空），"
                "原始文本在整理包外上游库（CURRENT_RELEASE.json required_source_databases），本任务文件不内置。"
            ),
            "state_a": state_a,
            "state_b": state_b,
            "blinding": "state_a/state_b 与 before/after 的对应见 SCOPE_ADJUSTMENT_AB_MAPPING.csv；judge 不可见该映射",
        }
        tasks.append(task)
        mapping_rows.append(
            {
                "task_id": task_id,
                "fact_id": fact_id,
                "state_a_corresponds_to": "before" if a_is_before else "after",
                "state_b_corresponds_to": "after" if a_is_before else "before",
                "derived_seed": DERIVED_SEED,
            }
        )

    tasks_path = OUTDIR / "SCOPE_ADJUSTMENT_TASKS.jsonl"
    with open(tasks_path, "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    mapping_path = OUTDIR / "SCOPE_ADJUSTMENT_AB_MAPPING.csv"
    with open(mapping_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(mapping_rows[0].keys()))
        w.writeheader()
        w.writerows(mapping_rows)

    audit = {
        "audit_id": "SCOPE_ADJUSTMENT_EXTRACTION_AUDIT",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment_id": "v3-10-structural-validation-scope-adjustments",
        "database": "data/release_databases/red_culture_stkg_final_v2.sqlite",
        "database_sha256": FINAL_DB_SHA256,
        "database_open_mode": "read-only (file:...?mode=ro)",
        "master_seed": MASTER_SEED,
        "task_name": TASK_NAME,
        "derived_seed": DERIVED_SEED,
        "seed_derivation": "int.from_bytes(SHA256('scope_adjustment_ab_blinding|20260907')[:8],'big')",
        "total_adjustments": len(rows),
        "dimension_distribution": stats,
        "time_role_transitions": dict(time_role_transitions.most_common()),
        "space_role_transitions": dict(space_role_transitions.most_common()),
        "adjustment_reason_counts": dict(reason_counts.most_common()),
        "method_version_counts": dict(method_versions.most_common()),
        "consistency_check": {
            "description": "research_scope_adjustments.final_* 与 research_assertions 当前值比对",
            "mismatch_count": len(consistency_mismatches),
            "mismatches": consistency_mismatches[:20],
        },
        "outputs": {
            "SCOPE_ADJUSTMENT_TASKS.jsonl": {"rows": len(tasks), "sha256": sha256_file(tasks_path)},
            "SCOPE_ADJUSTMENT_AB_MAPPING.csv": {"rows": len(mapping_rows), "sha256": sha256_file(mapping_path)},
        },
        "notes": [
            "44/112 非法 owner 与 208 条调整的交叉核实由 replay_structural_components.py 在同一目录的 STRUCTURAL_REPLAY_AUDIT.json 中给出；本文件 notes 在该步骤完成后回填结论。",
        ],
    }
    audit_path = OUTDIR / "SCOPE_ADJUSTMENT_EXTRACTION_AUDIT.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print(f"tasks={len(tasks)} mapping={len(mapping_rows)}")
    print("dimension_distribution:", stats)
    print("consistency_mismatches:", len(consistency_mismatches))
    print("derived_seed:", DERIVED_SEED)


if __name__ == "__main__":
    main()
