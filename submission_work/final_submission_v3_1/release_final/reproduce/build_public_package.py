# -*- coding: utf-8 -*-
"""build_public_package.py — PHASE 6：PUBLIC_REPRO_PACKAGE.zip 组装。

打包原则（对应 DATA_RIGHTS_MANIFEST.csv）：
  - public/redistributable：代码、文档、manifest、审计产物、最终库（合法可公开版）
  - derived-only：FINAL_TIERING.csv、checkpoint gz（仅短引文 ≤400 字）
  - excluded：源文献全文（private-source，绝不入包）
产物：release_final/dist/PUBLIC_REPRO_PACKAGE.zip + SHA256SUMS.txt
"""
from __future__ import annotations

import hashlib
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]           # release_final/
V31 = ROOT.parent
DIST = ROOT / "dist"
CN_TZ = timezone(timedelta(hours=8))

INCLUDE = [
    ("README_FIRST.md", ROOT / "README_FIRST.md"),
    ("app/", ROOT / "app"),
    ("audit/", ROOT / "audit"),
    ("configs/", ROOT / "configs"),
    ("data/red_culture_stkg_final.sqlite", ROOT / "data" / "red_culture_stkg_final.sqlite"),
    ("docs/", ROOT / "docs"),
    ("experiments/quality_audit/", ROOT / "experiments" / "quality_audit"),
    ("manifests/", ROOT / "manifests"),
    ("reproduce/", ROOT / "reproduce"),
    ("reports/", ROOT / "reports"),
    ("tests/", ROOT / "tests"),
    ("../experiments/07_provenance_semantic_gate/FINAL_TIERING.csv",
     V31 / "experiments" / "07_provenance_semantic_gate" / "FINAL_TIERING.csv"),
    ("../experiments/07_provenance_semantic_gate/FINAL_TIERING_CHECKPOINT.jsonl.gz",
     V31 / "experiments" / "07_provenance_semantic_gate" / "FINAL_TIERING_CHECKPOINT.jsonl.gz"),
    ("../experiments/07_provenance_semantic_gate/FINAL_TIERING_POLICY.json",
     V31 / "experiments" / "07_provenance_semantic_gate" / "FINAL_TIERING_POLICY.json"),
    ("../experiments/07_provenance_semantic_gate/FINAL_TIERING_SUMMARY.json",
     V31 / "experiments" / "07_provenance_semantic_gate" / "FINAL_TIERING_SUMMARY.json"),
    ("../audit/method_final/FINAL_EVIDENCE_REPORT.md",
     V31 / "audit" / "method_final" / "FINAL_EVIDENCE_REPORT.md"),
    ("code/experiment_pipelines/build_final_tiering.py",
     V31 / "code" / "experiment_pipelines" / "build_final_tiering.py"),
    ("code/experiment_pipelines/run_evidence_semantic_gate.py",
     V31 / "code" / "experiment_pipelines" / "run_evidence_semantic_gate.py"),
    ("code/independent_eval/lmstudio_provider.py",
     V31 / "code" / "independent_eval" / "lmstudio_provider.py"),
]


def sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    zip_path = DIST / "PUBLIC_REPRO_PACKAGE.zip"
    if zip_path.exists():
        zip_path.unlink()
    n = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for arc, p in INCLUDE:
            if p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file() and "__pycache__" not in f.name:
                        zf.write(f, arc + f.relative_to(p).as_posix())
                        n += 1
            elif p.exists():
                zf.write(p, arc)
                n += 1
            else:
                print(f"[warn] missing: {p}")
    sums = DIST / "SHA256SUMS.txt"
    lines = []
    for arc, p in INCLUDE:
        target = p
        if target.exists():
            if target.is_dir():
                continue
            lines.append(f"{sha256_of(target)}  {arc}")
    # 发布资产（EXE / figures / 报告）也纳入哈希清单
    exe = ROOT / "YangtzeSTKG-Reproduce.exe"
    if exe.exists():
        lines.append(f"{sha256_of(exe)}  YangtzeSTKG-Reproduce.exe")
    for extra in (ROOT / "figures").glob("*.png"):
        lines.append(f"{sha256_of(extra)}  figures/{extra.name}")
    for extra in (ROOT / "reports").glob("*.md"):
        lines.append(f"{sha256_of(extra)}  reports/{extra.name}")
    lines.append(f"{sha256_of(zip_path)}  PUBLIC_REPRO_PACKAGE.zip")
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[package] {zip_path.name}: {n} files, "
          f"{zip_path.stat().st_size / 1e6:.1f} MB; SHA256SUMS.txt written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
