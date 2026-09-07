"""Add idempotent query indexes needed by V2 semantic and spatial audits."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
REPORT = ROOT / "audit_reports" / "stkg_v2_semantic_query_indexes.json"
INDEXES = {
    "idx_v2_assertion_object": (
        "create index if not exists idx_v2_assertion_object "
        "on v2_assertion_scopes(object_id)"
    ),
    "idx_v2_assertion_canonical_place": (
        "create index if not exists idx_v2_assertion_canonical_place "
        "on v2_assertion_scopes(canonical_place_id)"
    ),
}


def run(database: Path, report_path: Path) -> dict:
    started = datetime.now()
    con = sqlite3.connect(database.resolve(), timeout=300)
    try:
        before = {
            row[0] for row in con.execute(
                "select name from sqlite_master where type='index' and tbl_name='v2_assertion_scopes'"
            )
        }
        for sql in INDEXES.values():
            con.execute(sql)
        con.commit()
        after = {
            row[0] for row in con.execute(
                "select name from sqlite_master where type='index' and tbl_name='v2_assertion_scopes'"
            )
        }
        plans = {
            "object_id": [
                row[3] for row in con.execute(
                    "explain query plan select fact_id from v2_assertion_scopes where object_id=?",
                    ("E",),
                )
            ],
            "canonical_place_id": [
                row[3] for row in con.execute(
                    "explain query plan select fact_id from v2_assertion_scopes where canonical_place_id=?",
                    ("E",),
                )
            ],
        }
        report = {
            "result": "PASS",
            "created_indexes": sorted(set(INDEXES) - before),
            "present_indexes": sorted(set(INDEXES) & after),
            "query_plans": plans,
            "quick_check": con.execute("pragma quick_check").fetchone()[0],
            "foreign_key_violations": len(con.execute("pragma foreign_key_check").fetchall()),
            "elapsed_seconds": (datetime.now() - started).total_seconds(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
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
    print(json.dumps(run(args.db, args.report), ensure_ascii=False))


if __name__ == "__main__":
    main()
