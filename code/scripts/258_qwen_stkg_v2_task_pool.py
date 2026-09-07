"""Run bounded parallel one-candidate-per-process Qwen adjudication calls."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import sqlite3
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHILD = ROOT / "scripts" / "257_qwen_adjudicate_one_stkg_v2_task.py"
CLUSTER_CHILD = ROOT / "scripts" / "276_qwen_adjudicate_one_stkg_v2_name_cluster.py"
DATABASE = ROOT / "derived" / "red_culture_stkg_semantic_v2.sqlite"
DEFAULT_LOG = ROOT / "run_logs" / "stkg_v2_qwen_pool.jsonl"


def run_one(task_type: str, timeout: int, database: Path, task_id: str | None = None) -> dict:
    child = CLUSTER_CHILD if task_type in {
        "entity_name_cluster_first_review", "entity_name_cluster_second_review"
    } else CHILD
    command = [
        sys.executable, str(child), "--db", str(database), "--task-type", task_type,
        "--timeout", str(timeout),
    ]
    if task_id:
        command.extend(["--task-id", task_id])
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout + 90,
    )
    line = next((value for value in reversed(result.stdout.splitlines()) if value.strip().startswith("{")), "")
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        payload = {"status": "worker_error", "error": (result.stderr or result.stdout)[-1200:]}
    if result.returncode:
        payload = {"status": "worker_error", "error": (result.stderr or result.stdout)[-1200:]}
    return payload


def recover_stale_processing(database: Path, stale_seconds: int) -> int:
    cutoff = (datetime.now() - timedelta(seconds=stale_seconds)).isoformat(timespec="seconds")
    con = sqlite3.connect(database.resolve(), timeout=120)
    try:
        cursor = con.execute(
            "update v2_model_tasks set status='retryable_error',updated_at=? "
            "where status='processing' and updated_at<?",
            (datetime.now().isoformat(timespec="seconds"), cutoff),
        )
        con.commit()
        return cursor.rowcount
    finally:
        con.close()


def select_retry_task_ids(database: Path, task_type: str, count: int) -> list[str]:
    con = sqlite3.connect(database.resolve(), timeout=120)
    try:
        return [
            str(row[0])
            for row in con.execute(
                "select task_id from v2_model_tasks where status='retryable_error' "
                "and task_type=? and attempts<30 order by priority,updated_at,task_id limit ?",
                (task_type, max(0, count)),
            )
        ]
    finally:
        con.close()


def select_spatial_pending_entity_task_ids(database: Path, count: int) -> list[str]:
    con = sqlite3.connect(database.resolve(), timeout=120)
    try:
        return [
            str(row[0])
            for row in con.execute(
                "select distinct t.task_id from v2_assertion_spatial_anchors a "
                "join v2_model_tasks t on t.unit_kind='entity' "
                "and t.unit_id=a.source_canonical_place_id and t.task_type='entity_type' "
                "where a.anchor_kind='pending_entity_type' "
                "and t.status in ('pending','retryable_error') and t.attempts<30 "
                "order by case t.status when 'pending' then 0 else 1 end,"
                "t.priority,t.updated_at,t.task_id limit ?",
                (max(0, count),),
            )
        ]
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--db", type=Path, default=DATABASE)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--retry-only", action="store_true")
    parser.add_argument("--spatial-pending-only", action="store_true")
    parser.add_argument(
        "--task-type", choices=(
            "entity_type", "entity_type_classifier_review",
            "entity_type_model_second_review",
            "event_occurrence_time_adjudication",
            "entity_name_cluster_first_review",
            "entity_name_cluster_second_review",
        ),
        default="entity_type",
    )
    args = parser.parse_args()
    if args.spatial_pending_only and args.task_type != "entity_type":
        parser.error("--spatial-pending-only requires --task-type entity_type")
    if args.spatial_pending_only and args.retry_only:
        parser.error("--spatial-pending-only and --retry-only are mutually exclusive")
    workers = max(1, min(5, args.workers))
    recovered = recover_stale_processing(args.db, args.timeout + 90)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    samples = []
    errors = []
    if args.retry_only:
        work_items = select_retry_task_ids(args.db, args.task_type, args.count)
    elif args.spatial_pending_only:
        work_items = select_spatial_pending_entity_task_ids(args.db, args.count)
    else:
        work_items = [None] * max(0, args.count)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(run_one, args.task_type, args.timeout, args.db, task_id)
            for task_id in work_items
        ]
        for future in as_completed(futures):
            payload = future.result()
            with args.log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            stats[f"status:{payload.get('status', 'unknown')}"] += 1
            if payload.get("decision"):
                stats[f"decision:{payload['decision']}"] += 1
            if len(samples) < 10:
                samples.append(payload)
            if payload.get("status") in {"retryable_error", "worker_error"}:
                errors.append(payload)
    print(json.dumps(
        {"requested": len(work_items), "workers": workers, "task_type": args.task_type,
         "retry_only": args.retry_only,
         "spatial_pending_only": args.spatial_pending_only,
         "recovered_stale": recovered, "stats": dict(stats), "samples": samples,
         "errors": errors, "log": str(args.log)},
        ensure_ascii=False,
    ))
    if stats.get("status:worker_error"):
        raise RuntimeError("one or more V2 Qwen worker processes failed")


if __name__ == "__main__":
    main()
