"""Prepare an isolated Qwen review queue for classifier-proposed type changes."""

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
REPORT = ROOT / "audit_reports" / "stkg_v2_classifier_review_queue.json"
TASK_TYPE = "entity_type_classifier_review"


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def classifier_version(con: sqlite3.Connection) -> str:
    rows = con.execute("select key,value_json from pred.classifier_metadata").fetchall()
    metadata = {str(key): json.loads(value) for key, value in rows}
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        return str(nested.get("model_version") or "unknown")
    return str(metadata.get("model_version") or "unknown")


def prepare(database: Path, predictions: Path, report_path: Path) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    con.execute("attach database ? as pred", (str(predictions.resolve()),))
    try:
        version = classifier_version(con)
        candidates = con.execute(
            "select p.entity_id,p.canonical_name,p.source_type,p.predicted_type,p.confidence,"
            "p.margin,p.lexical_hint,p.schema_top_type,t.payload_json "
            "from pred.entity_predictions p "
            "join v2_model_tasks t on t.unit_kind='entity' and t.unit_id=p.entity_id "
            "and t.task_type='entity_type' "
            "join v2_entities e on e.entity_id=p.entity_id "
            "where p.eligible_rule_candidate=1 and p.source_type<>p.predicted_type "
            "and e.semantic_status in ('model_review','manual_review') "
            "order by p.entity_id"
        ).fetchall()
        inserted = 0
        existing = 0
        by_change = Counter()
        con.execute("begin immediate")
        for row in candidates:
            base_payload = json.loads(row["payload_json"])
            payload = {
                **base_payload,
                "review_mode": "independent_classifier_change_review",
                "classifier_model_version": version,
                "classifier_predicted_type": row["predicted_type"],
                "classifier_confidence": row["confidence"],
                "classifier_margin": row["margin"],
                "lexical_hint": row["lexical_hint"],
                "schema_top_type": row["schema_top_type"],
            }
            task_id = stable_id("V2TASK", "entity", row["entity_id"], TASK_TYPE)
            cursor = con.execute(
                "insert or ignore into v2_model_tasks(task_id,unit_kind,unit_id,task_type,"
                "payload_json,status,attempts,priority,created_at,updated_at) "
                "values(?,?,?,?,?,'pending',0,20,?,?)",
                (
                    task_id, "entity", row["entity_id"], TASK_TYPE,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now, now,
                ),
            )
            inserted += cursor.rowcount
            existing += 1 - cursor.rowcount
            by_change[f"{row['source_type']}->{row['predicted_type']}"] += 1
        con.commit()
        queue_counts = dict(con.execute(
            "select status,count(*) from v2_model_tasks where task_type=? group by status",
            (TASK_TYPE,),
        ).fetchall())
        report = {
            "result": "PASS",
            "task_type": TASK_TYPE,
            "classifier_model_version": version,
            "eligible_change_candidates": len(candidates),
            "inserted": inserted,
            "already_present": existing,
            "queue_counts": queue_counts,
            "by_change": dict(sorted(by_change.items())),
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
    args = parser.parse_args()
    print(json.dumps(prepare(args.db, args.predictions, args.report), ensure_ascii=False))


if __name__ == "__main__":
    main()
