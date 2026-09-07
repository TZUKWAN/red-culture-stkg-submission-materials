"""Create one first-review task per unresolved exact-name V2 entity cluster."""

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
REPORT = ROOT / "audit_reports" / "stkg_v2_name_cluster_review_preparation.json"
METHOD_VERSION = "stkg-v2-name-cluster-review-1"
FIRST_TASK = "entity_name_cluster_first_review"


def stable_id(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        create table if not exists v2_name_clusters(
          cluster_id text primary key,
          canonical_name text not null,
          representative_entity_id text not null references v2_entities(entity_id),
          status text not null check(status in (
            'pending_first','first_completed','pending_second','completed','manual_review'
          )),
          member_count integer not null check(member_count>=1),
          assertion_count integer not null check(assertion_count>=0),
          method_version text not null,
          created_at text not null,
          updated_at text not null
        ) without rowid;
        create unique index if not exists idx_v2_name_cluster_name
          on v2_name_clusters(canonical_name);
        create index if not exists idx_v2_name_cluster_status
          on v2_name_clusters(status,assertion_count);
        create table if not exists v2_name_cluster_members(
          cluster_id text not null references v2_name_clusters(cluster_id),
          entity_id text not null references v2_entities(entity_id),
          source_entity_type text not null,
          primary key(cluster_id,entity_id)
        ) without rowid;
        create unique index if not exists idx_v2_name_cluster_member_entity
          on v2_name_cluster_members(entity_id);
        """
    )


def table_exists(con: sqlite3.Connection, table_name: str) -> bool:
    return con.execute(
        "select 1 from sqlite_master where type='table' and name=?", (table_name,)
    ).fetchone() is not None


def priority_for(assertion_count: int) -> int:
    if assertion_count >= 100:
        return 10
    if assertion_count >= 20:
        return 20
    if assertion_count >= 5:
        return 30
    return 40


def unresolved_clusters(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "select e.entity_id,e.canonical_name,e.source_entity_type,"
        "(select count(*) from v2_assertion_scopes a "
        " where a.subject_id=e.entity_id or a.object_id=e.entity_id) assertion_count "
        "from v2_entities e join v2_model_tasks t on t.unit_kind='entity' "
        "and t.unit_id=e.entity_id and t.task_type='entity_type' "
        "where t.status='pending' and e.semantic_status='model_review' "
        "order by e.canonical_name,e.entity_id"
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["canonical_name"]), []).append(row)
    result = []
    for name, members in grouped.items():
        result.append({
            "cluster_id": stable_id("V2NAME", METHOD_VERSION, name),
            "canonical_name": name,
            "representative_entity_id": str(members[0]["entity_id"]),
            "members": members,
            "assertion_count": sum(int(row["assertion_count"]) for row in members),
        })
    return result


def run(database: Path, report_path: Path, apply: bool) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys=on")
    try:
        if apply:
            ensure_schema(con)
        clusters = unresolved_clusters(con)
        existing_names = set()
        if table_exists(con, "v2_name_clusters"):
            existing_names = {
                str(row[0]) for row in con.execute("select canonical_name from v2_name_clusters")
            }
        candidates = [item for item in clusters if item["canonical_name"] not in existing_names]
        by_size = Counter(
            "1" if len(item["members"]) == 1
            else "2-5" if len(item["members"]) <= 5
            else "6+"
            for item in candidates
        )
        inserted_clusters = inserted_members = inserted_tasks = 0
        if apply:
            con.execute("begin immediate")
            for item in candidates:
                con.execute(
                    "insert into v2_name_clusters values(?,?,?,?,?,?,?,?,?)",
                    (
                        item["cluster_id"], item["canonical_name"],
                        item["representative_entity_id"], "pending_first",
                        len(item["members"]), item["assertion_count"],
                        METHOD_VERSION, now, now,
                    ),
                )
                inserted_clusters += 1
                for member in item["members"]:
                    con.execute(
                        "insert into v2_name_cluster_members values(?,?,?)",
                        (item["cluster_id"], member["entity_id"], member["source_entity_type"]),
                    )
                    inserted_members += 1
                task_id = stable_id("V2TASK", item["cluster_id"], FIRST_TASK)
                cursor = con.execute(
                    "insert or ignore into v2_model_tasks values(?,?,?,?,?,?,?,?,?,?)",
                    (
                        task_id, "entity", item["representative_entity_id"], FIRST_TASK,
                        json.dumps({
                            "cluster_id": item["cluster_id"],
                            "canonical_name": item["canonical_name"],
                            "member_ids": [str(row["entity_id"]) for row in item["members"]],
                            "review_round": 1,
                        }, ensure_ascii=False, sort_keys=True),
                        "pending", 0, priority_for(item["assertion_count"]), now, now,
                    ),
                )
                inserted_tasks += cursor.rowcount
            con.commit()
        report = {
            "result": "PASS",
            "apply": apply,
            "method_version": METHOD_VERSION,
            "unresolved_cluster_count": len(clusters),
            "candidate_cluster_count": len(candidates),
            "candidate_member_count": sum(len(item["members"]) for item in candidates),
            "inserted_clusters": inserted_clusters,
            "inserted_members": inserted_members,
            "inserted_tasks": inserted_tasks,
            "by_cluster_size": dict(sorted(by_size.items())),
            "max_cluster_size": max((len(item["members"]) for item in clusters), default=0),
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
