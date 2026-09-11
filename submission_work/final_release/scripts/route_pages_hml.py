# -*- coding: utf-8 -*-
"""route_pages_hml.py — 290k signal-positive + 12k no-signal 页面 H/M/L 路由。

路由规则：
  HIGH: score >= 5 且 text_length >= 200  → LLM candidate extraction（多通道）
  MEDIUM: score 2-4 或 (score>=5 且 text<200) → deterministic extraction + entity lexicon
  LOW: score 0-1 → 仅纳入 page coverage 统计，不做候选抽取
  NO_SIGNAL: score=0 → 抽 500 页做 false-negative rate 测量

输出：PAGE_ROUTING_HML.csv（全量 302,230 行）+ ROUTING_SUMMARY.json + FALSE_NEG_SAMPLE.json
"""
import csv, json, random, os
from collections import Counter
from pathlib import Path

SEED = 20260910
IN_CSV = Path(__file__).resolve().parents[1] / "data" / "PAGE_SCREENING.csv"
OUT_DIR = Path(__file__).resolve().parents[1] / "data"

def main():
    rows = list(csv.DictReader(open(IN_CSV, encoding="utf-8-sig")))
    print(f"input: {len(rows)} pages")
    rng = random.Random(SEED)

    out_csv = OUT_DIR / "PAGE_ROUTING_HML.csv"
    summary = {"total": len(rows), "route": Counter(), "no_signal_fn_sample": []}
    fn_pool = []

    with open(out_csv, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) + ["route", "route_reason"])
        w.writeheader()
        for r in rows:
            score = int(r["page_screening_score"])
            tlen = int(r["text_length"])
            if score == 0:
                route = "NO_SIGNAL"
                reason = "no screening signal"
                fn_pool.append(r)
            elif score >= 5 and tlen >= 200:
                route = "HIGH"
                reason = f"score={score}, text={tlen}"
            elif score >= 2:
                route = "MEDIUM"
                reason = f"score={score}"
            else:
                route = "LOW"
                reason = f"score={score}, minimal signal"
            w.writerow({**r, "route": route, "route_reason": reason})
            summary["route"][route] = summary["route"].get(route, 0) + 1

    # no-signal 抽 500 页做 false-negative rate 测量
    rng.shuffle(fn_pool)
    fn_sample = fn_pool[:500]
    fn_path = OUT_DIR / "FALSE_NEG_SAMPLE.json"
    fn_path.write_text(json.dumps(
        [{"page_path": r["page_path"], "book_title": r["book_title"],
          "text_length": r["text_length"]} for r in fn_sample],
        ensure_ascii=False, indent=2), encoding="utf-8")

    summary["no_signal_fn_sample_n"] = len(fn_sample)
    summary["route_file"] = str(out_csv)

    (OUT_DIR / "ROUTING_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("route distribution:", summary["route"])
    print(f"false-negative sample: {len(fn_sample)} pages")
    print(f"output: {out_csv}")

if __name__ == "__main__":
    main()
