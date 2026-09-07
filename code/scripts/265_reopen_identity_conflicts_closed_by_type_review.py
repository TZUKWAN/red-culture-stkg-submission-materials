"""Reopen identity conflicts that were incorrectly closed by entity type decisions."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_identity_conflict_status_repair.json"
TYPE_TASKS = (
    "entity_type", "entity_type_classifier_review", "entity_type_model_second_review",
)


def candidates(con: sqlite3.Connection) -> list[sqlite3.Row]:
    marks = ",".join("?" for _ in TYPE_TASKS)
    return con.execute(
        "select c.conflict_id,c.unit_id,c.resolution_decision_id,c.resolved_at,"
        "e.canonical_name,t.task_type "
        "from v2_semantic_conflicts c "
        "join v2_entities e on e.entity_id=c.unit_id "
        "join v2_model_decisions d on d.decision_id=c.resolution_decision_id "
        "join v2_model_tasks t on t.task_id=d.task_id "
        "where c.conflict_type='identity_ambiguity' and c.status='resolved' "
        f"and t.task_type in ({marks}) order by c.conflict_id",
        TYPE_TASKS,
    ).fetchall()


def run(database: Path, report_path: Path, apply: bool) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        rows = candidates(con)
        repaired = 0
        if apply:
            con.execute("begin immediate")
            for row in rows:
                cursor = con.execute(
                    "update v2_semantic_conflicts set status='open',"
                    "resolution_decision_id=null,resolved_at=null where conflict_id=? "
                    "and conflict_type='identity_ambiguity' and status='resolved'",
                    (row["conflict_id"],),
                )
                repaired += cursor.rowcount
            con.commit()
        report = {
            "result": "PASS",
            "apply": apply,
            "candidate_count": len(rows),
            "repaired": repaired,
            "candidates": [dict(row) for row in rows],
            "open_identity_conflicts": con.execute(
                "select count(*) from v2_semantic_conflicts "
                "where conflict_type='identity_ambiguity' and status='open'"
            ).fetchone()[0],
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
