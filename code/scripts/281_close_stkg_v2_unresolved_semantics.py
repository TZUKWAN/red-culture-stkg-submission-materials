"""Close unresolved V2 type and identity tasks without inventing semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_unresolved_semantic_closure.json"
METHOD_VERSION = "stkg-v2-unresolved-semantic-closure-1"


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def append_json_value(raw: str, value: str) -> str:
    values = json.loads(raw or "[]")
    if value not in values:
        values.append(value)
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def aliases_digest(con: sqlite3.Connection) -> str:
    digest = hashlib.sha256()
    for row in con.execute(
        "select entity_id,aliases_json from v2_entities order by entity_id"
    ):
        digest.update(str(row[0]).encode("utf-8"))
        digest.update(b"\x1f")
        digest.update(str(row[1]).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    return bool(
        con.execute(
            "select 1 from sqlite_master where type='table' and name=?",
            (table_name,),
        ).fetchone()
    )


def latest_second_reviews(con: sqlite3.Connection) -> dict[str, dict]:
    reviews: dict[str, dict] = {}
    rows = con.execute(
        "select json_extract(t.payload_json,'$.cluster_id') cluster_id,"
        "d.decision_id,d.decision_json,d.created_at "
        "from v2_model_tasks t join v2_model_decisions d on d.task_id=t.task_id "
        "where t.task_type='entity_name_cluster_second_review' "
        "and d.validator_pass=1 order by d.created_at,d.decision_id"
    )
    for row in rows:
        payload = json.loads(row["decision_json"])
        if row["cluster_id"]:
            reviews[str(row["cluster_id"])] = {
                "decision_id": str(row["decision_id"]),
                "payload": payload,
            }
    return reviews


def unresolved_type_candidates(con: sqlite3.Connection) -> list[dict]:
    reviews = latest_second_reviews(con)
    already_closed = set()
    if table_exists(con, "v2_entity_type_closures"):
        already_closed = {
            str(row[0]) for row in con.execute("select entity_id from v2_entity_type_closures")
        }
    rows = con.execute(
        "select e.*,t.task_id,t.status task_status,m.cluster_id "
        "from v2_entities e join v2_model_tasks t on t.unit_kind='entity' "
        "and t.unit_id=e.entity_id and t.task_type='entity_type' "
        "left join v2_name_cluster_members m on m.entity_id=e.entity_id "
        "where e.semantic_entity_type is null and e.semantic_status in "
        "('model_review','manual_review') and t.status in ('pending','manual_review') "
        "order by e.entity_id"
    ).fetchall()
    candidates = []
    for row in rows:
        if str(row["entity_id"]) in already_closed:
            continue
        cluster_review = reviews.get(str(row["cluster_id"] or ""), {})
        payload = cluster_review.get("payload", {})
        unresolved = payload.get("double_review_unresolved") or {}
        reason = str(unresolved.get(str(row["entity_id"])) or "prior_manual_review")
        assignment = next(
            (
                item
                for item in payload.get("assignments", [])
                if str(item.get("entity_id")) == str(row["entity_id"])
            ),
            None,
        )
        candidates.append(
            {
                "row": row,
                "reason": reason,
                "second_review_decision_id": cluster_review.get("decision_id"),
                "review_summary": {
                    "cluster_id": row["cluster_id"],
                    "unresolved_reason": reason,
                    "second_review_assignment": assignment,
                },
            }
        )
    return candidates


def identity_candidates(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "select c.conflict_id,c.unit_id entity_id,c.details_json,e.canonical_name,"
        "e.source_entity_type,e.semantic_entity_type,e.aliases_json "
        "from v2_semantic_conflicts c join v2_entities e on e.entity_id=c.unit_id "
        "where c.unit_kind='entity' and c.conflict_type='identity_ambiguity' "
        "and c.status='open' order by c.conflict_id"
    ).fetchall()


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        create table if not exists v2_entity_type_closures(
          entity_id text primary key references v2_entities(entity_id),
          source_entity_type text not null,
          fallback_entity_type text not null,
          closure_status text not null check(closure_status='accepted_unknown'),
          unresolved_reason text not null,
          second_review_decision_id text,
          review_summary_json text not null check(json_valid(review_summary_json)),
          method_version text not null,
          closed_at text not null
        );
        create table if not exists v2_identity_resolutions(
          conflict_id text primary key references v2_semantic_conflicts(conflict_id),
          entity_id text not null references v2_entities(entity_id),
          resolution_type text not null check(resolution_type='context_scoped_reference'),
          scope_policy text not null,
          global_merge_target text,
          rationale_json text not null check(json_valid(rationale_json)),
          method_version text not null,
          closed_at text not null,
          check(global_merge_target is null)
        );
        drop view if exists v2_entity_type_effective;
        create view v2_entity_type_effective as
        select e.entity_id,e.canonical_name,e.source_entity_type,e.semantic_entity_type,
               coalesce(e.semantic_entity_type,c.fallback_entity_type,e.source_entity_type)
                 as effective_entity_type,
               case when e.semantic_entity_type is not null then 'validated'
                    when c.closure_status='accepted_unknown' then 'fallback_unresolved'
                    else 'unclosed' end as type_validation_status,
               e.semantic_status,e.confidence,e.risk_tier,e.aliases_json,
               c.unresolved_reason,c.method_version as closure_method_version
        from v2_entities e left join v2_entity_type_closures c
          on c.entity_id=e.entity_id;
        """
    )


