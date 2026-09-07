"""Reset pre-SocialGroup name-cluster canaries while preserving their decision history."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_social_group_review_reset.json"
OLD_PROMPT_VERSION = "stkg-v2-name-cluster-adjudication-1"
FIRST_TASK = "entity_name_cluster_first_review"
SECOND_TASK = "entity_name_cluster_second_review"


def candidate_rows(con: sqlite3.Connection) -> list[sqlite3.Row]:
    return con.execute(
        "select distinct c.cluster_id,c.canonical_name,ft.task_id first_task_id," 
        "st.task_id second_task_id from v2_name_clusters c "
        "join v2_model_tasks ft on json_extract(ft.payload_json,'$.cluster_id')=c.cluster_id "
        "and ft.task_type=? join v2_model_tasks st "
        "on json_extract(st.payload_json,'$.cluster_id')=c.cluster_id and st.task_type=? "
        "join v2_model_decisions d on d.task_id=ft.task_id "
        "where d.prompt_version=? and ft.status='completed' and not exists ("
        "select 1 from v2_model_decisions sd where sd.task_id=st.task_id) "
        "and exists (select 1 from v2_name_cluster_members m "
        "join v2_model_tasks et on et.unit_kind='entity' and et.unit_id=m.entity_id "
        "and et.task_type='entity_type' where m.cluster_id=c.cluster_id and et.status='pending') "
        "order by c.cluster_id",
        (FIRST_TASK, SECOND_TASK, OLD_PROMPT_VERSION),
    ).fetchall()


def run(database: Path, report_path: Path, apply: bool) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        rows = candidate_rows(con)
        updated_first = updated_second = updated_clusters = 0
        if apply:
            con.execute("begin immediate")
            for row in rows:
                updated_first += con.execute(
                    "update v2_model_tasks set status='pending',updated_at=? where task_id=?",
                    (now, row["first_task_id"]),
                ).rowcount
                updated_second += con.execute(
                    "update v2_model_tasks set status='pending',updated_at=? where task_id=?",
                    (now, row["second_task_id"]),
                ).rowcount
                updated_clusters += con.execute(
                    "update v2_name_clusters set status='pending_first',updated_at=? where cluster_id=?",
                    (now, row["cluster_id"]),
                ).rowcount
            con.commit()
        remaining = len(candidate_rows(con)) if apply else len(rows)
        report = {
            "result": "PASS" if not apply or remaining == 0 else "FAIL",
            "apply": apply,
            "old_prompt_version": OLD_PROMPT_VERSION,
            "candidate_count": len(rows),
            "updated_first_tasks": updated_first,
            "updated_second_tasks": updated_second,
            "updated_clusters": updated_clusters,
            "remaining_candidates": remaining,
            "clusters": [
                {"cluster_id": row["cluster_id"], "canonical_name": row["canonical_name"]}
                for row in rows
            ],
            "preserved_old_decisions": con.execute(
                "select count(*) from v2_model_decisions where prompt_version=?",
                (OLD_PROMPT_VERSION,),
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
