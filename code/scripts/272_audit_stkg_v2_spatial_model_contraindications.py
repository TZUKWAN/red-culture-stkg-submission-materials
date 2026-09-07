"""Audit and repair spatial entity decisions that violate deterministic structure."""

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

from stkg_v2_semantics import (
    semantic_family, spatial_model_contraindication, strict_v2_entity_type_hint, type_facets,
)


DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_spatial_model_contraindications.json"
RULE_NAME = "stkg-v2-spatial-model-contraindication-1"


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def append_json_value(raw: str, value: str) -> str:
    values = json.loads(raw or "[]")
    if value not in values:
        values.append(value)
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def correction_for(name: str, final_type: str) -> str | None:
    hint = strict_v2_entity_type_hint(name, "Place")
    if hint and hint not in {"Place", "AdministrativeRegion", "CulturalSite"}:
        return hint
    if final_type == "AdministrativeRegion" and spatial_model_contraindication(name, final_type):
        return "Place"
    return None


def candidate_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "select t.task_id second_task_id,t.unit_id,t.payload_json,d.decision_id,"
        "json_extract(d.decision_json,'$.final_type') final_type,e.* "
        "from v2_model_tasks t join v2_model_decisions d on d.task_id=t.task_id "
        "and d.validator_pass=1 and d.decision_id=(select d2.decision_id "
        "from v2_model_decisions d2 where d2.task_id=t.task_id "
        "order by d2.created_at desc,d2.decision_id desc limit 1) "
        "join v2_entities e on e.entity_id=t.unit_id "
        "where t.task_type='entity_type_model_second_review' and t.status='completed' "
        "and json_extract(t.payload_json,'$.prior_prompt_version')='stkg-v2-semantic-adjudication-3' "
        "and e.semantic_status='auto_accepted' "
        "and e.semantic_entity_type=json_extract(d.decision_json,'$.final_type') order by e.entity_id"
    ).fetchall()


def run(database: Path, report_path: Path, apply: bool) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        rows = [
            row for row in candidate_rows(con)
            if spatial_model_contraindication(str(row["canonical_name"]), str(row["final_type"]))
        ]
        actions = []
        for row in rows:
            correction = correction_for(str(row["canonical_name"]), str(row["final_type"]))
            actions.append((row, correction, "rule_correction" if correction else "manual_review"))
        by_action = Counter(action for _, _, action in actions)
        by_reason = Counter(
            spatial_model_contraindication(str(row["canonical_name"]), str(row["final_type"]))
            for row, _, _ in actions
        )
        inserted_resolutions = 0
        if apply:
            con.execute("begin immediate")
            for row, correction, action in actions:
                reason = spatial_model_contraindication(
                    str(row["canonical_name"]), str(row["final_type"])
                )
                payload = json.loads(row["payload_json"])
                original_task_id = str(payload.get("review_mode") and "" or "")
                original_task = con.execute(
                    "select task_id from v2_model_tasks where unit_kind='entity' and unit_id=? "
                    "and task_type='entity_type'", (row["entity_id"],)
                ).fetchone()
                original_task_id = str(original_task[0]) if original_task else ""
                if correction:
                    resolution_id = stable_id("V2RULE", row["entity_id"], RULE_NAME)
                    cursor = con.execute(
                        "insert or ignore into v2_rule_resolutions values(?,?,?,?,?,?,?)",
                        (
                            resolution_id, original_task_id or row["second_task_id"],
                            row["entity_id"], RULE_NAME,
                            json.dumps({
                                "model_final_type": row["final_type"],
                                "second_decision_id": row["decision_id"],
                            }, ensure_ascii=False, sort_keys=True),
                            json.dumps({
                                "semantic_entity_type": correction,
                                "reason": reason,
                                "semantic_family": semantic_family(correction),
                                "type_facets": list(type_facets(correction)),
                            }, ensure_ascii=False, sort_keys=True), now,
                        ),
                    )
                    inserted_resolutions += cursor.rowcount
                    con.execute(
                        "update v2_entities set semantic_entity_type=?,semantic_status='auto_accepted',"
                        "confidence=0.99,risk_tier='A',semantic_family=?,type_facets_json=?,"
                        "decision_sources_json=?,risk_flags_json=?,method_version=?,updated_at=? "
                        "where entity_id=?",
                        (
                            correction, semantic_family(correction),
                            json.dumps(type_facets(correction), ensure_ascii=False),
                            append_json_value(row["decision_sources_json"], f"deterministic_rule:{RULE_NAME}"),
                            append_json_value(row["risk_flags_json"], reason), RULE_NAME, now,
                            row["entity_id"],
                        ),
                    )
                else:
                    source_type = str(row["source_entity_type"])
                    con.execute(
                        "update v2_entities set semantic_entity_type=null,semantic_status='manual_review',"
                        "confidence=0.5,risk_tier='D',semantic_family=?,type_facets_json=?,"
                        "risk_flags_json=?,method_version=?,updated_at=? where entity_id=?",
                        (
                            semantic_family(source_type),
                            json.dumps(type_facets(source_type), ensure_ascii=False),
                            append_json_value(row["risk_flags_json"], reason), RULE_NAME, now,
                            row["entity_id"],
                        ),
                    )
                    con.execute(
                        "update v2_model_tasks set status='manual_review',updated_at=? "
                        "where unit_kind='entity' and unit_id=? and task_type in "
                        "('entity_type','entity_type_model_second_review')",
                        (now, row["entity_id"]),
                    )
                    conflict_id = stable_id("V2CONFLICT", row["entity_id"], RULE_NAME)
                    con.execute(
                        "insert or ignore into v2_semantic_conflicts values(?,?,?,?,?,?,?,?,?,?)",
                        (
                            conflict_id, "entity", row["entity_id"],
                            "spatial_model_contraindication", "error",
                            json.dumps({
                                "model_final_type": row["final_type"], "reason": reason,
                                "second_decision_id": row["decision_id"],
                            }, ensure_ascii=False, sort_keys=True),
                            "open", None, now, None,
                        ),
                    )
            con.commit()
        remaining = [
            row for row in candidate_rows(con)
            if spatial_model_contraindication(str(row["canonical_name"]), str(row["final_type"]))
        ] if apply else rows
        report = {
            "result": "PASS" if not apply or not remaining else "FAIL",
            "apply": apply,
            "rule_name": RULE_NAME,
            "candidate_count": len(rows),
            "inserted_resolutions": inserted_resolutions,
            "remaining_contraindications": len(remaining),
            "by_action": dict(sorted(by_action.items())),
            "by_reason": dict(sorted(by_reason.items())),
            "sample": [
                {
                    "entity_id": row["entity_id"], "canonical_name": row["canonical_name"],
                    "model_final_type": row["final_type"], "correction": correction,
                    "action": action,
                    "reason": spatial_model_contraindication(
                        str(row["canonical_name"]), str(row["final_type"])
                    ),
                }
                for row, correction, action in actions
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
