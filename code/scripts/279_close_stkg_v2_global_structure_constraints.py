"""Close high-precision structural type contradictions across every V2 entity."""

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
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

structure = importlib.import_module("274_resolve_stkg_v2_strict_structure")
from stkg_v2_semantics import semantic_family, type_facets


DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_global_structure_closure.json"
RULE_NAME = "stkg-v2-global-structure-closure-1"


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


def choose_global_resolution(row: sqlite3.Row) -> tuple[str, str] | None:
    """Return only independent cross-type evidence, never a source-type restoration."""
    source_type = str(row["source_entity_type"])
    current_type = str(row["semantic_entity_type"] or source_type)
    hint = structure.strict_v2_entity_type_hint(str(row["canonical_name"]), source_type)
    resolution = structure.choose_strict_structure_type(
        str(row["canonical_name"]), source_type, hint
    )
    if not resolution:
        return None
    final_type, reason = resolution
    if final_type == current_type or final_type == source_type:
        return None
    if source_type == "Person" or current_type == "Person":
        return None
    text = str(row["canonical_name"]).strip()
    if final_type == "Institution" and (
        "与" in text
        or "及" in text
        or bool(re.search(r"(?:班|工作|斗争).*和", text))
        or (text.startswith("开") and text.endswith("书店"))
    ):
        return None
    if final_type == "Organization" and ("与" in text or "及" in text):
        return None
    if final_type == "Position" and (
        re.search(r"[等及与、/]", text)
        or re.search(r"(?:^任|历任|担任|[第首][一二三四五六七八九十]*任|南下任)", text)
    ):
        return None
    return final_type, reason


def candidate_rows(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "select e.*,t.task_id,t.status task_status from v2_entities e "
        "left join v2_model_tasks t on t.unit_kind='entity' and t.unit_id=e.entity_id "
        "and t.task_type='entity_type' where e.semantic_status in "
        "('auto_accepted','model_review') order by e.entity_id"
    ).fetchall()
    candidates = []
    for row in rows:
        resolution = choose_global_resolution(row)
        if resolution:
            final_type, reason = resolution
            candidates.append({"row": row, "final_type": final_type, "reason": reason})
    return candidates


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
                        "semantic_entity_type": row["semantic_entity_type"],
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
            "where entity_id=?",
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
        unresolved = int(
            con.execute(
                "select count(*) from v2_name_cluster_members m join v2_entities e "
                "on e.entity_id=m.entity_id where m.cluster_id=? "
                "and (e.semantic_entity_type is null or e.semantic_status<>'auto_accepted')",
                (cluster_id,),
            ).fetchone()[0]
        )
        cluster_status = "manual_review" if unresolved else "completed"
        con.execute(
            "update v2_name_clusters set status=?,updated_at=? where cluster_id=?",
            (cluster_status, now, cluster_id),
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


def candidate_payload(candidates: list[dict]) -> list[dict]:
    return [
        {
            "entity_id": item["row"]["entity_id"],
            "canonical_name": item["row"]["canonical_name"],
            "source_type": item["row"]["source_entity_type"],
            "current_type": item["row"]["semantic_entity_type"]
            or item["row"]["source_entity_type"],
            "final_type": item["final_type"],
            "reason": item["reason"],
            "prior_method_version": item["row"]["method_version"],
        }
        for item in candidates
    ]


def validate_database(
    con: sqlite3.Connection, expected_ids: set[str]
) -> dict:
    remaining = candidate_rows(con)
    applied = int(
        con.execute(
            "select count(*) from v2_entities where method_version=?",
            (RULE_NAME,),
        ).fetchone()[0]
    )
    quick_check = str(con.execute("pragma quick_check").fetchone()[0])
    foreign_key_errors = len(con.execute("pragma foreign_key_check").fetchall())
    if expected_ids:
        placeholders = ",".join("?" for _ in expected_ids)
        actual_ids = {
            str(row[0])
            for row in con.execute(
                f"select entity_id from v2_entities where entity_id in ({placeholders}) "
                "and method_version=? and semantic_status='auto_accepted'",
                (*sorted(expected_ids), RULE_NAME),
            )
        }
    else:
        actual_ids = set()
    passed = (
        quick_check == "ok"
        and foreign_key_errors == 0
        and not remaining
        and actual_ids == expected_ids
    )
    return {
        "quick_check": quick_check,
        "foreign_key_errors": foreign_key_errors,
        "remaining_candidates": len(remaining),
        "expected_updated_entities": len(expected_ids),
        "verified_updated_entities": len(actual_ids),
        "total_entities_at_rule_version": applied,
        "pass": passed,
    }


def summarize(candidates: list[dict]) -> dict:
    return {
        "candidate_count": len(candidates),
        "by_final_type": dict(
            sorted(Counter(item["final_type"] for item in candidates).items())
        ),
        "by_reason": dict(
            sorted(Counter(item["reason"] for item in candidates).items())
        ),
        "by_change": dict(
            sorted(
                Counter(
                    f"{item['row']['semantic_entity_type'] or item['row']['source_entity_type']}"
                    f"->{item['final_type']}"
                    for item in candidates
                ).items()
            )
        ),
    }


def run(database: Path, report: Path, apply: bool) -> dict:
    database = database.resolve()
    report = report.resolve()
    before_hash = sha256(database)
    source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    candidates = candidate_rows(source)
    source.close()
    details = candidate_payload(candidates)
    payload = {
        "status": "DRY_RUN" if not apply else "PENDING",
        "database": str(database),
        "rule_name": RULE_NAME,
        "before_sha256": before_hash,
        **summarize(candidates),
        "sample": details[:20],
    }
    full_report = {**payload, "sample": details[:300], "all_candidates": details}
    report.parent.mkdir(parents=True, exist_ok=True)
    if not apply:
        report.write_text(
            json.dumps(full_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return payload

    temporary = database.with_name(f".{database.name}.global-closure.tmp")
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
            raise RuntimeError("global structure closure validation failed")
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
    full_report = {**payload, "sample": details[:300], "all_candidates": details}
    report.write_text(
        json.dumps(full_report, ensure_ascii=False, indent=2), encoding="utf-8"
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