def apply_closure(
    con: sqlite3.Connection,
    type_candidates: list[dict],
    identities: list[sqlite3.Row],
    now: str,
) -> dict:
    ensure_schema(con)
    closed_type_conflicts = 0
    for item in type_candidates:
        row = item["row"]
        entity_id = str(row["entity_id"])
        closure_id = stable_id("V2CLOSURE", entity_id, METHOD_VERSION)
        con.execute(
            "insert into v2_entity_type_closures values(?,?,?,?,?,?,?,?,?)",
            (
                entity_id,
                row["source_entity_type"],
                row["source_entity_type"],
                "accepted_unknown",
                item["reason"],
                item["second_review_decision_id"],
                json.dumps(item["review_summary"], ensure_ascii=False, sort_keys=True),
                METHOD_VERSION,
                now,
            ),
        )
        con.execute(
            "update v2_entities set semantic_status='manual_review',confidence=null,"
            "risk_tier='D',decision_sources_json=?,risk_flags_json=?,method_version=?,"
            "updated_at=? where entity_id=? and semantic_entity_type is null",
            (
                append_json_value(
                    row["decision_sources_json"],
                    f"accepted_unknown:{METHOD_VERSION}",
                ),
                append_json_value(
                    row["risk_flags_json"],
                    f"unresolved_entity_type:{item['reason']}",
                ),
                METHOD_VERSION,
                now,
                entity_id,
            ),
        )
        con.execute(
            "update v2_model_tasks set status='manual_review',updated_at=? "
            "where task_id=? and status in ('pending','manual_review')",
            (now, row["task_id"]),
        )
        cursor = con.execute(
            "update v2_semantic_conflicts set status='accepted_unknown',"
            "resolution_decision_id=?,resolved_at=? where unit_kind='entity' "
            "and unit_id=? and status='open' and conflict_type<>'identity_ambiguity'",
            (closure_id, now, entity_id),
        )
        closed_type_conflicts += int(cursor.rowcount)

    for row in identities:
        details = json.loads(row["details_json"] or "{}")
        resolution_id = stable_id(
            "V2IDENTITY", row["conflict_id"], METHOD_VERSION
        )
        con.execute(
            "insert into v2_identity_resolutions values(?,?,?,?,?,?,?,?)",
            (
                row["conflict_id"],
                row["entity_id"],
                "context_scoped_reference",
                "keep_each_assertion_reference_scoped;never_global_merge_by_generic_label",
                None,
                json.dumps(
                    {
                        "canonical_name": row["canonical_name"],
                        "reason": details.get("reason", "generic_identity_ambiguity"),
                        "required_context": details.get("required_context", []),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                METHOD_VERSION,
                now,
            ),
        )
        con.execute(
            "update v2_semantic_conflicts set status='accepted_unknown',"
            "resolution_decision_id=?,resolved_at=? where conflict_id=? and status='open'",
            (resolution_id, now, row["conflict_id"]),
        )
    return {
        "closed_entity_types": len(type_candidates),
        "closed_type_conflicts": closed_type_conflicts,
        "context_scoped_identities": len(identities),
    }


def validate_database(
    con: sqlite3.Connection,
    expected_type_ids: set[str],
    expected_identity_ids: set[str],
    expected_alias_digest: str,
    expected_entity_count: int,
) -> dict:
    quick_check = str(con.execute("pragma quick_check").fetchone()[0])
    foreign_key_errors = len(con.execute("pragma foreign_key_check").fetchall())
    pending_type_tasks = int(
        con.execute(
            "select count(*) from v2_model_tasks where task_type='entity_type' "
            "and status='pending'"
        ).fetchone()[0]
    )
    unclosed_entities = int(
        con.execute(
            "select count(*) from v2_entities where semantic_entity_type is null "
            "and semantic_status='model_review'"
        ).fetchone()[0]
    )
    open_identity_conflicts = int(
        con.execute(
            "select count(*) from v2_semantic_conflicts "
            "where conflict_type='identity_ambiguity' and status='open'"
        ).fetchone()[0]
    )
    actual_type_ids = {
        str(row[0])
        for row in con.execute(
            "select entity_id from v2_entity_type_closures where method_version=?",
            (METHOD_VERSION,),
        )
    }
    actual_identity_ids = {
        str(row[0])
        for row in con.execute(
            "select conflict_id from v2_identity_resolutions where method_version=?",
            (METHOD_VERSION,),
        )
    }
    fallback_mismatches = int(
        con.execute(
            "select count(*) from v2_entity_type_closures "
            "where fallback_entity_type<>source_entity_type"
        ).fetchone()[0]
    )
    forbidden_merges = int(
        con.execute(
            "select count(*) from v2_identity_resolutions "
            "where global_merge_target is not null"
        ).fetchone()[0]
    )
    entity_count = int(con.execute("select count(*) from v2_entities").fetchone()[0])
    actual_alias_digest = aliases_digest(con)
    passed = all(
        (
            quick_check == "ok",
            foreign_key_errors == 0,
            pending_type_tasks == 0,
            unclosed_entities == 0,
            open_identity_conflicts == 0,
            actual_type_ids == expected_type_ids,
            actual_identity_ids == expected_identity_ids,
            fallback_mismatches == 0,
            forbidden_merges == 0,
            entity_count == expected_entity_count,
            actual_alias_digest == expected_alias_digest,
        )
    )
    return {
        "quick_check": quick_check,
        "foreign_key_errors": foreign_key_errors,
        "pending_entity_type_tasks": pending_type_tasks,
        "unclosed_model_review_entities": unclosed_entities,
        "open_identity_conflicts": open_identity_conflicts,
        "expected_type_closures": len(expected_type_ids),
        "verified_type_closures": len(actual_type_ids),
        "expected_identity_resolutions": len(expected_identity_ids),
        "verified_identity_resolutions": len(actual_identity_ids),
        "fallback_type_mismatches": fallback_mismatches,
        "forbidden_global_identity_merges": forbidden_merges,
        "entity_count_preserved": entity_count == expected_entity_count,
        "aliases_preserved": actual_alias_digest == expected_alias_digest,
        "pass": passed,
    }


def run(database: Path, report: Path, apply: bool) -> dict:
    database = database.resolve()
    report = report.resolve()
    before_hash = sha256(database)
    source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    type_candidates = unresolved_type_candidates(source)
    identities = identity_candidates(source)
    alias_hash = aliases_digest(source)
    entity_count = int(source.execute("select count(*) from v2_entities").fetchone()[0])
    source.close()
    payload = {
        "status": "DRY_RUN" if not apply else "PENDING",
        "database": str(database),
        "method_version": METHOD_VERSION,
        "before_sha256": before_hash,
        "unresolved_entity_type_count": len(type_candidates),
        "by_source_type": dict(
            sorted(
                Counter(
                    str(item["row"]["source_entity_type"])
                    for item in type_candidates
                ).items()
            )
        ),
        "by_unresolved_reason": dict(
            sorted(Counter(item["reason"] for item in type_candidates).items())
        ),
        "identity_ambiguity_count": len(identities),
        "identity_policy": "context_scoped_reference;no_global_merge",
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    if not apply:
        report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    temporary = database.with_name(f".{database.name}.unresolved-closure.tmp")
    temporary.unlink(missing_ok=True)
    shutil.copy2(database, temporary)
    con = sqlite3.connect(temporary, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        now = datetime.now().isoformat(timespec="seconds")
        con.execute("begin immediate")
        changes = apply_closure(con, type_candidates, identities, now)
        con.commit()
        validation = validate_database(
            con,
            {str(item["row"]["entity_id"]) for item in type_candidates},
            {str(row["conflict_id"]) for row in identities},
            alias_hash,
            entity_count,
        )
        if not validation["pass"]:
            raise RuntimeError("unresolved semantic closure validation failed")
    except Exception:
        con.rollback()
        con.close()
        temporary.unlink(missing_ok=True)
        raise
    con.close()
    if sha256(database) != before_hash:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("V2 database changed before atomic replacement")
    os.replace(temporary, database)
    payload.update(
        {
            "status": "PASS",
            "changes": changes,
            "validation": validation,
            "after_sha256": sha256(database),
            "completed_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
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
