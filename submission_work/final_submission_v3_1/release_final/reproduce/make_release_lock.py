# -*- coding: utf-8 -*-
"""make_release_lock.py — 生成发布锁（全部数字与哈希的最终封存）。"""
import hashlib
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
CN_TZ = timezone(timedelta(hours=8))


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def git(*a: str) -> str:
    return subprocess.run(["git", *a], cwd=REPO, capture_output=True,
                          text=True, timeout=60).stdout.strip()


nums = json.loads((ROOT / "manifests" / "FINAL_NUMBERS.json").read_text(encoding="utf-8"))
audit = json.loads((ROOT / "experiments" / "quality_audit" / "AUDIT_RESULTS.json")
                   .read_text(encoding="utf-8"))
replay = json.loads((ROOT / "audit" / "REPLAY_REPORT.json").read_text(encoding="utf-8"))

m = {x["metric"]: x["value"] for x in nums["metrics"]}
lock = {
    "locked": True,
    "locked_at": datetime.now(CN_TZ).isoformat(),
    "tag": "stkg-final-reproducible-2026",
    "git_head": git("log", "-1", "--format=%H"),
    "final_db_sha256": nums["final_db_sha256"],
    "package_sha256": "see SHA256SUMS.txt (self-reference excluded by design)",
    "final_numbers": {
        "total_assertions": m["total_assertions"],
        "gate_universe": m["gate_universe_old_strict"],
        "gate_strict": m["gate_strict"],
        "gate_contextual": m["gate_contextual"],
        "gate_unresolved": m["gate_unresolved"],
        "pending_hold": 0,
        "full_db_strict": m["full_db_strict_semantic"],
        "full_db_contextual": m["full_db_contextual"],
        "full_db_unresolved": m["full_db_unresolved"],
    },
    "independent_audit": {
        "decision": audit["decision"],
        "n": audit["n_judged_both"],
        "strict_support_precision_strong_consensus":
            audit["strict_support_precision_strong_consensus"],
        "false_positive_rate": audit["strict_false_positive_rate"],
        "cohens_kappa": audit["cohens_kappa"],
        "judges": ["gpt-oss-20b", "qwen/qwen3-8b"],
        "production_model": "qwen3.5-4b",
    },
    "replay_all_pass": replay["all_pass"],
}
out = ROOT / "manifests" / "RELEASE_LOCK.json"
out.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
print("[lock] wrote RELEASE_LOCK.json")
print(json.dumps(lock, ensure_ascii=False, indent=1)[:800])
