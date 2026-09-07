"""Reopen name-cluster decisions that violate the current semantic guardrails."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from stkg_v2_semantics import (
    entity_context_contraindication,
    entity_model_contraindication,
    semantic_family,
    type_facets,
)


DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_name_cluster_guard_remediation.json"
METHOD_VERSION = "stkg-v2-name-cluster-guard-remediation-1"
FIRST_TASK = "entity_name_cluster_first_review"
SECOND_TASK = "entity_name_cluster_second_review"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def active_guard_violations(con: sqlite3.Connection) -> list[dict]:
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select e.entity_id,e.canonical_name,e.source_entity_type,e.semantic_entity_type,"
        "e.semantic_status,e.method_version,m.cluster_id "
        "from v2_entities e join v2_name_cluster_members m on m.entity_id=e.entity_id "
        "where e.method_version like 'stkg-v2-name-cluster-adjudication-%' "
        "and e.semantic_status='auto_accepted' and e.semantic_entity_type is not null "
        "order by m.cluster_id,e.entity_id"
    ).fetchall()
    cluster_types: dict[str, set[str]] = {}
    violations = []
    for row in rows:
        cluster_id = str(row["cluster_id"])
        if cluster_id not in cluster_types:
            cluster_types[cluster_id] = {
                str(item[0])
                for item in con.execute(
                    "select source_entity_type from v2_name_cluster_members where cluster_id=?",
                    (cluster_id,),
                )
            }
        reason = entity_model_contraindication(
            str(row["canonical_name"]),
            str(row["source_entity_type"]),
            str(row["semantic_entity_type"]),
            cluster_types[cluster_id],
        )
        if not reason and con.execute(
            "select 1 from sqlite_master where type='table' and name='v2_assertion_scopes'"
        ).fetchone():
            context_rows = con.execute(
                "select predicate,case when subject_id=? then 'subject' else 'object' end endpoint_role "
                "from v2_assertion_scopes where subject_id=? or object_id=?",
                (row["entity_id"], row["entity_id"], row["entity_id"]),
            ).fetchall()
            reason = entity_context_contraindication(
                str(row["canonical_name"]),
                str(row["source_entity_type"]),
                str(row["semantic_entity_type"]),
                [
                    {"predicate": item[0], "endpoint_role": item[1]}
                    for item in context_rows
                ],
            )
        if reason:
            violations.append({
                "entity_id": str(row["entity_id"]),
                "cluster_id": cluster_id,
                "canonical_name": str(row["canonical_name"]),
                "source_entity_type": str(row["source_entity_type"]),
                "applied_entity_type": str(row["semantic_entity_type"]),
                "guard_reason": reason,
                "prior_method_version": str(row["method_version"]),
            })
    return violations


def reopen_conflicts(con: sqlite3.Connection, entity_id: str, cluster_id: str) -> int:
    cursor = con.execute(
        "update v2_semantic_conflicts set status='open',resolution_decision_id=null,resolved_at=null "
        "where unit_kind='entity' and unit_id=? and status='resolved' "
        "and conflict_type<>'identity_ambiguity' and resolution_decision_id in ("
        "select d.decision_id from v2_model_decisions d join v2_model_tasks t on t.task_id=d.task_id "
        "where t.task_type=? and json_extract(t.payload_json,'$.cluster_id')=?"
        ")",
        (entity_id, SECOND_TASK, cluster_id),
    )
    return int(cursor.rowcount)


def apply_remediation(con: sqlite3.Connection, violations: list[dict], now: str) -> dict:
    reopened_conflicts = 0
    reopened_entity_tasks = 0
    clusters = sorted({item["cluster_id"] for item in violations})
    for item in violations:
        source_type = item["source_entity_type"]
        cursor = con.execute(
            "update v2_entities set semantic_entity_type=null,semantic_status='model_review',"
            "confidence=null,risk_tier='C',semantic_family=?,type_facets_json=?,"
            "decision_sources_json=json_insert(decision_sources_json,'$[#]',?),"
            "risk_flags_json=json_insert(risk_flags_json,'$[#]',?),method_version=?,updated_at=? "
            "where entity_id=? and semantic_status='auto_accepted' "
            "and method_version like 'stkg-v2-name-cluster-adjudication-%'",
            (
                semantic_family(source_type),
                json.dumps(type_facets(source_type), ensure_ascii=False),
                METHOD_VERSION,
                item["guard_reason"],
                METHOD_VERSION,
                now,
                item["entity_id"],
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"failed to reopen guarded entity {item['entity_id']}")
        cursor = con.execute(
            "update v2_model_tasks set status='pending',updated_at=? "
            "where unit_kind='entity' and unit_id=? and task_type='entity_type' "
            "and status='completed'",
            (now, item["entity_id"]),
        )
        reopened_entity_tasks += int(cursor.rowcount)
        reopened_conflicts += reopen_conflicts(
            con, item["entity_id"], item["cluster_id"]
        )
    for cluster_id in clusters:
        con.execute(
            "update v2_model_tasks set status='pending',updated_at=? "
            "where task_type in (?,?) and json_extract(payload_json,'$.cluster_id')=?",
            (now, FIRST_TASK, SECOND_TASK, cluster_id),
        )
        con.execute(
            "update v2_name_clusters set status='pending_first',updated_at=? where cluster_id=?",
            (now, cluster_id),
        )
    return {
        "reopened_entities": len(violations),
        "reopened_clusters": len(clusters),
        "reopened_entity_tasks": reopened_entity_tasks,
        "reopened_conflicts": reopened_conflicts,
    }


def validate_database(con: sqlite3.Connection, violations: list[dict]) -> dict:
    quick_check = str(con.execute("pragma quick_check").fetchone()[0])
    foreign_key_errors = len(con.execute("pragma foreign_key_check").fetchall())
    ids = [item["entity_id"] for item in violations]
    reopened_entities = 0
    if ids:
        placeholders = ",".join("?" for _ in ids)
        reopened_entities = int(con.execute(
            f"select count(*) from v2_entities where entity_id in ({placeholders}) "
            "and semantic_status='model_review' and semantic_entity_type is null "
            "and method_version=?",
            (*ids, METHOD_VERSION),
        ).fetchone()[0])
    remaining_guard_violations = active_guard_violations(con)
    return {
        "quick_check": quick_check,
        "foreign_key_errors": foreign_key_errors,
        "expected_reopened_entities": len(ids),
        "verified_reopened_entities": reopened_entities,
        "remaining_active_guard_violations": remaining_guard_violations,
        "pass": (
            quick_check == "ok"
            and foreign_key_errors == 0
            and reopened_entities == len(ids)
            and not remaining_guard_violations
        ),
    }


def run(database: Path, report: Path, apply: bool) -> dict:
    database = database.resolve()
    report = report.resolve()
    before_hash = sha256(database)
    source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    violations = active_guard_violations(source)
    source.close()
    payload = {
        "status": "DRY_RUN" if not apply else "PENDING",
        "database": str(database),
        "method_version": METHOD_VERSION,
        "before_sha256": before_hash,
        "detected_violations": violations,
        "detected_count": len(violations),
    }
    if not apply:
        return payload

    temporary = database.with_name(f".{database.name}.guard-remediation.tmp")
    temporary.unlink(missing_ok=True)
    shutil.copy2(database, temporary)
    con = sqlite3.connect(temporary, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        now = datetime.now().isoformat(timespec="seconds")
        con.execute("begin immediate")
        changes = apply_remediation(con, violations, now)
        con.commit()
        validation = validate_database(con, violations)
        if not validation["pass"]:
            raise RuntimeError("guard remediation validation failed")
    except Exception:
        con.rollback()
        con.close()
        temporary.unlink(missing_ok=True)
        raise
    con.close()
    if sha256(database) != before_hash:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("V2 source changed before atomic replacement")
    os.replace(temporary, database)
    payload.update({
        "status": "PASS",
        "changes": changes,
        "validation": validation,
        "after_sha256": sha256(database),
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    })
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DATABASE)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.db, args.report, args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
