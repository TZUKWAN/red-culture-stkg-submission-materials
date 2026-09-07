# -*- coding: utf-8 -*-
"""Phase 0: generate audit/BASELINE_FREEZE_MANIFEST.json for final_submission_v3.

Freezes the current release: git state, metadata digests, SHA-256 of release
databases / source data / schema / existing experiment outputs / audit logs,
LFS-pointer verification for the final SQLite, Python environment, and random
seeds used by experiment scripts.

Read-only with respect to all original files; only writes the manifest.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]  # repository root
OUT = ROOT / "submission_work" / "final_submission_v3" / "audit" / "BASELINE_FREEZE_MANIFEST.json"

CHUNK = 1024 * 1024  # 1 MB streaming chunks


def sha256_streaming(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def file_entry(path: Path) -> dict:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256_streaming(path),
        "size_bytes": path.stat().st_size,
    }


def git_info() -> dict:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    dirty_lines = [ln for ln in status.splitlines() if ln.strip()]
    return {
        "commit": commit,
        "dirty": bool(dirty_lines),
        "status_porcelain": dirty_lines,
    }


def metadata_summary(path: Path) -> dict:
    entry = file_entry(path)
    summary = {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, dict):
            summary["top_level_keys"] = sorted(data.keys())
            for key in ("release", "release_id", "name", "version", "tag",
                        "created_at", "generated_at", "description"):
                if key in data:
                    summary[key] = data[key]
            # shallow scalar preview for small manifests
            preview = {}
            for k, v in data.items():
                if isinstance(v, (str, int, float, bool)) or v is None:
                    preview[k] = v
            if preview:
                summary["scalar_fields"] = preview
            if isinstance(data.get("files"), list):
                summary["file_count"] = len(data["files"])
        elif isinstance(data, list):
            summary["item_count"] = len(data)
    except Exception as exc:  # noqa: BLE001
        summary["parse_error"] = str(exc)
    entry["summary"] = summary
    return entry


def lfs_check(path: Path) -> dict:
    size = path.stat().st_size
    with open(path, "rb") as f:
        head = f.read(128)
    magic = b"SQLite format 3\x00"
    is_sqlite = head.startswith(magic)
    is_lfs_pointer = head.startswith(b"version https://git-lfs")
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "size_bytes": size,
        "header_hex": head[:16].hex(),
        "is_sqlite_format_3": is_sqlite,
        "is_lfs_pointer": is_lfs_pointer,
        "verdict": (
            "REAL_SQLITE_DATABASE" if is_sqlite and not is_lfs_pointer
            else ("LFS_POINTER_NOT_RESOLVED" if is_lfs_pointer else "UNKNOWN_FORMAT")
        ),
    }


# (pattern, group index, whether match is numeric). First group is the seed value.
SEED_PATTERNS = [
    (re.compile(r"random\.seed\(\s*([0-9]+)\s*\)"), True),
    (re.compile(r"np\.random\.seed\(\s*([0-9]+)\s*\)"), True),
    (re.compile(r"numpy\.random\.seed\(\s*([0-9]+)\s*\)"), True),
    (re.compile(r"np\.random\.default_rng\(\s*([0-9]+)\s*\)"), True),
    (re.compile(r"torch\.manual_seed\(\s*([0-9]+)\s*\)"), True),
    # uppercase constants such as BOOTSTRAP_SEED = 20260730, RANDOM_STATE = 20260730
    (re.compile(r"\b[A-Z][A-Z0-9_]*(?:SEED|RANDOM_STATE)\s*=\s*([0-9]+)"), True),
    # string seeds such as SPLIT_SEED = "paper-a-baseline-stratified-v1-20260730"
    (re.compile(r"\b[A-Z][A-Z0-9_]*SEED\s*=\s*[\"']([^\"']+)[\"']"), False),
    (re.compile(r"(?i)\brandom_state\s*=\s*([0-9]+)"), True),
    (re.compile(r"--seed[=\s]+([0-9]+)"), True),
]


def scan_seeds() -> list:
    results = []
    scan_dirs = [ROOT / "code" / "scripts",
                 ROOT / "submission_work" / "final_submission_v2" / "code" / "experiment_pipelines"]
    for d in scan_dirs:
        if not d.is_dir():
            continue
        for py in sorted(d.glob("*.py")):
            try:
                text = py.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            found = []
            for lineno, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                for pat, numeric in SEED_PATTERNS:
                    m = pat.search(line)
                    if m:
                        value = int(m.group(1)) if numeric else m.group(1)
                        found.append({"line": lineno, "seed": value,
                                      "snippet": stripped[:120]})
            if found:
                unique = sorted({str(f["seed"]) for f in found})
                results.append({
                    "script": py.relative_to(ROOT).as_posix(),
                    "seeds": unique,
                    "occurrences": found,
                })
    return results


def collect_files() -> list:
    files = []

    # metadata
    for name in ("CURRENT_RELEASE.json", "release_manifest.json"):
        files.append(metadata_summary(ROOT / "metadata" / name))

    # release databases
    for p in sorted((ROOT / "data" / "release_databases").glob("*.sqlite")):
        files.append(file_entry(p))

    # master data
    files.append(file_entry(ROOT / "data" / "source_data" / "master_data.csv"))

    # graph export
    for name in ("nodes.csv", "relationships.csv"):
        p = ROOT / "data" / "graph_export" / name
        if p.exists():
            files.append(file_entry(p))

    # schema (all files)
    for p in sorted((ROOT / "schema").rglob("*")):
        if p.is_file():
            files.append(file_entry(p))

    # v2 experiment csv/json
    for p in sorted((ROOT / "submission_work" / "final_submission_v2" / "experiments").rglob("*")):
        if p.is_file() and p.suffix.lower() in (".csv", ".json"):
            files.append(file_entry(p))

    # audit json/log
    for p in sorted((ROOT / "audit").rglob("*")):
        if p.is_file() and p.suffix.lower() in (".json", ".log"):
            files.append(file_entry(p))

    return files


def pip_freeze() -> list:
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True, text=True, check=True, timeout=120,
        ).stdout
        return sorted(ln.strip() for ln in out.splitlines() if ln.strip())
    except Exception as exc:  # noqa: BLE001
        return [f"pip freeze failed: {exc}"]


def main() -> None:
    files = collect_files()
    manifest = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(),
        "repository": str(ROOT),
        "git": git_info(),
        "python": {
            "version": sys.version.replace("\n", " "),
            "executable": sys.executable,
            "packages": pip_freeze(),
        },
        "seeds": scan_seeds(),
        "lfs_check": lfs_check(ROOT / "data" / "release_databases" / "red_culture_stkg_final_v2.sqlite"),
        "files": files,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"wrote {OUT}")
    print(f"file entries: {len(files)}")
    print(f"git dirty: {manifest['git']['dirty']}")
    print(f"lfs verdict: {manifest['lfs_check']['verdict']}")


if __name__ == "__main__":
    main()
