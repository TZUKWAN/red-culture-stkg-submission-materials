"""Close high-precision classifier candidates that retain their existing entity type."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
PREDICTIONS = ROOT / "derived" / "stkg_v2_entity_classifier.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_classifier_same_type_closure.json"
RULE_NAME = "stkg-v2-classifier-same-type-closure-2"


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def append_json_value(raw: str, value: str) -> str:
    values = json.loads(raw or "[]")
    if value not in values:
        values.append(value)
    return json.dumps(values, ensure_ascii=False, sort_keys=True)


def run(database: Path, predictions: Path, report_path: Path, apply: bool) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    con.execute("attach database ? as pred", (str(predictions.resolve()),))
    try:
        candidates = con.execute(
            "select p.*,e.semantic_status,e.semantic_entity_type,e.decision_sources_json,"
            "e.risk_flags_json,t.task_id,t.status task_status "
            "from pred.entity_predictions p join v2_entities e on e.entity_id=p.entity_id "
            "join v2_model_tasks t on t.unit_kind='entity' and t.unit_id=p.entity_id "
            "and t.task_type='entity_type' "
            "where p.eligible_rule_candidate=1 and p.source_type=p.predicted_type "
            "and p.lexical_hint=p.source_type and p.schema_top_type=p.source_type "
            "and e.semantic_status='model_review' and e.semantic_entity_type is null "
            "and t.status='pending' order by p.entity_id"
        ).fetchall()
        by_type = Counter(str(row["source_type"]) for row in candidates)
        by_signal = Counter(
            "lexical+schema" if row["lexical_hint"] and row["schema_top_type"]
            else "lexical" if row["lexical_hint"] else "schema"
            for row in candidates
        )
        inserted_resolutions = 0
        if apply:
            con.execute("begin immediate")
            for row in candidates:
                source = f"local_classifier:{RULE_NAME}"
                decision_sources = append_json_value(row["decision_sources_json"], source)
                con.execute(
                    "update v2_entities set semantic_entity_type=source_entity_type,"
                    "semantic_status='auto_accepted',confidence=?,risk_tier='B',"
                    "decision_sources_json=?,updated_at=? where entity_id=?",
                    (row["confidence"], decision_sources, now, row["entity_id"]),
                )
                con.execute(
                    "update v2_model_tasks set status='completed',updated_at=? where task_id=?",
                    (now, row["task_id"]),
                )
                resolution_id = stable_id("V2RULE", row["entity_id"], RULE_NAME)
                cursor = con.execute(
                    "insert or ignore into v2_rule_resolutions values(?,?,?,?,?,?,?)",
                    (
                        resolution_id, row["task_id"], row["entity_id"], RULE_NAME,
                        json.dumps({
                            "semantic_entity_type": None,
                            "semantic_status": row["semantic_status"],
                        }, ensure_ascii=False, sort_keys=True),
                        json.dumps({
                            "semantic_entity_type": row["source_type"],
                            "semantic_status": "auto_accepted",
                            "confidence": row["confidence"],
                            "lexical_hint": row["lexical_hint"],
                            "schema_top_type": row["schema_top_type"],
                        }, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                inserted_resolutions += cursor.rowcount
                con.execute(
                    "update v2_semantic_conflicts set status='resolved',"
                    "resolution_decision_id=?,resolved_at=? where unit_kind='entity' "
                    "and unit_id=? and status='open' and conflict_type<>'identity_ambiguity'",
                    (resolution_id, now, row["entity_id"]),
                )
            con.commit()
        report = {
            "result": "PASS",
            "rule_name": RULE_NAME,
            "apply": apply,
            "candidate_count": len(candidates),
            "inserted_resolutions": inserted_resolutions,
            "by_type": dict(sorted(by_type.items())),
            "by_signal": dict(sorted(by_signal.items())),
            "sample": [
                {
                    "entity_id": row["entity_id"], "canonical_name": row["canonical_name"],
                    "type": row["source_type"], "confidence": row["confidence"],
                    "lexical_hint": row["lexical_hint"],
                    "schema_top_type": row["schema_top_type"],
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
    parser.add_argument("--predictions", type=Path, default=PREDICTIONS)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.db, args.predictions, args.report, args.apply), ensure_ascii=False))


if __name__ == "__main__":
    main()
