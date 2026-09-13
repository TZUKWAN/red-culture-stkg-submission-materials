# -*- coding: utf-8 -*-
"""make_baseline_snapshot.py — PHASE 0：只读基线与不可篡改审计锚点。

对最终分层战役的全部关键产物计算 SHA256，记录 git/Python/OS 环境，
写入 release_final/audit/00_BASELINE_SNAPSHOT.json，并做二次哈希回读校验。

只读既有产物，不修改任何数据文件。
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # .../final_submission_v3_1
REPO = ROOT.parents[1]                               # 仓库根（投稿材料_代码数据整理包）
GATE = ROOT / "experiments" / "07_provenance_semantic_gate"
OUT = ROOT / "release_final" / "audit" / "00_BASELINE_SNAPSHOT.json"
CN_TZ = timezone(timedelta(hours=8))


def sha256(path: Path, buf: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                              text=True, timeout=60).stdout.strip()
    except Exception as exc:
        return f"<git error: {exc}>"


KEY_FILES = {
    "final_tiering_csv": GATE / "FINAL_TIERING.csv",
    "final_tiering_summary": GATE / "FINAL_TIERING_SUMMARY.json",
    "final_tiering_checkpoint_gz": GATE / "FINAL_TIERING_CHECKPOINT.jsonl.gz",
    "final_tiering_policy": GATE / "FINAL_TIERING_POLICY.json",
    "final_tiering_rules": GATE / "FINAL_TIERING_RULES.json",
    "final_tiering_features": GATE / "FINAL_TIERING_FEATURES.csv",
    "final_tiering_features_meta": GATE / "FINAL_TIERING_FEATURES_META.json",
    "evidence_gate_verdicts": GATE / "EVIDENCE_GATE_VERDICTS.jsonl",
    "evidence_gate_checkpoint": GATE / "EVIDENCE_GATE_CHECKPOINT.jsonl",
    "final_evidence_report": ROOT / "audit" / "method_final" / "FINAL_EVIDENCE_REPORT.md",
    "provider": ROOT / "code" / "independent_eval" / "lmstudio_provider.py",
    "build_final_tiering": ROOT / "code" / "experiment_pipelines" / "build_final_tiering.py",
    "semantic_gate": ROOT / "code" / "experiment_pipelines" / "run_evidence_semantic_gate.py",
}


def find_final_db() -> list[Path]:
    """定位候选 final SQLite（只记录，不打开写句柄）。"""
    pats = ["*.sqlite", "*.db"]
    hits: list[Path] = []
    for base in (ROOT / "data", ROOT):
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in (".sqlite", ".db") and ".tmp_" not in p.name:
                hits.append(p)
    return sorted(set(hits), key=lambda p: p.stat().st_size, reverse=True)[:12]


def main() -> int:
    snap: dict = {
        "task": "PHASE 0 baseline snapshot (read-only audit anchor)",
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "git": {
            "head": git("log", "-1", "--format=%H %s"),
            "branch": git("branch", "--show-current"),
            "status_short": git("status", "--short")[:2000],
        },
        "env": {
            "python": sys.version,
            "os": platform.platform(),
            "machine": platform.machine(),
        },
        "files": {},
        "candidate_databases": [],
    }
    missing = []
    for name, p in KEY_FILES.items():
        if not p.exists():
            missing.append(str(p))
            continue
        h1 = sha256(p)
        h2 = sha256(p)          # 回读校验：两次哈希必须一致
        snap["files"][name] = {
            "path": str(p.relative_to(REPO)),
            "sha256": h1,
            "sha256_recheck": h2,
            "match": h1 == h2,
            "bytes": p.stat().st_size,
        }
    for db in find_final_db():
        h1 = sha256(db)
        snap["candidate_databases"].append({
            "path": str(db.relative_to(REPO)),
            "sha256": h1,
            "sha256_recheck": sha256(db),
            "bytes": db.stat().st_size,
        })
    snap["missing_files"] = missing
    snap["all_hashes_consistent"] = all(
        f["match"] for f in snap["files"].values()
    ) and all(d["sha256"] == d["sha256_recheck"] for d in snap["candidate_databases"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[baseline] wrote {OUT.name}")
    print(f"[baseline] files hashed: {len(snap['files'])}, "
          f"candidate DBs: {len(snap['candidate_databases'])}, missing: {len(missing)}")
    print(f"[baseline] all_hashes_consistent = {snap['all_hashes_consistent']}")
    for name, f in snap["files"].items():
        print(f"  {f['sha256'][:16]}  {name}")
    for d in snap["candidate_databases"]:
        print(f"  DB {d['sha256'][:16]}  {d['bytes']:,}B  {d['path']}")
    return 0 if snap["all_hashes_consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
