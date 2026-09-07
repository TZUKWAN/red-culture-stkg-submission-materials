"""Materialize strict atomic cultural-site entities in the V2 semantic ledger."""

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
REPORT = ROOT / "audit_reports" / "stkg_v2_cultural_site_materialization.json"
RULE_NAME = "stkg-v2-cultural-site-structural-1"


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def append_json_value(raw: str, value: str) -> str:
    values = json.loads(raw or "[]")
    if value not in values:
        values.append(value)
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def run(database: Path, report_path: Path, apply: bool) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        rows = con.execute(
            "select e.*,t.task_id,t.status task_status from v2_entities e "
            "left join v2_model_tasks t on t.unit_kind='entity' and t.unit_id=e.entity_id "
            "and t.task_type='entity_type' order by e.entity_id"
        ).fetchall()
        candidates = [
            row for row in rows
            if strict_v2_entity_type_hint(
                str(row["canonical_name"]), str(row["source_entity_type"])
            ) == "CulturalSite"
            and str(row["semantic_entity_type"] or row["source_entity_type"]) != "CulturalSite"
        ]
        by_before = Counter(
            str(row["semantic_entity_type"] or row["source_entity_type"])
            for row in candidates
        )
        referenced_ids = {
            row[0]: row[1] for row in con.execute(
                "select canonical_place_id,count(*) from v2_assertion_scopes "
                "where canonical_place_id is not null group by canonical_place_id"
            )
        }
        inserted_resolutions = 0
        if apply:
            con.execute("begin immediate")
            for row in candidates:
                before_type = str(row["semantic_entity_type"] or row["source_entity_type"])
                source = f"deterministic_rule:{RULE_NAME}"
                decision_sources = append_json_value(row["decision_sources_json"], source)
                risk_flags = append_json_value(row["risk_flags_json"], "cultural_site_structural_type")
                con.execute(
                    "update v2_entities set semantic_entity_type='CulturalSite',"
                    "semantic_family=?,type_facets_json=?,semantic_status='auto_accepted',"
                    "confidence=0.99,risk_tier='A',decision_sources_json=?,risk_flags_json=?,"
                    "updated_at=? where entity_id=?",
                    (
                        semantic_family("CulturalSite"),
                        json.dumps(type_facets("CulturalSite"), ensure_ascii=False),
                        decision_sources, risk_flags, now, row["entity_id"],
                    ),
                )
                task_id = row["task_id"] or stable_id("V2RULETASK", row["entity_id"], RULE_NAME)
                if row["task_id"]:
                    con.execute(
                        "update v2_model_tasks set status='completed',updated_at=? where task_id=?",
                        (now, row["task_id"]),
                    )
                resolution_id = stable_id("V2RULE", row["entity_id"], RULE_NAME)
                cursor = con.execute(
                    "insert or ignore into v2_rule_resolutions values(?,?,?,?,?,?,?)",
                    (
                        resolution_id, task_id, row["entity_id"], RULE_NAME,
                        json.dumps({
                            "effective_type": before_type,
                            "semantic_status": row["semantic_status"],
                        }, ensure_ascii=False, sort_keys=True),
                        json.dumps({
                            "semantic_entity_type": "CulturalSite",
                            "semantic_family": "SpatialEntity",
                            "type_facets": list(type_facets("CulturalSite")),
                            "confidence": 0.99,
                        }, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                inserted_resolutions += cursor.rowcount
                con.execute(
                    "update v2_semantic_conflicts set status='resolved',resolution_decision_id=?,"
                    "resolved_at=? where unit_kind='entity' and unit_id=? and status='open' "
                    "and conflict_type<>'identity_ambiguity'",
                    (resolution_id, now, row["entity_id"]),
                )
            con.commit()
        report = {
            "result": "PASS",
            "rule_name": RULE_NAME,
            "apply": apply,
            "candidate_count": len(candidates),
            "inserted_resolutions": inserted_resolutions,
            "canonical_place_referenced_candidates": sum(
                row["entity_id"] in referenced_ids for row in candidates
            ),
            "by_before_type": dict(sorted(by_before.items())),
            "sample": [
                {
                    "entity_id": row["entity_id"], "canonical_name": row["canonical_name"],
                    "source_type": row["source_entity_type"],
                    "before_type": row["semantic_entity_type"] or row["source_entity_type"],
                    "canonical_place_references": referenced_ids.get(row["entity_id"], 0),
                }
                for row in candidates[:50]
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
