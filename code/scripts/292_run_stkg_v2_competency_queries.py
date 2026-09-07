"""Execute all V2 research competency queries against the final SQLite database read-only."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "stkg" / "schema" / "competency_query_contract_v2.yaml"

DENIED_ACTIONS = {
    sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
    sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_TEMP_INDEX,
    sqlite3.SQLITE_CREATE_TEMP_TABLE, sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
    sqlite3.SQLITE_CREATE_TEMP_VIEW, sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_CREATE_VIEW,
    sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_DROP_TEMP_INDEX,
    sqlite3.SQLITE_DROP_TEMP_TABLE, sqlite3.SQLITE_DROP_TEMP_TRIGGER,
    sqlite3.SQLITE_DROP_TEMP_VIEW, sqlite3.SQLITE_DROP_TRIGGER, sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH,
    sqlite3.SQLITE_REINDEX,
}


def load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_only_authorizer(action, _arg1, _arg2, _database, _source):
    return sqlite3.SQLITE_DENY if action in DENIED_ACTIONS else sqlite3.SQLITE_OK


def open_read_only(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("pragma query_only=on")
    con.set_authorizer(read_only_authorizer)
    return con


def normalize(value):
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    return value


def execute_query(con: sqlite3.Connection, sql: str, required: list[str], preview_limit: int = 12) -> dict:
    started = time.perf_counter()
    cursor = con.execute(sql)
    columns = [item[0] for item in cursor.description or []]
    digest = hashlib.sha256()
    preview = []
    row_count = 0
    null_counts = {column: 0 for column in required}
    for row in cursor:
        payload = {column: normalize(row[column]) for column in columns}
        digest.update(
            (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            .encode("utf-8")
        )
        if len(preview) < preview_limit:
            preview.append(payload)
        row_count += 1
        for column in required:
            if column in columns and row[column] is None:
                null_counts[column] += 1
    return {
        "columns": columns,
        "missing_required_columns": sorted(set(required) - set(columns)),
        "required_null_counts": null_counts,
        "row_count": row_count,
        "rows_sha256": digest.hexdigest(),
        "preview": preview,
        "elapsed_seconds": round(time.perf_counter() - started, 6),
    }


def atomic_write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_contract(contract_path: Path) -> dict:
    contract = load_yaml(contract_path)
    database = (ROOT / contract["database"]).resolve()
    query_dir = (ROOT / contract["query_directory"]).resolve()
    report_path = (ROOT / contract["report"]).resolve()
    if not database.exists():
        raise FileNotFoundError(database)
    before = {
        "path": str(database), "size_bytes": database.stat().st_size,
        "mtime_ns": database.stat().st_mtime_ns, "sha256": sha256(database),
    }
    failures = []
    results = {}
    con = open_read_only(database)
    try:
        quick_check = str(con.execute("pragma quick_check").fetchone()[0])
        foreign_key_errors = len(con.execute("pragma foreign_key_check").fetchall())
        if quick_check != "ok":
            failures.append(f"quick_check={quick_check}")
        if foreign_key_errors:
            failures.append(f"foreign_key_errors={foreign_key_errors}")
        for query_id, spec in contract["queries"].items():
            query_path = query_dir / spec["file"]
            try:
                sql = query_path.read_text(encoding="utf-8")
                result = execute_query(con, sql, list(spec["required"]))
                result.update({
                    "file": str(query_path), "file_sha256": sha256(query_path),
                    "required_columns": list(spec["required"]),
                })
                results[query_id] = result
                if result["missing_required_columns"]:
                    failures.append(
                        f"{query_id} missing columns={result['missing_required_columns']}"
                    )
                if result["row_count"] == 0 and not spec.get("allow_empty", False):
                    failures.append(f"{query_id} returned zero rows")
            except Exception as exc:
                failures.append(f"{query_id} failed: {type(exc).__name__}: {exc}")
    finally:
        con.close()
    after = {
        "size_bytes": database.stat().st_size, "mtime_ns": database.stat().st_mtime_ns,
        "sha256": sha256(database),
    }
    after["unchanged"] = all(after[key] == before[key] for key in ("size_bytes", "mtime_ns", "sha256"))
    if not after["unchanged"]:
        failures.append("final V2 database changed during read-only competency queries")
    expected_query_count = len(contract["queries"])
    if expected_query_count != 26:
        failures.append(f"contract query count={expected_query_count}, expected=26")
    if len(results) != expected_query_count:
        failures.append(f"executed query count={len(results)}, expected={expected_query_count}")
    combined = hashlib.sha256()
    for query_id in sorted(results):
        combined.update(f"{query_id}:{results[query_id]['rows_sha256']}\n".encode("utf-8"))
    report = {
        "status": "PASS" if not failures else "FAIL",
        "build_version": "red-culture-stkg-v2-competency-queries-1",
        "contract": {"path": str(contract_path.resolve()), "sha256": sha256(contract_path)},
        "database_before": {**before, "quick_check": quick_check, "foreign_key_errors": foreign_key_errors},
        "database_after": after,
        "query_count": len(results),
        "combined_rows_sha256": combined.hexdigest(),
        "queries": results,
        "failures": failures,
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    atomic_write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=CONTRACT)
    args = parser.parse_args()
    report = run_contract(args.contract.resolve())
    print(json.dumps({
        "status": report["status"], "query_count": report["query_count"],
        "combined_rows_sha256": report["combined_rows_sha256"],
        "failures": report["failures"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
