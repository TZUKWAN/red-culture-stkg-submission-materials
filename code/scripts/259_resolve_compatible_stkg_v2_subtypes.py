"""Resolve compatible subtype name collisions without another model call."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

try:
    from scripts.stkg_v2_semantics import (
        TYPE_PARENT, semantic_family, strict_v2_entity_type_hint, type_facets,
    )
except ModuleNotFoundError:
    from stkg_v2_semantics import TYPE_PARENT, semantic_family, strict_v2_entity_type_hint, type_facets


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_compatible_subtype_closure.json"
RULE_NAME = "compatible-subtype-name-collision-v1"


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_unique(values_json: str, value: str) -> str:
    values = list(json.loads(values_json))
    if value not in values:
        values.append(value)
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def is_compatible_subtype_candidate(source_type: str, risk_flags_json: str) -> bool:
    return (
        source_type in TYPE_PARENT
        and set(json.loads(risk_flags_json)) == {"same_name_multiple_source_types"}
    )


def ensure_schema(con: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in con.execute("pragma table_info(v2_entities)")}
    if "semantic_family" not in columns:
        con.execute("alter table v2_entities add column semantic_family text")
    if "type_facets_json" not in columns:
        con.execute(
            "alter table v2_entities add column type_facets_json text not null default '[]' "
            "check(json_valid(type_facets_json))"
        )
    con.executescript(
        """
        create table if not exists v2_rule_resolutions(
          resolution_id text primary key,
          task_id text not null,
          unit_id text not null,
          rule_name text not null,
          before_json text not null check(json_valid(before_json)),
          after_json text not null check(json_valid(after_json)),
          created_at text not null
        ) without rowid;
        create index if not exists idx_v2_rule_resolutions_unit
          on v2_rule_resolutions(unit_id,rule_name);
        """
    )


def candidate_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = con.execute(
        "select t.task_id,t.unit_id,t.payload_json,e.canonical_name,e.source_entity_type,"
        "e.semantic_entity_type,e.semantic_status,e.confidence,e.risk_tier,"
        "e.decision_sources_json,e.risk_flags_json "
        "from v2_model_tasks t join v2_entities e on e.entity_id=t.unit_id "
        "where t.task_type='entity_type' and t.status='pending' order by t.task_id"
    ).fetchall()
    return [
        row
        for row in rows
        if is_compatible_subtype_candidate(row["source_entity_type"], row["risk_flags_json"])
    ]


def parent_downgrade_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = con.execute(
        "select e.entity_id,e.canonical_name,e.source_entity_type,e.semantic_entity_type,"
        "e.semantic_status,e.confidence,e.risk_tier,e.decision_sources_json,e.risk_flags_json,"
        "t.task_id from v2_entities e left join v2_model_tasks t on t.unit_id=e.entity_id "
        "and t.task_type='entity_type' where e.semantic_entity_type is not null"
    ).fetchall()
    return [
        row for row in rows
        if TYPE_PARENT.get(str(row["source_entity_type"])) == str(row["semantic_entity_type"])
        and strict_v2_entity_type_hint(
            str(row["canonical_name"]), str(row["source_entity_type"])
        ) != str(row["semantic_entity_type"])
    ]


def populate_type_hierarchy(con: sqlite3.Connection) -> int:
    updates = []
    for entity_id, source_type, semantic_type, current_family, current_facets in con.execute(
        "select entity_id,source_entity_type,semantic_entity_type,semantic_family,type_facets_json "
        "from v2_entities"
    ):
        effective_type = str(semantic_type or source_type)
        expected_family = semantic_family(effective_type)
        expected_facets = json.dumps(type_facets(effective_type), ensure_ascii=False)
        if current_family != expected_family or current_facets != expected_facets:
            updates.append((expected_family, expected_facets, entity_id))
    con.executemany(
        "update v2_entities set semantic_family=?,type_facets_json=? where entity_id=?",
        updates,
    )
    return len(updates)


def run(database: Path, report_path: Path, apply: bool) -> dict:
    database = database.resolve()
    before_hash = sha256_file(database) if apply else None
    con = sqlite3.connect(database, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        if apply:
            ensure_schema(con)
            con.commit()
        rows = candidate_rows(con)
        downgrades = parent_downgrade_rows(con)
        by_type = Counter(str(row["source_entity_type"]) for row in rows)
        downgrade_by_type = Counter(str(row["source_entity_type"]) for row in downgrades)
        pending_before = con.execute(
            "select count(*) from v2_model_tasks where task_type='entity_type' and status='pending'"
        ).fetchone()[0]
        if apply:
            con.commit()
            con.execute("begin immediate")
            hierarchy_rows = populate_type_hierarchy(con)
            now = datetime.now().isoformat(timespec="seconds")
            for row in rows:
                source_type = str(row["source_entity_type"])
                resolution_id = stable_id("V2RULE", RULE_NAME, row["task_id"])
                before = {
                    "semantic_entity_type": row["semantic_entity_type"],
                    "semantic_status": row["semantic_status"],
                    "confidence": row["confidence"],
                    "risk_tier": row["risk_tier"],
                    "task_payload": json.loads(row["payload_json"]),
                }
                after = {
                    "semantic_entity_type": source_type,
                    "semantic_status": "auto_accepted",
                    "confidence": 0.98,
                    "risk_tier": "B",
                    "semantic_family": semantic_family(source_type),
                    "type_facets": type_facets(source_type),
                }
                con.execute(
                    "insert or replace into v2_rule_resolutions values(?,?,?,?,?,?,?)",
                    (
                        resolution_id, row["task_id"], row["unit_id"], RULE_NAME,
                        json.dumps(before, ensure_ascii=False, sort_keys=True),
                        json.dumps(after, ensure_ascii=False, sort_keys=True), now,
                    ),
                )
                con.execute(
                    "update v2_entities set semantic_entity_type=?,semantic_status='auto_accepted',"
                    "confidence=0.98,risk_tier='B',decision_sources_json=?,risk_flags_json=?,"
                    "method_version=?,updated_at=?,semantic_family=?,type_facets_json=? where entity_id=?",
                    (
                        source_type,
                        append_unique(row["decision_sources_json"], RULE_NAME),
                        append_unique(row["risk_flags_json"], "compatible_subtype_name_collision"),
                        RULE_NAME, now, semantic_family(source_type),
                        json.dumps(type_facets(source_type), ensure_ascii=False), row["unit_id"],
                    ),
                )
                con.execute(
                    "update v2_semantic_conflicts set status='resolved',resolution_decision_id=?,"
                    "resolved_at=? where unit_kind='entity' and unit_id=? and status='open'",
                    (resolution_id, now, row["unit_id"]),
                )
                con.execute("delete from v2_model_tasks where task_id=?", (row["task_id"],))
            for row in downgrades:
                source_type = str(row["source_entity_type"])
                task_id = str(row["task_id"] or stable_id("NO_TASK", row["entity_id"]))
                resolution_id = stable_id("V2RULE", RULE_NAME, "restore_subtype", row["entity_id"])
                before = {
                    "semantic_entity_type": row["semantic_entity_type"],
                    "semantic_status": row["semantic_status"],
                    "confidence": row["confidence"],
                    "risk_tier": row["risk_tier"],
                }
                after = {
                    "semantic_entity_type": source_type,
                    "semantic_status": "auto_accepted",
                    "confidence": 0.98,
                    "risk_tier": "B",
                    "semantic_family": semantic_family(source_type),
                    "type_facets": type_facets(source_type),
                }
                con.execute(
                    "insert or replace into v2_rule_resolutions values(?,?,?,?,?,?,?)",
                    (
                        resolution_id, task_id, row["entity_id"], RULE_NAME,
                        json.dumps(before, ensure_ascii=False, sort_keys=True),
                        json.dumps(after, ensure_ascii=False, sort_keys=True), now,
                    ),
                )
                con.execute(
                    "update v2_entities set semantic_entity_type=?,semantic_status='auto_accepted',"
                    "confidence=0.98,risk_tier='B',decision_sources_json=?,risk_flags_json=?,"
                    "method_version=?,updated_at=?,semantic_family=?,type_facets_json=? where entity_id=?",
                    (
                        source_type,
                        append_unique(row["decision_sources_json"], RULE_NAME),
                        append_unique(row["risk_flags_json"], "parent_downgrade_restored"),
                        RULE_NAME, now, semantic_family(source_type),
                        json.dumps(type_facets(source_type), ensure_ascii=False), row["entity_id"],
                    ),
                )
                con.execute(
                    "update v2_semantic_conflicts set status='resolved',resolution_decision_id=?,"
                    "resolved_at=? where unit_kind='entity' and unit_id=?",
                    (resolution_id, now, row["entity_id"]),
                )
            pending_after = con.execute(
                "select count(*) from v2_model_tasks where task_type='entity_type' and status='pending'"
            ).fetchone()[0]
            validation = {
                "missing_semantic_family": con.execute(
                    "select count(*) from v2_entities where semantic_family is null"
                ).fetchone()[0],
                "missing_type_facets": con.execute(
                    "select count(*) from v2_entities where json_array_length(type_facets_json)=0"
                ).fetchone()[0],
                "remaining_compatible_candidates": len(candidate_rows(con)),
                "remaining_parent_downgrades": len(parent_downgrade_rows(con)),
                "rule_resolution_rows": con.execute(
                    "select count(*) from v2_rule_resolutions where rule_name=?", (RULE_NAME,)
                ).fetchone()[0],
                "name_collision_resolution_rows": con.execute(
                    "select count(*) from v2_rule_resolutions where rule_name=? "
                    "and json_type(before_json,'$.task_payload') is not null", (RULE_NAME,)
                ).fetchone()[0],
                "parent_downgrade_resolution_rows": con.execute(
                    "select count(*) from v2_rule_resolutions where rule_name=? "
                    "and json_type(before_json,'$.task_payload') is null", (RULE_NAME,)
                ).fetchone()[0],
            }
            zero_checks = {
                "missing_semantic_family", "missing_type_facets",
                "remaining_compatible_candidates", "remaining_parent_downgrades",
            }
            result = "PASS" if all(validation[key] == 0 for key in zero_checks) else "FAIL"
            if rows or downgrades or hierarchy_rows:
                con.execute(
                    "insert into v2_build_events(phase,action,result,metrics_json,created_at) values(?,?,?,?,?)",
                    (
                        "D", RULE_NAME, result,
                        json.dumps(
                            {"closed": len(rows), "parent_downgrades_restored": len(downgrades),
                             "hierarchy_rows_populated": hierarchy_rows,
                             "validation": validation}, ensure_ascii=False
                        ), now,
                    ),
                )
            con.commit()
        else:
            hierarchy_rows = 0
            pending_after = pending_before - len(rows)
            validation = {"dry_run": True}
            result = "DRY_RUN"
    finally:
        con.close()

    after_hash = sha256_file(database) if apply else None
    report = {
        "result": result,
        "applied": apply,
        "rule": RULE_NAME,
        "database": str(database),
        "database_sha256_before": before_hash,
        "database_sha256_after": after_hash,
        "candidate_count": len(rows),
        "candidate_by_source_type": dict(sorted(by_type.items())),
        "parent_downgrade_count": len(downgrades),
        "parent_downgrade_by_source_type": dict(sorted(downgrade_by_type.items())),
        "entity_type_pending_before": pending_before,
        "entity_type_pending_after": pending_after,
        "hierarchy_rows_populated": hierarchy_rows,
        "validation": validation,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if apply:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DATABASE)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = run(args.db, args.report, args.apply)
    print(json.dumps(report, ensure_ascii=False))
    if report["result"] == "FAIL":
        raise RuntimeError("compatible subtype closure validation failed")


if __name__ == "__main__":
    main()
