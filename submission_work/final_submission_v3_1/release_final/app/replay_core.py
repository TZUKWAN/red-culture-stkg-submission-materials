# -*- coding: utf-8 -*-
"""replay_core.py — Level-A 离线回放核心（CLI 与 EXE 服务器共用）。"""
from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CN_TZ = timezone(timedelta(hours=8))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_all(release_root: Path) -> dict:
    rel = release_root.resolve()
    v31 = rel.parent
    gate = v31 / "experiments" / "07_provenance_semantic_gate"
    audit = rel / "audit"
    steps: list[dict] = []

    def step(name: str, ok: bool, detail: str) -> None:
        steps.append({"step": name, "pass": bool(ok), "detail": detail})

    snap_path = audit / "00_BASELINE_SNAPSHOT.json"
    if snap_path.exists():
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        ck = snap["files"].get("final_tiering_checkpoint_gz", {})
        pol = snap["files"].get("final_tiering_policy", {})
        step("archive_hash_checkpoint",
             ck.get("sha256") == sha256(gate / "FINAL_TIERING_CHECKPOINT.jsonl.gz"),
             str(ck.get("sha256", "?"))[:16])
        step("archive_hash_policy",
             pol.get("sha256") == sha256(gate / "FINAL_TIERING_POLICY.json"),
             str(pol.get("sha256", "?"))[:16])
    else:
        step("baseline_snapshot", False, "00_BASELINE_SNAPSHOT.json 缺失")

    bad = total = 0
    try:
        with gzip.open(gate / "FINAL_TIERING_CHECKPOINT.jsonl.gz", "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                total += 1
                try:
                    json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
        step("checkpoint_integrity", bad == 0, f"{total:,} records, {bad} malformed")
    except OSError as exc:
        step("checkpoint_integrity", False, f"gzip error: {exc}")

    r = subprocess.run([sys.executable, str(audit / "replay_final_tiering.py")],
                       capture_output=True, text=True, timeout=3600)
    diff_path = audit / "REBUILD_DIFF.json"
    if diff_path.exists():
        d = json.loads(diff_path.read_text(encoding="utf-8"))
        step("tiering_replay_identical", bool(d.get("identical")),
             f"rows={d.get('official_rows'):,} field_diffs={d.get('field_diff_total')}")
    else:
        step("tiering_replay_identical", False, (r.stderr or "no diff")[-300:])

    nums_path = rel / "manifests" / "FINAL_NUMBERS.json"
    db_path = rel / "data" / "red_culture_stkg_final.sqlite"
    if nums_path.exists() and db_path.exists():
        nums = json.loads(nums_path.read_text(encoding="utf-8"))
        actual = sha256(db_path)
        step("final_db_hash_matches_numbers", nums.get("final_db_sha256") == actual,
             actual[:16])
        hard = next((m for m in nums["metrics"]
                     if m["metric"] == "final_db_hard_violations"), {})
        step("final_db_hard_violations_zero", hard.get("value") == 0,
             f"violations={hard.get('value')}")
    else:
        step("final_db_hash_matches_numbers", False, "FINAL_NUMBERS 或 final DB 缺失")

    report = {
        "generated_at": datetime.now(CN_TZ).isoformat(),
        "mode": "Level-A offline replay (no LLM, no network)",
        "all_pass": all(s["pass"] for s in steps),
        "steps": steps,
    }
    out = audit / "REPLAY_REPORT.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
