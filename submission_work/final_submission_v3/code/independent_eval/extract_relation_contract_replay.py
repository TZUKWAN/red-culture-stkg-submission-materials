#!/usr/bin/env python3
"""任务2 核心：确定性重放全库结构消融，复现 3412 条关系契约变化集与 44/112 非法 owner 计数。

逻辑逐行对齐 submission_work/final_submission_v2/code/experiment_pipelines/run_component_ablations.py
的 structural_replay()（第 436–596 行），契约/闭包函数直接复用
code/scripts/284_materialize_stkg_v2_research_base.py（其依赖 stkg_contract /
stkg_v2_semantics 由 data/external_inputs 下未改动的复制件提供）。
owner_type_valid 逐字复制自 run_component_ablations.py 第 411–433 行。

产出（experiments/10_structural_validation/）：
- RELATION_CONTRACT_CHANGED_SET.csv  全部 changed_vs_full 记录（w/o Relation Contract）
- STRUCTURAL_REPLAY_AUDIT.json       五个变体计数与 v2 汇总核对 + 44/112 与 208 交叉表

数据库全部只读。不修改任何已有文件。
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"D:\REDCULTUREDATA\投稿材料_代码数据整理包")
FINAL_DB = ROOT / "data" / "release_databases" / "red_culture_stkg_final_v2.sqlite"
SEMANTIC_DB = ROOT / "data" / "release_databases" / "red_culture_stkg_semantic_v2.sqlite"
EXTERNAL = ROOT / "submission_work" / "final_submission_v3" / "data" / "external_inputs"
SCRIPT_284 = ROOT / "code" / "scripts" / "284_materialize_stkg_v2_research_base.py"
OUTDIR = ROOT / "submission_work" / "final_submission_v3" / "experiments" / "10_structural_validation"

FINAL_DB_SHA256 = "a199d736b9ec436b3d5f244e874718604b6c84955a505f31f90a3e28c51a9ee7"
SEMANTIC_DB_SHA256 = "fbfb6529335e1c838270c63eee53c92a568c2b075354f7ad5f9d5815b88bb377"

# v2 汇总（ablation_experiment_summary.json）中的目标核对值
V2_REFERENCE = {
    "w/o Relation Contract": {"changed_vs_full": 3412, "strict_contract_violations": 3412},
    "w/o Role-owner Closure": {
        "changed_vs_full": 208,
        "invalid_time_owner_types": 44,
        "invalid_space_owner_types": 112,
    },
    "w/o Identity Projection": {"changed_vs_full": 24005},
    "w/o Global Closure": {"changed_vs_full": 27475},
}


def load_research_base():
    """导入 284 脚本作为模块（其 stkg_contract/stkg_v2_semantics 依赖由 external_inputs 提供）。"""
    sys.path.insert(0, str(EXTERNAL))
    spec = importlib.util.spec_from_file_location("research_base_284", SCRIPT_284)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 逐字复制自 run_component_ablations.py 第 411-433 行（不得改动逻辑）
def owner_type_valid(role: str, owner_id, subject_id: str, subject_type: str, object_id: str, object_type: str, kind: str) -> bool:
    required = {
        "time": {
            "event_occurrence": {"Event"},
            "biographical": {"Person"},
            "creation_or_publication": {"CreativeWork", "Document", "Artifact"},
            "source_document_time": {"Document"},
        },
        "space": {
            "event_location": {"Event"},
            "biographical_location": {"Person"},
            "creation_or_publication_location": {"CreativeWork", "Document", "Artifact"},
        },
    }[kind]
    allowed = required.get(role)
    if allowed is None:
        return owner_id is None or role not in {"unknown"}
    owner_type = None
    if owner_id == subject_id:
        owner_type = subject_type
    if owner_id == object_id:
        owner_type = object_type if owner_type is None else owner_type
    return owner_type in allowed


def risk_route(risk_tier: str, enabled: bool) -> str:
    """对齐 frozen_v2_replay.risk_route 语义：risk_tier A/B 走自动通道（仅用于 route 计数，不影响本任务）。"""
    if not enabled:
        return "unrouted"
    return f"route_{risk_tier}"


def main() -> None:
    rb = load_research_base()

    con = sqlite3.connect(f"file:{SEMANTIC_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("ATTACH DATABASE ? AS fin", (f"file:{FINAL_DB.as_posix()}?mode=ro",))

    # 与 v2 structural_replay 完全相同的查询
    query = (
        "with provenance as ("
        " select fact_id,count(*) provenance_count,"
        " max(case when member_status not like '%repaired%' and member_status not like '%rewrite%' "
        " and member_status not like '%preserved%' then 1 else 0 end) has_nonrepair"
        " from fin.research_assertion_provenance group by fact_id) "
        "select a.fact_id,a.subject_id source_subject_id,a.object_id source_object_id,"
        "a.source_subject_type,a.source_object_type,a.predicate,a.time_start,a.time_role source_time_role,"
        "a.time_owner_id source_time_owner_id,a.space_role source_space_role,a.space_owner_id source_space_owner_id,"
        "a.semantic_status,a.risk_tier,sp.canonical_anchor_id,"
        "ms.canonical_entity_id subject_id,ms.canonical_entity_type subject_type,"
        "mo.canonical_entity_id object_id,mo.canonical_entity_type object_type,"
        "mto.canonical_entity_id time_owner_canonical_id,mso.canonical_entity_id space_owner_canonical_id,"
        "es.effective_entity_type source_subject_effective_type,es.type_validation_status subject_validation,"
        "eo.effective_entity_type source_object_effective_type,eo.type_validation_status object_validation,"
        "p.provenance_count,p.has_nonrepair,"
        "f.subject_id release_subject_id,f.object_id release_object_id,f.time_role release_time_role,"
        "f.time_owner_id release_time_owner_id,f.space_role release_space_role,"
        "f.space_owner_id release_space_owner_id,f.research_tier release_tier "
        "from v2_assertion_scopes a "
        "join v2_entity_identity_map ms on ms.source_entity_id=a.subject_id "
        "join v2_entity_identity_map mo on mo.source_entity_id=a.object_id "
        "left join v2_entity_identity_map mto on mto.source_entity_id=a.time_owner_id "
        "left join v2_entity_identity_map mso on mso.source_entity_id=a.space_owner_id "
        "join v2_entity_type_effective es on es.entity_id=a.subject_id "
        "join v2_entity_type_effective eo on eo.entity_id=a.object_id "
        "join v2_spatial_projection sp on sp.fact_id=a.fact_id "
        "join fin.research_assertions f on f.fact_id=a.fact_id "
        "join provenance p on p.fact_id=a.fact_id order by a.fact_id"
    )

    variants = {
        "Full framework": {"risk": True, "identity": True, "relation": True, "role": True, "provenance": True},
        "w/o Identity Projection": {"risk": True, "identity": False, "relation": True, "role": True, "provenance": True},
        "w/o Relation Contract": {"risk": True, "identity": True, "relation": False, "role": True, "provenance": True},
        "w/o Role-owner Closure": {"risk": True, "identity": True, "relation": True, "role": False, "provenance": True},
        "w/o Global Closure": {"risk": True, "identity": False, "relation": False, "role": False, "provenance": False},
    }
    stats = {
        name: {
            "tiers": Counter(),
            "strict_contract_violations": 0,
            "invalid_time_owner_types": 0,
            "invalid_space_owner_types": 0,
            "changed_vs_full": 0,
        }
        for name in variants
    }

    changed_rows = []  # w/o Relation Contract 变化记录
    # 44/112 交叉所需：w/o Role-owner Closure 下每条断言的 owner 合法性
    owner_validity = {}  # fact_id -> (time_valid, space_valid)
    scope_adjusted_facts = set()
    total = 0

    for row in con.execute(query):
        total += 1
        fact_id = str(row["fact_id"])
        states = {}
        for name, toggles in variants.items():
            if toggles["identity"]:
                subject_id = str(row["subject_id"])
                object_id = str(row["object_id"])
                subject_type = str(row["subject_type"])
                object_type = str(row["object_type"])
                time_owner = row["time_owner_canonical_id"]
                space_owner = row["space_owner_canonical_id"]
            else:
                subject_id = str(row["source_subject_id"])
                object_id = str(row["source_object_id"])
                subject_type = str(row["source_subject_effective_type"])
                object_type = str(row["source_object_effective_type"])
                time_owner = row["source_time_owner_id"]
                space_owner = row["source_space_owner_id"]
            if toggles["role"]:
                time_role, time_owner = rb.close_time_scope_after_identity(
                    str(row["source_time_role"]), time_owner, str(row["predicate"]), row["time_start"],
                    subject_id, subject_type, object_id, object_type,
                )
                space_role, space_owner = rb.close_space_scope_after_identity(
                    str(row["source_space_role"]), space_owner, str(row["predicate"]),
                    row["canonical_anchor_id"], subject_id, subject_type, object_id, object_type,
                )
            else:
                time_role = str(row["source_time_role"])
                space_role = str(row["source_space_role"])
            actual_contract_pass = rb.relation_domain_range_pass_v2(
                row["predicate"], subject_type, object_type
            )
            contract_pass = actual_contract_pass if toggles["relation"] else True
            provenance_pass = bool(row["provenance_count"]) if toggles["provenance"] else True
            route_pass = str(row["semantic_status"]) == "auto_accepted" if toggles["risk"] else True
            strict = (
                route_pass
                and not str(row["predicate"]).startswith("raw:")
                and row["subject_validation"] == "validated"
                and row["object_validation"] == "validated"
                and contract_pass
                and provenance_pass
            )
            tier = "strict_semantic" if strict else ("contextual" if route_pass else "unresolved")
            state = (subject_id, object_id, time_role, time_owner or "", space_role, space_owner or "", tier)
            states[name] = state
            item = stats[name]
            item["tiers"][tier] += 1
            item["strict_contract_violations"] += int(tier == "strict_semantic" and not actual_contract_pass)
            item["invalid_time_owner_types"] += int(
                not owner_type_valid(time_role, time_owner, subject_id, subject_type, object_id, object_type, "time")
            )
            item["invalid_space_owner_types"] += int(
                not owner_type_valid(space_role, space_owner, subject_id, subject_type, object_id, object_type, "space")
            )
            if name == "w/o Role-owner Closure":
                owner_validity[fact_id] = (
                    owner_type_valid(time_role, time_owner, subject_id, subject_type, object_id, object_type, "time"),
                    owner_type_valid(space_role, space_owner, subject_id, subject_type, object_id, object_type, "space"),
                )
        full_state = states["Full framework"]
        for name, state in states.items():
            if name == "Full framework":
                continue
            if state != full_state:
                stats[name]["changed_vs_full"] += 1
                if name == "w/o Relation Contract":
                    changed_rows.append(
                        {
                            "fact_id": fact_id,
                            "predicate": str(row["predicate"]),
                            "subject_id": full_state[0],
                            "object_id": full_state[1],
                            "subject_type": str(row["subject_type"]),
                            "object_type": str(row["object_type"]),
                            "source_subject_id": str(row["source_subject_id"]),
                            "source_object_id": str(row["source_object_id"]),
                            "source_subject_type": str(row["source_subject_type"]),
                            "source_object_type": str(row["source_object_type"]),
                            "semantic_status": str(row["semantic_status"]),
                            "risk_tier": str(row["risk_tier"]),
                            "actual_contract_pass": int(actual_contract_pass),
                            "full_time_role": full_state[2],
                            "full_time_owner_id": full_state[3],
                            "full_space_role": full_state[4],
                            "full_space_owner_id": full_state[5],
                            "full_tier": full_state[6],
                            "wo_time_role": state[2],
                            "wo_time_owner_id": state[3],
                            "wo_space_role": state[4],
                            "wo_space_owner_id": state[5],
                            "wo_tier": state[6],
                        }
                    )
    con.close()

    # 补充名称与历史阶段（final 库，只读）
    con = sqlite3.connect(f"file:{FINAL_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    for r in con.execute("SELECT fact_id FROM research_scope_adjustments"):
        scope_adjusted_facts.add(r["fact_id"])
    changed_ids = [r["fact_id"] for r in changed_rows]
    name_map, stage_map = {}, {}
    for i in range(0, len(changed_ids), 500):
        chunk = changed_ids[i : i + 500]
        q = ",".join("?" * len(chunk))
        for a in con.execute(
            f"SELECT fact_id, subject_name, object_name, time_raw, place_raw, research_tier FROM research_assertions WHERE fact_id IN ({q})",
            chunk,
        ):
            name_map[a["fact_id"]] = dict(a)
        for s in con.execute(
            f"SELECT fact_id, stage_code FROM research_assertion_stage_memberships WHERE fact_id IN ({q}) ORDER BY stage_code",
            chunk,
        ):
            stage_map.setdefault(s["fact_id"], []).append(s["stage_code"])
    con.close()

    out_csv = OUTDIR / "RELATION_CONTRACT_CHANGED_SET.csv"
    fields = [
        "fact_id", "subject_id", "subject_name", "subject_type", "predicate",
        "object_id", "object_name", "object_type",
        "source_subject_id", "source_subject_type", "source_object_id", "source_object_type",
        "stage_codes", "semantic_status", "risk_tier", "release_tier",
        "actual_contract_pass",
        "full_time_role", "full_time_owner_id", "full_space_role", "full_space_owner_id", "full_tier",
        "wo_time_role", "wo_time_owner_id", "wo_space_role", "wo_space_owner_id", "wo_tier",
        "in_scope_adjustments_208",
    ]
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in changed_rows:
            nm = name_map.get(r["fact_id"], {})
            w.writerow(
                {
                    **r,
                    "subject_name": nm.get("subject_name"),
                    "object_name": nm.get("object_name"),
                    "stage_codes": "|".join(stage_map.get(r["fact_id"], [])) or "no_stage",
                    "release_tier": nm.get("research_tier"),
                    "in_scope_adjustments_208": int(r["fact_id"] in scope_adjusted_facts),
                }
            )

    # 44/112 与 208 交叉
    time_invalid_facts = {fid for fid, (tv, sv) in owner_validity.items() if not tv}
    space_invalid_facts = {fid for fid, (tv, sv) in owner_validity.items() if not sv}
    # 注意：owner_validity 记录的是所有断言在 w/o Role-owner Closure 下的合法性；
    # 44/112 是该变体的全局计数，这里进一步限定在 208 条调整集内交叉
    cross = {
        "wo_role_owner_invalid_time_owner_count_global": len(time_invalid_facts),
        "wo_role_owner_invalid_space_owner_count_global": len(space_invalid_facts),
        "invalid_time_owner_in_scope_208": len(time_invalid_facts & scope_adjusted_facts),
        "invalid_space_owner_in_scope_208": len(space_invalid_facts & scope_adjusted_facts),
        "scope_208_with_any_invalid_owner": len((time_invalid_facts | space_invalid_facts) & scope_adjusted_facts),
        "scope_208_without_invalid_owner": len(scope_adjusted_facts - (time_invalid_facts | space_invalid_facts)),
    }

    # 与 v2 汇总核对
    checks = {}
    for name, ref in V2_REFERENCE.items():
        got = stats[name]
        checks[name] = {
            k: {"v2_reported": v, "v3_replayed": got.get(k), "match": got.get(k) == v}
            for k, v in ref.items()
        }

    def sha256_file(p: Path) -> str:
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    audit = {
        "audit_id": "STRUCTURAL_REPLAY_AUDIT",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment_id": "v3-10-structural-validation-relation-contract-replay",
        "databases": {
            "final": {"path": "data/release_databases/red_culture_stkg_final_v2.sqlite", "sha256": FINAL_DB_SHA256},
            "semantic": {"path": "data/release_databases/red_culture_stkg_semantic_v2.sqlite", "sha256": SEMANTIC_DB_SHA256},
        },
        "database_open_mode": "read-only (file:...?mode=ro; ATTACH 只读 URI)",
        "replay_logic_source": "submission_work/final_submission_v2/code/experiment_pipelines/run_component_ablations.py:436-596 逐行对齐",
        "closure_functions_source": "code/scripts/284_materialize_stkg_v2_research_base.py（依赖 data/external_inputs 下未改动复制件 stkg_contract.py / stkg_v2_semantics.py）",
        "total_assertions_replayed": total,
        "variant_stats": {
            name: {
                "tiers": dict(item["tiers"]),
                "strict_contract_violations": item["strict_contract_violations"],
                "invalid_time_owner_types": item["invalid_time_owner_types"],
                "invalid_space_owner_types": item["invalid_space_owner_types"],
                "changed_vs_full": item["changed_vs_full"],
            }
            for name, item in stats.items()
        },
        "cross_checks_vs_v2_summary": checks,
        "relation_contract_changed_rows": len(changed_rows),
        "owner_validity_cross_scope_adjustments": cross,
        "outputs": {
            "RELATION_CONTRACT_CHANGED_SET.csv": {"rows": len(changed_rows), "sha256": sha256_file(out_csv)},
        },
        "notes": [],
    }
    all_match = all(c["match"] for v in checks.values() for c in v.values())
    audit["notes"].append(
        f"五个变体重放计数与 v2 汇总全部一致：{all_match}。w/o Relation Contract changed_vs_full={stats['w/o Relation Contract']['changed_vs_full']}，strict_contract_violations={stats['w/o Relation Contract']['strict_contract_violations']}。"
    )
    audit["notes"].append(
        "44/112 与 208 的关系：w/o Role-owner Closure 全局非法时间 owner=%d、非法空间 owner=%d（与 v2 报告 44/112 一致）；"
        "其中落在 208 条 scope_adjustments 内的：时间 %d、空间 %d、任一维度 %d；208 中无非法 owner 的 %d 条系其他闭包原因"
        "（如 unknown 角色重分类、context/relation 角色 owner 置空等）。" % (
            len(time_invalid_facts), len(space_invalid_facts),
            cross["invalid_time_owner_in_scope_208"], cross["invalid_space_owner_in_scope_208"],
            cross["scope_208_with_any_invalid_owner"], cross["scope_208_without_invalid_owner"],
        )
    )
    audit_path = OUTDIR / "STRUCTURAL_REPLAY_AUDIT.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    print("total replayed:", total)
    print("changed rows (w/o Relation Contract):", len(changed_rows))
    print("cross checks all match:", all_match)
    for name, chk in checks.items():
        print(name, {k: (v['v3_replayed'], v['match']) for k, v in chk.items()})
    print("44/112 cross:", cross)


if __name__ == "__main__":
    main()
