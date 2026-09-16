# -*- coding: utf-8 -*-
"""mark_superseded_dirs.py — 旧版本目录顶部打 SUPERSEDED 横幅。"""
from pathlib import Path

BASE = Path(__file__).resolve().parents[3]
banner = ("> [SUPERSEDED 2026-09-16] 本目录为历史版本存档；最终权威数字见\n"
          "> `submission_work/final_submission_v3_1/AUTHORITATIVE_RESULTS.md`。\n\n")
targets = ["README.md", "README_FIRST.md",
           "FINAL_SUBMISSION_READINESS_REPORT.md",
           "00_FINAL_RELEASE_BASELINE.md", "FINAL_RESEARCH_REPORT.md"]
for d in ("final_submission", "final_submission_v2", "final_submission_v3",
          "final_release"):
    base = BASE / d
    if not base.exists():
        print("skip(无目录):", d)
        continue
    hit = None
    for t in targets:
        if (base / t).exists():
            hit = base / t
            break
    if hit is None:
        notice = base / "SUPERSEDED_NOTICE.md"
        notice.write_text(banner, encoding="utf-8")
        print("notice:", notice)
    else:
        text = hit.read_text(encoding="utf-8")
        if text.startswith("> [SUPERSEDED"):
            print("已带横幅:", hit.name)
            continue
        hit.write_text(banner + text, encoding="utf-8")
        print("bannered:", hit)
