# -*- coding: utf-8 -*-
"""Shared helpers for final_submission_v3 independent-eval data-prep scripts.

All database access is read-only (SQLite ``file:...?mode=ro`` URIs).
Nothing in this module writes to any pre-existing file.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

# repo_root/submission_work/final_submission_v3/code/independent_eval/_common.py
V3_ROOT = Path(__file__).resolve().parents[2]          # .../submission_work/final_submission_v3
REPO_ROOT = V3_ROOT.parents[1]                         # repo root

FINAL_DB = REPO_ROOT / "data" / "release_databases" / "red_culture_stkg_final_v2.sqlite"
SEMANTIC_DB = REPO_ROOT / "data" / "release_databases" / "red_culture_stkg_semantic_v2.sqlite"
# Upstream integrated pipeline DB (outside the submission repo). Accessed strictly
# read-only via mode=ro URI; required because the release DBs only carry evidence
# *ids* while the real source text lives in evidence_registry of this database.
INTEGRATION_DB = Path("D:/REDCULTUREDATA/final_stkg_pipeline/red_culture_semantic_integration_v1.sqlite")

MASTER_SEED = 20260907

EXP08 = V3_ROOT / "experiments" / "08_independent_reference"
EXP11 = V3_ROOT / "experiments" / "11_identity_validation"
EXP12 = V3_ROOT / "experiments" / "12_provenance_validation"

_CN_TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(_CN_TZ).isoformat(timespec="seconds")


def derive_seed(task_name: str, master_seed: int = MASTER_SEED) -> int:
    """Per-task seed derived as SHA-256(task_name + master_seed)."""
    h = hashlib.sha256(f"{task_name}|{master_seed}".encode("utf-8")).digest()
    return int.from_bytes(h[:8], "big") % (2**31)


def sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def _ro_uri(path: Path) -> str:
    return "file:" + str(path).replace("\\", "/") + "?mode=ro"


def connect_final() -> sqlite3.Connection:
    """Read-only connection to the final release DB with the semantic DB attached."""
    con = sqlite3.connect(_ro_uri(FINAL_DB), uri=True)
    con.execute(f"ATTACH DATABASE '{_ro_uri(SEMANTIC_DB)}' AS sem")
    con.row_factory = sqlite3.Row
    return con


def attach_integration(con: sqlite3.Connection) -> None:
    con.execute(f"ATTACH DATABASE '{_ro_uri(INTEGRATION_DB)}' AS up")


def write_manifest(out_dir: Path, name: str, manifest: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return path


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def db_hashes() -> dict:
    return {
        "final_db_path": str(FINAL_DB),
        "final_db_sha256": sha256_file(FINAL_DB),
        "semantic_db_path": str(SEMANTIC_DB),
        "semantic_db_sha256": sha256_file(SEMANTIC_DB),
    }
