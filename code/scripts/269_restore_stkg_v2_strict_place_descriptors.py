"""Restore source-place entities that have unambiguous spatial descriptor names."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from stkg_v2_semantics import semantic_family, strict_v2_entity_type_hint, type_facets


DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_strict_place_descriptor_restoration.json"
RULE_NAME = "stkg-v2-strict-place-descriptor-1"


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def append_json_value(raw: str, value: str) -> str:
    values = json.loads(raw or "[]")
    if value not in values:
        values.append(value)
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def candidate_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    rows = con.execute(
        "select e.*,t.task_id,t.status task_status,count(s.fact_id) canonical_place_references "
        "from v2_entities e join v2_assertion_scopes s on s.canonical_place_id=e.entity_id "
        "left join v2_model_tasks t on t.unit_kind='entity' and t.unit_id=e.entity_id "
        "and t.task_type='entity_type' where e.source_entity_type='Place' "
        "and coalesce(e.semantic_entity_type,e.source_entity_type)<>'Place' "
        "and e.semantic_status='auto_accepted' group by e.entity_id order by e.entity_id"
    ).fetchall()
    return [
        row for row in rows
        if strict_v2_entity_type_hint(
            str(row["canonical_name"]), str(row["source_entity_type"])
        ) == "Place"
    ]


def run(database: Path, report_path: Path, apply: bool) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        rows = candidate_rows(con)
        by_before = Counter(
            str(row["semantic_entity_type"] or row["source_entity_type"]) for row in rows
        )
        inserted_resolutions = 0
        if apply:
            con.execute("begin immediate")
            for row in rows:
                before_type = str(row["semantic_entity_type"] or row["source_entity_type"])
                task_id = str(row["task_id"] or stable_id("V2RULETASK", row["entity_id"], RULE_NAME))
                resolution_id = stable_id("V2RULE", row["entity_id"], RULE_NAME)
                cursor = con.execute(
                    "insert or ignore into v2_rule_resolutions values(?,?,?,?,?,?,?)",
                    (
                        resolution_id, task_id, row["entity_id"], RULE_NAME,
                        json.dumps({
                            "semantic_entity_type": before_type,
                            "semantic_status": row["semantic_status"],
                            "confidence": row["confidence"],
                            "risk_tier": row["risk_tier"],
                        }, ensure_ascii=False, sort_keys=True),
                        json.dumps({
                            "semantic_entity_type": "Place",
                            "semantic_family": "SpatialEntity",
                            "type_facets": list(type_facets("Place")),
                            "confidence": 0.99,
                        }, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                inserted_resolutions += cursor.rowcount
                con.execute(
                    "update v2_entities set semantic_entity_type='Place',semantic_family=?,"
                    "type_facets_json=?,semantic_status='auto_accepted',confidence=0.99,"
                    "risk_tier='A',decision_sources_json=?,risk_flags_json=?,method_version=?,"
                    "updated_at=? where entity_id=?",
                    (
                        semantic_family("Place"),
                        json.dumps(type_facets("Place"), ensure_ascii=False),
                        append_json_value(row["decision_sources_json"], f"deterministic_rule:{RULE_NAME}"),
                        append_json_value(row["risk_flags_json"], "strict_place_descriptor_restored"),
                        RULE_NAME, now, row["entity_id"],
                    ),
                )
                if row["task_id"]:
                    con.execute(
                        "update v2_model_tasks set status='completed',updated_at=? where task_id=?",
                        (now, row["task_id"]),
                    )
                con.execute(
                    "update v2_semantic_conflicts set status='resolved',resolution_decision_id=?,"
                    "resolved_at=? where unit_kind='entity' and unit_id=? and status='open' "
                    "and conflict_type<>'identity_ambiguity'",
                    (resolution_id, now, row["entity_id"]),
                )
            con.commit()
        remaining = len(candidate_rows(con)) if apply else len(rows)
        report = {
            "result": "PASS" if not apply or remaining == 0 else "FAIL",
            "apply": apply,
            "rule_name": RULE_NAME,
            "candidate_count": len(rows),
            "inserted_resolutions": inserted_resolutions,
            "remaining_candidates": remaining,
            "canonical_place_references": sum(int(row["canonical_place_references"]) for row in rows),
            "by_before_type": dict(sorted(by_before.items())),
            "sample": [
                {
                    "entity_id": row["entity_id"],
                    "canonical_name": row["canonical_name"],
                    "before_type": row["semantic_entity_type"],
                    "canonical_place_references": row["canonical_place_references"],
                }
                for row in rows[:100]
            ],
            "quick_check": con.execute("pragma quick_check").fetchone()[0],
            "foreign_key_violations": len(con.execute("pragma foreign_key_check").fetchall()),
            "created_at": now,
        }
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DATABASE)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.db, args.report, args.apply), ensure_ascii=False))


if __name__ == "__main__":
    main()
