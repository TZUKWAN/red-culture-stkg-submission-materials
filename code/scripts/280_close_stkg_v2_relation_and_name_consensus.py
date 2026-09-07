"""Close high-precision V2 relation-role and exact-name type consensus cases."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

same_name = importlib.import_module("273_resolve_stkg_v2_strict_same_name_consensus")
from stkg_v2_semantics import semantic_family, strict_v2_entity_type_hint, type_facets


DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_relation_name_consensus_closure.json"
RULE_NAME = "stkg-v2-relation-name-consensus-closure-1"

RAW_SPATIAL_OBJECT_PREDICATES = {
    "raw:active_at", "raw:stationed_at", "raw:fought_at", "raw:born_at", "raw:died_at",
    "raw:arrested_at", "raw:imprisoned_at", "raw:发生地", "raw:事件发生地",
    "raw:发生地点", "raw:行动地点", "raw:被俘地点", "raw:转移路径",
    "raw:worked_at", "raw:指导地点",
}
ACTOR_VS_PLACE_PREDICATES = {"stationed_at", "fought_at", "participated_in"}
PERSON_CATEGORY_NAMES = {
    "教师", "学生", "群众", "工人", "农民", "妇女", "干部", "党员", "战士", "士兵",
    "儿童", "青年", "老人", "代表",
}
PROVINCE_ABBREVIATION_CHARS = frozenset(
    "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼"
)


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


def entity_context(con: sqlite3.Connection, entity_id: str) -> list[dict]:
    return [
        {"predicate": str(row[0]), "endpoint_role": str(row[1])}
        for row in con.execute(
            "select predicate,case when subject_id=? then 'subject' else 'object' end "
            "from v2_assertion_scopes where subject_id=? or object_id=?",
            (entity_id, entity_id, entity_id),
        )
    ]


def direct_relation_resolution(
    row: sqlite3.Row,
    contexts: list[dict],
    sibling_source_types: set[str],
) -> tuple[str, str] | None:
    name = str(row["canonical_name"])
    source_type = str(row["source_entity_type"])
    subject_predicates = {
        item["predicate"] for item in contexts if item["endpoint_role"] == "subject"
    }
    object_predicates = {
        item["predicate"] for item in contexts if item["endpoint_role"] == "object"
    }
    raw_spatial_hits = sum(
        1
        for item in contexts
        if item["endpoint_role"] == "object"
        and item["predicate"] in RAW_SPATIAL_OBJECT_PREDICATES
    )
    if name == "群众力量" and source_type == "Organization":
        return "Concept", "exact_abstract_strength_name"
    if source_type == "Person" and "depicts" in object_predicates:
        return "Person", "depicts_object_with_person_source"
    if (
        source_type == "Concept"
        and object_predicates.intersection({"raw:活捉", "raw:逮捕", "raw:处决"})
        and "Person" in sibling_source_types
    ):
        return "Person", "captured_object_with_person_sibling"
    if (
        source_type == "Person"
        and subject_predicates.intersection(ACTOR_VS_PLACE_PREDICATES)
        and "Place" in sibling_source_types
        and strict_v2_entity_type_hint(name, "Place") != "Place"
        and not (
            len(name) == 2 and all(char in PROVINCE_ABBREVIATION_CHARS for char in name)
        )
        and raw_spatial_hits < 2
    ):
        return "Person", "actor_endpoint_distinguishes_place_homonym"
    return None


def is_proper_person_name(name: str) -> bool:
    text = str(name).strip()
    return (
        text not in PERSON_CATEGORY_NAMES
        and bool(re.fullmatch(r"[\u4e00-\u9fff]{2,4}", text))
        and not text.endswith(("群众", "工人", "农民", "学生", "战士", "队员", "代表"))
    )


def candidate_rows(con: sqlite3.Connection) -> list[dict]:
    unresolved = con.execute(
        "select e.*,t.task_id,t.status task_status from v2_entities e "
        "left join v2_model_tasks t on t.unit_kind='entity' and t.unit_id=e.entity_id "
        "and t.task_type='entity_type' where e.semantic_status='model_review' "
        "and e.semantic_entity_type is null order by e.entity_id"
    ).fetchall()
    source_types_by_name: dict[str, set[str]] = defaultdict(set)
    accepted_types_by_name: dict[str, set[str]] = defaultdict(set)
    for item in con.execute(
        "select canonical_name,source_entity_type,semantic_entity_type,semantic_status "
        "from v2_entities"
    ):
        source_types_by_name[str(item[0])].add(str(item[1]))
        if str(item[3]) == "auto_accepted":
            accepted_types_by_name[str(item[0])].add(str(item[2] or item[1]))

    selected: dict[str, dict] = {}
    for row in unresolved:
        contexts = entity_context(con, str(row["entity_id"]))
        resolution = direct_relation_resolution(
            row, contexts, source_types_by_name[str(row["canonical_name"])]
        )
        if resolution:
            final_type, reason = resolution
            selected[str(row["entity_id"])] = {
                "row": row,
                "final_type": final_type,
                "reason": reason,
                "evidence_class": "relation_role",
            }

    for item in same_name.candidate_rows(con):
        row = item["row"]
        entity_id = str(row["entity_id"])
        if str(row["semantic_status"]) != "model_review" or entity_id in selected:
            continue
        selected[entity_id] = {
            "row": row,
            "final_type": item["final_type"],
            "reason": item["reason"],
            "evidence_class": "strict_same_name_consensus",
        }

    projected_accepted = defaultdict(set)
    for name, values in accepted_types_by_name.items():
        projected_accepted[name].update(values)
    for item in selected.values():
        projected_accepted[str(item["row"]["canonical_name"])].add(item["final_type"])
    for row in unresolved:
        entity_id = str(row["entity_id"])
        name = str(row["canonical_name"])
        source_type = str(row["source_entity_type"])
        if entity_id in selected:
            continue
        if (
            source_type == "Person"
            and projected_accepted.get(name) == {"Person"}
            and is_proper_person_name(name)
        ):
            selected[entity_id] = {
                "row": row,
                "final_type": "Person",
                "reason": "proper_person_name_with_unique_same_name_type",
                "evidence_class": "source_type_consensus",
            }
    return [selected[key] for key in sorted(selected)]


def ensure_entity_task(
    con: sqlite3.Connection, row: sqlite3.Row, now: str
) -> str:
    if row["task_id"]:
        return str(row["task_id"])
    task_id = stable_id("V2TASK", row["entity_id"], "entity_type")
    con.execute(
        "insert into v2_model_tasks values(?,?,?,?,?,'completed',0,100,?,?)",
        (
            task_id,
            "entity",
            row["entity_id"],
            "entity_type",
            json.dumps(
                {"entity_id": row["entity_id"], "generated_by": RULE_NAME},
                ensure_ascii=False,
                sort_keys=True,
            ),
            now,
            now,
        ),
    )
    return task_id


def apply_candidates(
    con: sqlite3.Connection, candidates: list[dict], now: str
) -> dict:
    inserted_resolutions = 0
    affected_clusters: set[str] = set()
    for item in candidates:
        row = item["row"]
        final_type = item["final_type"]
        task_id = ensure_entity_task(con, row, now)
        resolution_id = stable_id("V2RULE", row["entity_id"], RULE_NAME)
        cursor = con.execute(
            "insert or ignore into v2_rule_resolutions values(?,?,?,?,?,?,?)",
            (
                resolution_id,
                task_id,
                row["entity_id"],
                RULE_NAME,
                json.dumps(
                    {
                        "source_entity_type": row["source_entity_type"],
                        "semantic_status": row["semantic_status"],
                        "method_version": row["method_version"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "semantic_entity_type": final_type,
                        "semantic_family": semantic_family(final_type),
                        "type_facets": list(type_facets(final_type)),
                        "reason": item["reason"],
                        "evidence_class": item["evidence_class"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                now,
            ),
        )
        inserted_resolutions += int(cursor.rowcount)
        cursor = con.execute(
            "update v2_entities set semantic_entity_type=?,semantic_status='auto_accepted',"
            "confidence=0.99,risk_tier='A',semantic_family=?,type_facets_json=?,"
            "decision_sources_json=?,risk_flags_json=?,method_version=?,updated_at=? "
            "where entity_id=? and semantic_status='model_review' "
            "and semantic_entity_type is null",
            (
                final_type,
                semantic_family(final_type),
                json.dumps(type_facets(final_type), ensure_ascii=False),
                append_json_value(
                    row["decision_sources_json"], f"deterministic_rule:{RULE_NAME}"
                ),
                append_json_value(row["risk_flags_json"], item["reason"]),
                RULE_NAME,
                now,
                row["entity_id"],
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"failed to update {row['entity_id']}")
        con.execute(
            "update v2_model_tasks set status='completed',updated_at=? where task_id=?",
            (now, task_id),
        )
        con.execute(
            "update v2_semantic_conflicts set status='resolved',resolution_decision_id=?,"
            "resolved_at=? where unit_kind='entity' and unit_id=? and status='open' "
            "and conflict_type<>'identity_ambiguity'",
            (resolution_id, now, row["entity_id"]),
        )
        cluster = con.execute(
            "select cluster_id from v2_name_cluster_members where entity_id=?",
            (row["entity_id"],),
        ).fetchone()
        if cluster:
            affected_clusters.add(str(cluster[0]))

    for cluster_id in sorted(affected_clusters):
        unresolved_count = int(
            con.execute(
                "select count(*) from v2_name_cluster_members m join v2_entities e "
                "on e.entity_id=m.entity_id where m.cluster_id=? "
                "and (e.semantic_entity_type is null or e.semantic_status<>'auto_accepted')",
                (cluster_id,),
            ).fetchone()[0]
        )
        con.execute(
            "update v2_name_clusters set status=?,updated_at=? where cluster_id=?",
            ("manual_review" if unresolved_count else "completed", now, cluster_id),
        )
        con.execute(
            "update v2_model_tasks set status='completed',updated_at=? where task_type in "
            "('entity_name_cluster_first_review','entity_name_cluster_second_review') "
            "and json_extract(payload_json,'$.cluster_id')=?",
            (now, cluster_id),
        )
    return {
        "updated_entities": len(candidates),
        "inserted_resolutions": inserted_resolutions,
        "affected_name_clusters": len(affected_clusters),
    }


def public_candidates(candidates: list[dict]) -> list[dict]:
    return [
        {
            "entity_id": item["row"]["entity_id"],
            "canonical_name": item["row"]["canonical_name"],
            "source_type": item["row"]["source_entity_type"],
            "final_type": item["final_type"],
            "reason": item["reason"],
            "evidence_class": item["evidence_class"],
        }
        for item in candidates
    ]


def validate_database(
    con: sqlite3.Connection, expected_ids: set[str]
) -> dict:
    remaining = candidate_rows(con)
    placeholders = ",".join("?" for _ in expected_ids)
    actual_ids = set()
    if expected_ids:
        actual_ids = {
            str(row[0])
            for row in con.execute(
                f"select entity_id from v2_entities where entity_id in ({placeholders}) "
                "and method_version=? and semantic_status='auto_accepted'",
                (*sorted(expected_ids), RULE_NAME),
            )
        }
    quick_check = str(con.execute("pragma quick_check").fetchone()[0])
    foreign_key_errors = len(con.execute("pragma foreign_key_check").fetchall())
    pending_name_reviews = int(
        con.execute(
            "select count(*) from v2_name_clusters where status in "
            "('pending_first','pending_second')"
        ).fetchone()[0]
    )
    passed = (
        quick_check == "ok"
        and foreign_key_errors == 0
        and not remaining
        and actual_ids == expected_ids
        and pending_name_reviews == 0
    )
    return {
        "quick_check": quick_check,
        "foreign_key_errors": foreign_key_errors,
        "remaining_candidates": len(remaining),
        "expected_updated_entities": len(expected_ids),
        "verified_updated_entities": len(actual_ids),
        "pending_name_review_clusters": pending_name_reviews,
        "pass": passed,
    }


def run(database: Path, report: Path, apply: bool) -> dict:
    database = database.resolve()
    report = report.resolve()
    before_hash = sha256(database)
    source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    candidates = candidate_rows(source)
    source.close()
    details = public_candidates(candidates)
    payload = {
        "status": "DRY_RUN" if not apply else "PENDING",
        "database": str(database),
        "rule_name": RULE_NAME,
        "before_sha256": before_hash,
        "candidate_count": len(candidates),
        "by_evidence_class": dict(
            sorted(Counter(item["evidence_class"] for item in candidates).items())
        ),
        "by_final_type": dict(
            sorted(Counter(item["final_type"] for item in candidates).items())
        ),
        "sample": details[:30],
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    if not apply:
        report.write_text(
            json.dumps({**payload, "all_candidates": details}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    temporary = database.with_name(f".{database.name}.relation-consensus.tmp")
    temporary.unlink(missing_ok=True)
    shutil.copy2(database, temporary)
    con = sqlite3.connect(temporary, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        now = datetime.now().isoformat(timespec="seconds")
        con.execute("begin immediate")
        changes = apply_candidates(con, candidates, now)
        con.commit()
        validation = validate_database(
            con, {str(item["row"]["entity_id"]) for item in candidates}
        )
        if not validation["pass"]:
            raise RuntimeError("relation and name consensus closure validation failed")
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
    report.write_text(
        json.dumps({**payload, "all_candidates": details}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
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
