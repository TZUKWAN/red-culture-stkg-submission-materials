"""Prepare independent second reviews for earlier single-model entity decisions."""

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
REPORT = ROOT / "audit_reports" / "stkg_v2_model_second_review_queue.json"
TASK_TYPE = "entity_type_model_second_review"


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def prepare(database: Path, report_path: Path) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        candidates = con.execute(
            "with ranked as ("
            " select d.*,row_number() over(partition by d.task_id order by d.created_at desc,d.decision_id desc) rn"
            " from v2_model_decisions d where d.validator_pass=1"
            ") "
            "select t.task_id original_task_id,t.unit_id,t.payload_json,d.decision_id,"
            "d.prompt_version,d.confidence,json_extract(d.decision_json,'$.final_type') prior_type,"
            "e.source_entity_type,e.semantic_entity_type "
            "from v2_model_tasks t join ranked d on d.task_id=t.task_id and d.rn=1 "
            "join v2_entities e on e.entity_id=t.unit_id "
            "where t.task_type='entity_type' and t.status='completed' "
            "and e.semantic_status='auto_accepted' "
            "and json_extract(d.decision_json,'$.final_type') is not null "
            "and e.semantic_entity_type=json_extract(d.decision_json,'$.final_type') "
            "order by t.unit_id"
        ).fetchall()
        inserted = 0
        existing = 0
        by_version = Counter()
        by_change = Counter()
        con.execute("begin immediate")
        for row in candidates:
            payload = {
                **json.loads(row["payload_json"]),
                "review_mode": "independent_model_second_review",
                "prior_model_type": row["prior_type"],
                "prior_decision_id": row["decision_id"],
                "prior_prompt_version": row["prompt_version"],
                "prior_confidence": row["confidence"],
            }
            task_id = stable_id("V2TASK", "entity", row["unit_id"], TASK_TYPE)
            cursor = con.execute(
                "insert or ignore into v2_model_tasks(task_id,unit_kind,unit_id,task_type,"
                "payload_json,status,attempts,priority,created_at,updated_at) "
                "values(?,?,?,?,?,'pending',0,15,?,?)",
                (
                    task_id, "entity", row["unit_id"], TASK_TYPE,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now, now,
                ),
            )
            inserted += cursor.rowcount
            existing += 1 - cursor.rowcount
            by_version[str(row["prompt_version"])] += 1
            by_change[f"{row['source_entity_type']}->{row['prior_type']}"] += 1
        con.commit()
        queue_counts = dict(con.execute(
            "select status,count(*) from v2_model_tasks where task_type=? group by status",
            (TASK_TYPE,),
        ).fetchall())
        report = {
            "result": "PASS",
            "task_type": TASK_TYPE,
            "eligible_prior_decisions": len(candidates),
            "inserted": inserted,
            "already_present": existing,
            "queue_counts": queue_counts,
            "by_prior_prompt_version": dict(sorted(by_version.items())),
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
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    print(json.dumps(prepare(args.db, args.report), ensure_ascii=False))


if __name__ == "__main__":
    main()
