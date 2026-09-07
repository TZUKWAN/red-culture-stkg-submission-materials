import importlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path


pool = importlib.import_module("scripts.258_qwen_stkg_v2_task_pool")


class V2QwenPoolTests(unittest.TestCase):
    def test_only_stale_processing_tasks_are_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "queue.sqlite"
            con = sqlite3.connect(database)
            try:
                con.execute(
                    "create table v2_model_tasks(task_id text,status text,updated_at text)"
                )
                old = (datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds")
                fresh = datetime.now().isoformat(timespec="seconds")
                con.executemany(
                    "insert into v2_model_tasks values(?,?,?)",
                    [("old", "processing", old), ("fresh", "processing", fresh),
                     ("pending", "pending", old)],
                )
                con.commit()
            finally:
                con.close()
            recovered = pool.recover_stale_processing(database, 300)
            self.assertEqual(recovered, 1)
            con = sqlite3.connect(database)
            try:
                statuses = dict(con.execute("select task_id,status from v2_model_tasks"))
            finally:
                con.close()
            self.assertEqual(statuses["old"], "retryable_error")
            self.assertEqual(statuses["fresh"], "processing")
            self.assertEqual(statuses["pending"], "pending")

    def test_retry_selection_excludes_pending_and_other_task_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "queue.sqlite"
            con = sqlite3.connect(database)
            try:
                con.execute(
                    "create table v2_model_tasks(task_id text,status text,task_type text,"
                    "attempts integer,priority integer,updated_at text)"
                )
                con.executemany(
                    "insert into v2_model_tasks values(?,?,?,?,?,?)",
                    [
                        ("retry-entity", "retryable_error", "entity_type", 1, 1, "2026-01-01"),
                        ("pending-entity", "pending", "entity_type", 0, 1, "2026-01-01"),
                        ("retry-time", "retryable_error", "event_occurrence_time_adjudication", 1, 1, "2026-01-01"),
                        ("exhausted", "retryable_error", "entity_type", 30, 1, "2026-01-01"),
                    ],
                )
                con.commit()
            finally:
                con.close()
            self.assertEqual(
                pool.select_retry_task_ids(database, "entity_type", 10), ["retry-entity"]
            )

    def test_spatial_pending_selection_uses_exact_task_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "queue.sqlite"
            con = sqlite3.connect(database)
            try:
                con.executescript(
                    """
                    create table v2_model_tasks(
                      task_id text,status text,task_type text,attempts integer,priority integer,
                      updated_at text,unit_kind text,unit_id text
                    );
                    create table v2_assertion_spatial_anchors(
                      source_canonical_place_id text,anchor_kind text
                    );
                    """
                )
                con.executemany(
                    "insert into v2_model_tasks values(?,?,?,?,?,?,?,?)",
                    [
                        ("target", "pending", "entity_type", 0, 1, "2026-01-01", "entity", "E1"),
                        ("not-spatial", "pending", "entity_type", 0, 1, "2026-01-01", "entity", "E2"),
                        ("wrong-type", "pending", "event_occurrence_time_adjudication", 0, 1, "2026-01-01", "entity", "E1"),
                        ("done", "completed", "entity_type", 1, 1, "2026-01-01", "entity", "E3"),
                    ],
                )
                con.executemany(
                    "insert into v2_assertion_spatial_anchors values(?,?)",
                    [("E1", "pending_entity_type"), ("E3", "pending_entity_type")],
                )
                con.commit()
            finally:
                con.close()
            self.assertEqual(
                pool.select_spatial_pending_entity_task_ids(database, 10), ["target"]
            )


if __name__ == "__main__":
    unittest.main()
